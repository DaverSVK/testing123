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
#include "assignment.h"

/**
  * @brief  Detects an edge (button press) on the input pin.
  *         Every call processes one sample of the input pin. A state different from the
  *         last stable one has to be read "samples"-times in a row to be reported as an edge.
  *         A single deviating sample resets the counter, so the sequence 0,1,1,1,0,1
  *         is evaluated as "no edge" while 0,1,1,1,1,1 (samples = 5) is a rising edge.
  * @param  pin_state  current state of the input pin ("1" or "0")
  * @param  samples    number of identical samples in a row required to accept the edge
  * @retval NONE / RISE / FALL
  */
EDGE_TYPE edgeDetect(uint8_t pin_state, uint8_t samples)
{
	/* State has to survive between the calls - one call = one sample. */
	static uint8_t stable_state = 0U;
	static uint8_t match_count  = 0U;
	static uint8_t initialized  = 0U;

	EDGE_TYPE edge = NONE;

	/* Accept any non-zero value as logical "1". */
	uint8_t current_state = (pin_state != 0U) ? 1U : 0U;

	/* At least one sample is always needed. */
	if(samples == 0U)
	{
		samples = 1U;
	}

	/* First call only latches the current level - no edge can be detected yet. */
	if(initialized == 0U)
	{
		initialized  = 1U;
		stable_state = current_state;
		return NONE;
	}

	if(current_state == stable_state)
	{
		/* Nothing new on the input - the counter of the new state starts over. */
		match_count = 0U;
	}
	else
	{
		match_count++;

		if(match_count >= samples)
		{
			/* New state was read "samples"-times in a row - the edge is accepted. */
			stable_state = current_state;
			match_count  = 0U;
			edge = (current_state != 0U) ? RISE : FALL;
		}
	}

	return edge;
}

int main(void)
{
  /*
   *  DO NOT WRITE TO THE WHOLE REGISTER!!!
   *  Write to the bits, that are meant for change.
   */
   
  //Systick init
  LL_Init1msTick(8000000);
  LL_SYSTICK_SetClkSource(LL_SYSTICK_CLKSOURCE_HCLK);
  LL_SetSystemCoreClock(8000000);	

  /*
   * TASK - configure MCU peripherals so that button state can be read and LED can be driven.
   * Button (input signal) must be connected to the GPIO port A and its pin 3.
   * LED (output signal) must be connected to the GPIO port A and its pin 4.
   *
   * In header file "assignment.h" define macros for MCU registers access, the "EDGE_TYPE"
   * enum and the "edgeDetect" function prototype.
   * Code in this file must use these macros for the peripherals setup.
   * The LED changes its state only when the chosen edge type is detected on the input pin.
   */


  /* Enable clock for GPIO port A*/

	//type your code for GPIOA clock enable here:
	/* RCC_AHBENR bit 17 (IOPAEN) - enable clock for GPIOA peripheral */
	*RCC_AHBENR_REG |= (1UL << 17);


  /* GPIOA pin 3 and 4 setup */

	//type your code for GPIOA pins setup here:

	/* PA3 - button input: MODER bits [7:6] = 00 (input mode) */
	*GPIOA_MODER_REG &= ~(0x3UL << 6);
	/* PA3 - pull-up resistor: PUPDR bits [7:6] = 01 */
	*GPIOA_PUPDR_REG &= ~(0x3UL << 6);
	*GPIOA_PUPDR_REG |=  (0x1UL << 6);

	/* PA4 - LED output: MODER bits [9:8] = 01 (general purpose output) */
	*GPIOA_MODER_REG &= ~(0x3UL << 8);
	*GPIOA_MODER_REG |=  (0x1UL << 8);
	/* PA4 - push-pull output: OTYPER bit 4 = 0 */
	*GPIOA_OTYPER_REG &= ~(1UL << 4);
	/* PA4 - low speed: OSPEEDR bits [9:8] = 00 */
	*GPIOA_OSPEEDER_REG &= ~(0x3UL << 8);
	/* PA4 - no pull-up/pull-down: PUPDR bits [9:8] = 00 */
	*GPIOA_PUPDR_REG &= ~(0x3UL << 8);


  /* LED is off after the start-up */
  uint8_t led_state = 0U;
  LED_OFF;

  while (1)
  {
	  /* One sample of the input pin per loop pass -
	   * SAMPLE_PERIOD_MS * DEBOUNCE_SAMPLES = DEBOUNCE_MS (100 ms) debounce window. */
	  LL_mDelay(SAMPLE_PERIOD_MS);

	  /* LED changes its state only on the rising edge of the input signal. */
	  if(edgeDetect(BUTTON_GET_STATE, DEBOUNCE_SAMPLES) == RISE)
	  {
		  led_state = !led_state;

		  if(led_state)
		  {
			  LED_ON;
		  }
		  else
		  {
			  LED_OFF;
		  }
	  }
  }

}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */

  /* USER CODE END Error_Handler_Debug */
}

#ifdef  USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(char *file, uint32_t line)
{ 
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     tex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */

/************************ (C) COPYRIGHT STMicroelectronics *****END OF FILE****/
