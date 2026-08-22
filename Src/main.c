/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * <h2><center>&copy; Copyright (c) 2019 STMicroelectronics.
  * All rights reserved.</center></h2>
  *
  * This software component is licensed by ST under BSD 3-Clause license,
  * the "License"; You may not use this file except in compliance with the
  * License. You may obtain a copy of the License at:
  *                        opensource.org/licenses/BSD-3-Clause
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "dma.h"
#include "usart.h"
#include "gpio.h"
#include <stdio.h>

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);


/* Function processing DMA Rx data. Counts how many capital and small letters are in sentence.
 * Result is supposed to be stored in global variable of type "letter_count_" that is defined in "main.h"
 *
 * @param1 - received sign
 */
void proccesDmaData(uint8_t sign);


/* Space for your global variables. */

	/* A set of characters is discarded when '$' does not arrive within 35
	 * characters of the '#' - the closing '$' itself counts as one of them. */
	#define FRAME_WINDOW_CHARS	35U
	#define FRAME_PAYLOAD_MAX	(FRAME_WINDOW_CHARS - 1U)

	/* Period of the buffer state message - 0.5 Hz. */
	#define REPORT_PERIOD_MS	2000U

	letter_count_ letterCount;

	static char    frameBuffer[FRAME_PAYLOAD_MAX + 1U];
	static uint8_t frameLength = 0;
	static uint8_t frameOpen   = 0;
	static volatile uint8_t frameReady = 0;

	static char txBuffer[96];


int main(void)
{
  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  LL_APB2_GRP1_EnableClock(LL_APB2_GRP1_PERIPH_SYSCFG);
  LL_APB1_GRP1_EnableClock(LL_APB1_GRP1_PERIPH_PWR);
  NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_4);

  /* Configure the system clock */
  SystemClock_Config();
  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_USART2_UART_Init();

  /* Space for your local variables, callback registration ...*/

  	  uint32_t msCounter = 0;
  	  uint16_t occupied;
  	  float    load;
  	  int      length;

  	  USART2_RegisterCallback(proccesDmaData);

  while (1)
  {
	  /* Periodic transmission of information about DMA Rx buffer state.
	   * Transmission frequency - 0.5Hz.
	   * Message format - "Buffer capacity: %d bytes, occupied memory: %d bytes, load [in %]: %f%"
	   */

	  /* Valid text string information transmission.
	   * Transmission frequency - when new valid string is received.
	   * Message format - "Valid string: %s, lower-case: %d, upper-case: %d"
	   */

	  /* 1 ms time base - the SysTick COUNTFLAG clears itself when it is read. */
	  if(LL_SYSTICK_IsActiveCounterFlag())
	  {
		  msCounter++;
	  }

	  if(frameReady != 0)
	  {
		  frameReady = 0;

		  length = sprintf(txBuffer,
		                   "Valid string: %s, lower-case: %d, upper-case: %d\r\n",
		                   frameBuffer,
		                   letterCount.small_letter,
		                   letterCount.capital_letter);

		  while(LL_DMA_IsEnabledChannel(DMA1, LL_DMA_CHANNEL_7) != 0);
		  USART2_PutBuffer((uint8_t*)txBuffer, (uint8_t)length);
	  }

	  if(msCounter >= REPORT_PERIOD_MS)
	  {
		  msCounter = 0;

		  occupied = (uint16_t)(DMA_USART2_BUFFER_SIZE
		                        - LL_DMA_GetDataLength(DMA1, LL_DMA_CHANNEL_6));
		  load = (100.0f * (float)occupied) / (float)DMA_USART2_BUFFER_SIZE;

		  length = sprintf(txBuffer,
		                   "Buffer capacity: %d bytes, occupied memory: %d bytes, load [in %%]: %.1f%%\r\n",
		                   (int)DMA_USART2_BUFFER_SIZE,
		                   (int)occupied,
		                   load);

		  while(LL_DMA_IsEnabledChannel(DMA1, LL_DMA_CHANNEL_7) != 0);
		  USART2_PutBuffer((uint8_t*)txBuffer, (uint8_t)length);
	  }
  }
  /* USER CODE END 3 */
}


void SystemClock_Config(void)
{
  LL_FLASH_SetLatency(LL_FLASH_LATENCY_0);

  if(LL_FLASH_GetLatency() != LL_FLASH_LATENCY_0)
  {
  Error_Handler();
  }
  LL_RCC_HSI_Enable();

   /* Wait till HSI is ready */
  while(LL_RCC_HSI_IsReady() != 1)
  {

  }
  LL_RCC_HSI_SetCalibTrimming(16);
  LL_RCC_SetAHBPrescaler(LL_RCC_SYSCLK_DIV_1);
  LL_RCC_SetAPB1Prescaler(LL_RCC_APB1_DIV_1);
  LL_RCC_SetAPB2Prescaler(LL_RCC_APB1_DIV_1);
  LL_RCC_SetSysClkSource(LL_RCC_SYS_CLKSOURCE_HSI);

   /* Wait till System clock is ready */
  while(LL_RCC_GetSysClkSource() != LL_RCC_SYS_CLKSOURCE_STATUS_HSI)
  {

  }
  LL_Init1msTick(8000000);
  LL_SYSTICK_SetClkSource(LL_SYSTICK_CLKSOURCE_HCLK);
  LL_SetSystemCoreClock(8000000);
}

/*
 * Implementation of function processing data received via USART.
 */
void proccesDmaData(uint8_t sign)
{
	/* Process received data */

	/* '#' always starts a new set of characters, even in the middle of one. */
	if(sign == '#')
	{
		frameOpen   = 1;
		frameLength = 0;
		letterCount.small_letter   = 0;
		letterCount.capital_letter = 0;
		return;
	}

	/* Everything received before the start character is ignored. */
	if(frameOpen == 0)
	{
		return;
	}

	if(sign == '$')
	{
		frameBuffer[frameLength] = '\0';
		frameOpen  = 0;
		frameReady = 1;
		return;
	}

	/* No '$' within 35 characters of the '#' - throw the data away and wait
	 * for a new start character. */
	if(frameLength >= FRAME_PAYLOAD_MAX)
	{
		frameOpen   = 0;
		frameLength = 0;
		return;
	}

	if((sign >= 'a') && (sign <= 'z'))
	{
		letterCount.small_letter++;
	}
	else if((sign >= 'A') && (sign <= 'Z'))
	{
		letterCount.capital_letter++;
	}

	frameBuffer[frameLength++] = (char)sign;
}


void Error_Handler(void)
{

}

#ifdef  USE_FULL_ASSERT

void assert_failed(char *file, uint32_t line)
{

}

#endif

/************************ (C) COPYRIGHT STMicroelectronics *****END OF FILE****/
