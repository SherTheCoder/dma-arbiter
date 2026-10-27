/*
 * GPDMA1 port-mapping bench for the STM32N6570-DK.
 *
 * The host (board/run.py) writes a batch of jobs into `jobs` over SWD, bumps
 * ctl.go and waits for ctl.done to match. A job is up to 8 GPDMA1 channels,
 * each moving 32-bit words from one endpoint to another on software request,
 * so they all go as fast as the bus lets them, like the RTL fabric does. An
 * endpoint is an APB2 register or the channel's own buffer in AXISRAM1 or
 * AHBSRAM. Channel c is enabled ch[c].delay CPU cycles after the job's t0,
 * and the DWT cycle counter stamps every enable and every transfer complete.
 *
 * A job can also name a probe channel. It isn't started with the others;
 * once they're running it does `probes` short blocks one after another and
 * each one is timed from enable to TCF.
 *
 * All times are CPU cycles, 600 MHz, so 3 per AHB cycle. The D-cache stays
 * off so the host reads what the CPU wrote and the other way round.
 */
#include <string.h>
#include "stm32n6xx_hal.h"

#define NCH        8
#define MAX_JOBS   512
#define MAX_PROBES 32
#define BUF_WORDS  8192
#define MAGIC      0x444d4142u      /* "DMAB" */
#define TIMEOUT    60000000u        /* 100 ms */
#define F_TIMEOUT  (1u << 31)

/* endpoints 0-7 are the apb[] registers, the rest are memory */
enum { MEM = 8, SCRATCH, AHB };

struct chan {
    uint8_t  src, dst;  /* endpoints */
    uint8_t  burst;     /* beats, same on both sides */
    uint8_t  ports;     /* bit 0 source port, bit 1 destination port */
    uint16_t words;     /* 0: channel not used */
    uint16_t delay;     /* CPU cycles after t0 */
};

struct job {
    struct chan ch[NCH];
    uint8_t  probe;       /* probe channel, 0xff for none */
    uint8_t  probes;
    uint16_t gap;         /* CPU cycles between SMISR polls */
    uint32_t probe_wait;  /* CPU cycles from the last enable to the first probe */
};

struct result {
    uint32_t start[NCH];
    uint32_t done[NCH];
    uint32_t flags;       /* error flags from every channel's CSR, bit 31 timeout */
    uint32_t polls;
    uint32_t probe_end;
    uint16_t lat[MAX_PROBES];
};

struct ctl {
    uint32_t magic;
    uint32_t go;
    uint32_t done;
    uint32_t njobs;
    int32_t  err;
    uint32_t selftest;
    uint32_t cpu_hz, sys_hz, hclk_hz, pclk2_hz;
    uint32_t idcode;
};

volatile struct ctl ctl;
struct job jobs[MAX_JOBS];
struct result res[MAX_JOBS];
static uint32_t buf[NCH][BUF_WORDS] __attribute__((section(".dma"), aligned(32)));
static uint32_t scratch[BUF_WORDS] __attribute__((section(".dma"), aligned(32)));

/* all on APB2 */
static volatile uint32_t *const apb[] = {
    &SAI1_Block_A->DR,  /* SAI TX in the BSP */
    &SAI1_Block_B->DR,  /* SAI RX in the BSP */
    &SAI2_Block_A->DR,
    &SAI2_Block_B->DR,
    &TIM15->CCR1,
    &TIM16->CCR1,
    &TIM17->CCR1,
    &TIM9->CCR1,
};

#define CH(c)  ((DMA_Channel_TypeDef *)((uint32_t)GPDMA1_Channel0 + 0x80u * (c)))
#define ERRS   (DMA_CSR_DTEF | DMA_CSR_ULEF | DMA_CSR_USEF | DMA_CSR_TOF)
#define FLAGS  (DMA_CFCR_TCF | DMA_CFCR_HTF | DMA_CFCR_DTEF | DMA_CFCR_ULEF | DMA_CFCR_USEF \
                | DMA_CFCR_SUSPF | DMA_CFCR_TOF)
/* only so the flags show up in SMISR, the NVIC lines stay off */
#define IRQS   (DMA_CCR_TCIE | DMA_CCR_DTEIE | DMA_CCR_ULEIE | DMA_CCR_USEIE | DMA_CCR_TOIE)

/* AHBSRAM1 and 2 back to back, 32 KB: four 8 KB buffers, channels c and c+4
   share one. Nobody checks what lands in them during a timed run. */
#define AHB_BUF(c) (SRAM1_AHB_BASE_S + 0x2000u * ((c) & 3u))

int clock_init(void);

void SysTick_Handler(void)
{
    HAL_IncTick();
}

static inline uint32_t now(void)
{
    return DWT->CYCCNT;
}

static inline void wait_until(uint32_t t)
{
    while ((int32_t)(now() - t) < 0)
        ;
}

static void stop(int c)
{
    DMA_Channel_TypeDef *ch = CH(c);

    if (ch->CCR & DMA_CCR_EN) {
        uint32_t t = now() + 600000u;
        ch->CCR |= DMA_CCR_SUSP;
        while (!(ch->CSR & DMA_CSR_SUSPF) && (int32_t)(now() - t) < 0)
            ;
    }
    ch->CCR = DMA_CCR_RESET;
    ch->CFCR = FLAGS;
}

static uint32_t addr(int e, int c)
{
    if (e < MEM)
        return (uint32_t)apb[e];
    if (e == MEM)
        return (uint32_t)buf[c];
    if (e == SCRATCH)
        return (uint32_t)scratch;
    return AHB_BUF(c);
}

static void arm(int c, const struct chan *s)
{
    DMA_Channel_TypeDef *ch = CH(c);
    uint32_t bl = s->burst - 1u;
    uint32_t ctr1 = (2u << DMA_CTR1_SDW_LOG2_Pos) | (2u << DMA_CTR1_DDW_LOG2_Pos)
                  | (bl << DMA_CTR1_SBL_1_Pos) | (bl << DMA_CTR1_DBL_1_Pos)
                  | ((s->ports & 1u) << DMA_CTR1_SAP_Pos) | ((s->ports >> 1 & 1u) << DMA_CTR1_DAP_Pos)
                  | DMA_CTR1_SSEC | DMA_CTR1_DSEC;

    if (s->src >= MEM)
        ctr1 |= DMA_CTR1_SINC;
    if (s->dst >= MEM)
        ctr1 |= DMA_CTR1_DINC;
    ch->CFCR = FLAGS;
    ch->CTR1 = ctr1;
    ch->CTR2 = DMA_CTR2_SWREQ;
    ch->CBR1 = s->words * 4u;
    ch->CSAR = addr(s->src, c);
    ch->CDAR = addr(s->dst, c);
    ch->CLLR = 0;
    ch->CCR = IRQS;
}

static void run(const struct job *j, struct result *r)
{
    uint8_t order[NCH];
    uint32_t mask = 0, n = 0, p = j->probe;

    memset(r, 0, sizeof *r);
    for (int c = 0; c < NCH; c++) {
        stop(c);
        if (!j->ch[c].words)
            continue;
        arm(c, &j->ch[c]);
        mask |= 1u << c;
        if (c == p)
            continue;
        /* keep the enables in time order */
        uint32_t k = n++;
        while (k && j->ch[order[k - 1]].delay > j->ch[c].delay) {
            order[k] = order[k - 1];
            k--;
        }
        order[k] = c;
    }
    __DSB();

    uint32_t t0 = now() + 300;
    for (uint32_t k = 0; k < n; k++) {
        int c = order[k];
        wait_until(t0 + j->ch[c].delay);
        CH(c)->CCR = IRQS | DMA_CCR_EN;
        r->start[c] = now() - t0;
    }

    if (p < NCH) {
        DMA_Channel_TypeDef *ch = CH(p);
        wait_until(now() + j->probe_wait);
        for (uint32_t i = 0; i < j->probes && i < MAX_PROBES; i++) {
            if (i)
                arm(p, &j->ch[p]);
            __DSB();
            uint32_t s = now();
            ch->CCR = IRQS | DMA_CCR_EN;
            while (!(ch->CSR & (DMA_CSR_TCF | ERRS)) && now() - s < TIMEOUT)
                ;
            uint32_t e = now() - s;
            r->lat[i] = e > 0xffff ? 0xffff : e;
            r->flags |= ch->CSR & ERRS;
        }
        r->probe_end = now() - t0;
        mask &= ~(1u << p);
    }

    uint32_t seen = 0, polls = 0;
    while (seen != mask) {
        uint32_t m = GPDMA1->SMISR & mask & ~seen;
        uint32_t t = now();
        polls++;
        for (; m; m &= m - 1) {
            int c = __builtin_ctz(m);
            r->done[c] = t - t0;
            seen |= 1u << c;
        }
        if (t - t0 > TIMEOUT) {
            r->flags |= F_TIMEOUT;
            break;
        }
        if (j->gap)
            wait_until(t + j->gap);
    }
    r->polls = polls;
    for (int c = 0; c < NCH; c++)
        if (j->ch[c].words)
            r->flags |= CH(c)->CSR & ERRS;
}

/* One channel, one block, nothing else going on. */
static uint32_t once(int src, int dst, int burst, int ports, int words)
{
    static struct job j;
    static struct result r;

    memset(&j, 0, sizeof j);
    j.probe = 0xff;
    j.ch[0] = (struct chan){ src, dst, burst, ports, words, 0 };
    run(&j, &r);
    return r.flags;
}

/* Before anything gets timed: every port pair copies memory correctly, and
   the APB registers really are what the channels read and write. Each bit
   set in the result is a check that failed. */
static uint32_t selftest(void)
{
    uint32_t bad = 0;

    for (int ports = 0; ports < 4; ports++) {
        for (int i = 0; i < 256; i++) {
            buf[0][i] = 0x5a000000u + i * 0x10001u + ports;
            scratch[i] = 0;
        }
        if (once(MEM, SCRATCH, 4, ports, 256) || memcmp(buf[0], scratch, 256 * 4))
            bad |= 1u << ports;
    }
    for (int ports = 0; ports < 4; ports++) {
        uint32_t *ahb = (uint32_t *)AHB_BUF(0);
        for (int i = 0; i < 256; i++) {
            ahb[i] = 0xa5000000u + i * 0x10001u + ports;
            scratch[i] = 0;
        }
        if (once(AHB, SCRATCH, 4, ports, 256) || memcmp(ahb, scratch, 256 * 4))
            bad |= 1u << (4 + ports);
    }

    /* a timer register as the sink keeps the last word written... */
    for (int ports = 0; ports < 4; ports++) {
        TIM15->CCR1 = 0;
        for (int i = 0; i < 16; i++)
            buf[0][i] = 0x100 + 16 * ports + i;
        if (once(MEM, 4, 1, ports, 16) || TIM15->CCR1 != 0x10fu + 16 * ports)
            bad |= 1u << (8 + ports);
    }
    /* ...and as the source every word reads back its value */
    for (int ports = 0; ports < 4; ports++) {
        TIM15->CCR1 = 0x1234 + ports;
        memset(buf[0], 0, 64);
        if (once(4, MEM, 1, ports, 16))
            bad |= 1u << (12 + ports);
        for (int i = 0; i < 16; i++)
            if (buf[0][i] != 0x1234u + ports)
                bad |= 1u << (12 + ports);
    }

    /* the SAI TX fifo takes the words even with the block disabled */
    SAI1_Block_A->CR2 = SAI_xCR2_FFLUSH;
    if (once(MEM, 0, 1, 1, 16) || !(SAI1_Block_A->SR & SAI_xSR_FLVL))
        bad |= 1u << 16;
    SAI1_Block_A->CR2 = SAI_xCR2_FFLUSH;
    TIM15->CCR1 = 0;
    return bad;
}

int main(void)
{
    /* we get here from the boot ROM, not from a reset */
    __disable_irq();
    SysTick->CTRL = 0;
    for (uint32_t i = 0; i < sizeof NVIC->ICER / sizeof NVIC->ICER[0]; i++) {
        NVIC->ICER[i] = ~0u;
        NVIC->ICPR[i] = ~0u;
    }
    MPU->CTRL = 0;
    SCB_DisableDCache();
    SCB_EnableICache();
    SCB_InvalidateICache();
    __enable_irq();

    HAL_Init();
    ctl.err = clock_init();
    SysTick->CTRL = 0;
    __disable_irq();

    __HAL_RCC_AXISRAM1_MEM_CLK_ENABLE();
    __HAL_RCC_AXISRAM2_MEM_CLK_ENABLE();
    __HAL_RCC_AHBSRAM1_MEM_CLK_ENABLE();
    __HAL_RCC_AHBSRAM2_MEM_CLK_ENABLE();
    __HAL_RCC_DBGMCU_CLK_ENABLE();
    __HAL_RCC_GPDMA1_CLK_ENABLE();
    __HAL_RCC_SAI1_CLK_ENABLE();
    __HAL_RCC_SAI2_CLK_ENABLE();
    __HAL_RCC_TIM9_CLK_ENABLE();
    __HAL_RCC_TIM15_CLK_ENABLE();
    __HAL_RCC_TIM16_CLK_ENABLE();
    __HAL_RCC_TIM17_CLK_ENABLE();

    DCB->DEMCR |= DCB_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    uint32_t t = now();
    for (volatile int i = 0; i < 100; i++)
        ;
    if (!ctl.err && now() == t)
        ctl.err = -10;

    /* channels 0-7 secure and privileged, like the BSP's SAI channels */
    GPDMA1->SECCFGR |= 0xffu;
    GPDMA1->PRIVCFGR |= 0xffu;

    ctl.cpu_hz = HAL_RCC_GetCpuClockFreq();
    ctl.sys_hz = HAL_RCC_GetSysClockFreq();
    ctl.hclk_hz = HAL_RCC_GetHCLKFreq();
    ctl.pclk2_hz = HAL_RCC_GetPCLK2Freq();
    ctl.idcode = DBGMCU->IDCODE;
    ctl.selftest = selftest();
    ctl.magic = MAGIC;

    for (;;) {
        uint32_t go = ctl.go;
        if (go == ctl.done)
            continue;
        __DSB();
        __COMPILER_BARRIER();
        uint32_t n = ctl.njobs < MAX_JOBS ? ctl.njobs : MAX_JOBS;
        for (uint32_t i = 0; i < n; i++)
            run(&jobs[i], &res[i]);
        __COMPILER_BARRIER();
        __DSB();
        ctl.done = go;
    }
}
