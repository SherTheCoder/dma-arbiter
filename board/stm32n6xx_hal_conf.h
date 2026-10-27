/* Just enough HAL for clocks and power. */
#ifndef STM32N6XX_HAL_CONF_H
#define STM32N6XX_HAL_CONF_H

#define HAL_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED   /* the RCC driver's MCO code wants it */
#define HAL_PWR_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED

#define HSE_VALUE            48000000UL
#define HSE_STARTUP_TIMEOUT  100UL
#define LSE_VALUE            32768UL
#define LSE_STARTUP_TIMEOUT  5000UL
#define MSI_VALUE            4000000UL
#define HSI_VALUE            64000000UL
#define LSI_VALUE            32000UL
#define VDD_VALUE            3300UL
#define TICK_INT_PRIORITY    15U
#define USE_RTOS             0U

#include "stm32n6xx_hal_rcc.h"
#include "stm32n6xx_hal_cortex.h"
#include "stm32n6xx_hal_gpio.h"
#include "stm32n6xx_hal_pwr.h"

#define assert_param(expr) ((void)0U)

#endif
