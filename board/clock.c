#include "stm32n6xx_hal.h"

/* Same clocks as ST's DK templates: HSI 64 MHz -> PLL1 at 1200 MHz, CPU 600
   MHz on IC1, AXI 400 MHz on IC2, AHB and APB at 200 MHz. No overdrive. */
int clock_init(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};

    if (HAL_PWREx_ConfigSupply(PWR_EXTERNAL_SOURCE_SUPPLY) != HAL_OK)
        return -1;
    if (HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1) != HAL_OK)
        return -2;

    osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    osc.HSIState = RCC_HSI_ON;
    osc.HSIDiv = RCC_HSI_DIV1;
    osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    osc.PLL1.PLLState = RCC_PLL_NONE;
    osc.PLL2.PLLState = RCC_PLL_NONE;
    osc.PLL3.PLLState = RCC_PLL_NONE;
    osc.PLL4.PLLState = RCC_PLL_NONE;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK)
        return -3;

    /* PLL1 can't be changed while it feeds the CPU or the buses, which it does
       if the bench was already loaded once since the last reset */
    HAL_RCC_GetClockConfig(&clk);
    if (clk.CPUCLKSource == RCC_CPUCLKSOURCE_IC1 || clk.SYSCLKSource == RCC_SYSCLKSOURCE_IC2_IC6_IC11) {
        clk.ClockType = RCC_CLOCKTYPE_CPUCLK | RCC_CLOCKTYPE_SYSCLK;
        clk.CPUCLKSource = RCC_CPUCLKSOURCE_HSI;
        clk.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
        if (HAL_RCC_ClockConfig(&clk) != HAL_OK)
            return -4;
    }

    osc.OscillatorType = RCC_OSCILLATORTYPE_NONE;
    osc.PLL1.PLLState = RCC_PLL_ON;
    osc.PLL1.PLLSource = RCC_PLLSOURCE_HSI;
    osc.PLL1.PLLM = 4;
    osc.PLL1.PLLN = 75;
    osc.PLL1.PLLFractional = 0;
    osc.PLL1.PLLP1 = 1;
    osc.PLL1.PLLP2 = 1;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK)
        return -5;

    clk.ClockType = RCC_CLOCKTYPE_CPUCLK | RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK
                  | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2 | RCC_CLOCKTYPE_PCLK4 | RCC_CLOCKTYPE_PCLK5;
    clk.CPUCLKSource = RCC_CPUCLKSOURCE_IC1;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_IC2_IC6_IC11;
    clk.AHBCLKDivider = RCC_HCLK_DIV2;
    clk.APB1CLKDivider = RCC_APB1_DIV1;
    clk.APB2CLKDivider = RCC_APB2_DIV1;
    clk.APB4CLKDivider = RCC_APB4_DIV1;
    clk.APB5CLKDivider = RCC_APB5_DIV1;
    clk.IC1Selection.ClockSelection = RCC_ICCLKSOURCE_PLL1;
    clk.IC1Selection.ClockDivider = 2;
    clk.IC2Selection.ClockSelection = RCC_ICCLKSOURCE_PLL1;
    clk.IC2Selection.ClockDivider = 3;
    clk.IC6Selection.ClockSelection = RCC_ICCLKSOURCE_PLL1;
    clk.IC6Selection.ClockDivider = 4;
    clk.IC11Selection.ClockSelection = RCC_ICCLKSOURCE_PLL1;
    clk.IC11Selection.ClockDivider = 3;
    if (HAL_RCC_ClockConfig(&clk) != HAL_OK)
        return -6;
    return 0;
}
