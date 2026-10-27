# Bench firmware for the STM32N6570-DK. Needs arm-none-eabi-gcc and the
# STM32CubeN6 package, which is only used for the startup file, SystemInit
# and the RCC/PWR HAL (plus GPIO, which the RCC driver needs). The GPDMA and
# DWT code in bench.c is register level.

CUBE ?= $(HOME)/STM32Cube/Repository/STM32Cube_FW_N6_V1.3.0
CC = arm-none-eabi-gcc
OUT = build

DEV = $(CUBE)/Drivers/CMSIS/Device/ST/STM32N6xx
HAL = $(CUBE)/Drivers/STM32N6xx_HAL_Driver/Src

SRC = bench.c clock.c \
      $(DEV)/Source/Templates/system_stm32n6xx_fsbl.c \
      $(HAL)/stm32n6xx_hal.c \
      $(HAL)/stm32n6xx_hal_cortex.c \
      $(HAL)/stm32n6xx_hal_gpio.c \
      $(HAL)/stm32n6xx_hal_pwr.c \
      $(HAL)/stm32n6xx_hal_pwr_ex.c \
      $(HAL)/stm32n6xx_hal_rcc.c \
      $(HAL)/stm32n6xx_hal_rcc_ex.c
ASM = $(DEV)/Source/Templates/gcc/startup_stm32n657xx_fsbl.s

CPU = -mcpu=cortex-m55 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard
CFLAGS = $(CPU) -mcmse -O2 -g -Wall -ffunction-sections -fdata-sections \
         -DSTM32N657xx -DUSE_HAL_DRIVER \
         -I. -I$(DEV)/Include -I$(CUBE)/Drivers/STM32N6xx_HAL_Driver/Inc -I$(CUBE)/Drivers/CMSIS/Include
LDFLAGS = $(CPU) -T bench.ld -Wl,--gc-sections -Wl,--no-warn-rwx-segments \
          --specs=nano.specs --specs=nosys.specs -Wl,-Map=$(OUT)/bench.map

$(OUT)/bench.elf: $(SRC) $(ASM) bench.ld stm32n6xx_hal_conf.h | $(OUT)
	$(CC) $(CFLAGS) $(SRC) $(ASM) $(LDFLAGS) -o $@
	arm-none-eabi-size $@

$(OUT):
	mkdir -p $@

clean:
	rm -rf $(OUT)

.PHONY: clean
