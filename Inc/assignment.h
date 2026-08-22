/*
 * assignment.h
 *
 *  Created on: 27. 9. 2020
 *      Author: Stancoj
 */

#ifndef ASSIGNMENT_H_
#define ASSIGNMENT_H_

#include <stdint.h>

/**
 * 		This header file provides macros to the MCU's registers required for this assignment.
 * 		Your task is to provide their actual implementation so you can use them in application in "main.c"
 * 		and make your "LED blink" application code readable and great again!
 */

/* Register access macro */
#define REG32(addr) ((volatile uint32_t *)(addr))

/* General purpose input output port A macros */
//GPIOA peripheral base address
#define	GPIOA_BASE_ADDR			0x48000000UL/* Add GPIO A peripheral base address here. */
//MODER register
#define	GPIOA_MODER_REG			REG32(GPIOA_BASE_ADDR + 0x00UL)/* Add moder register address here. */
//OTYPER register
#define	GPIOA_OTYPER_REG		REG32(GPIOA_BASE_ADDR + 0x04UL)/* Add otyper register address here. */
//OSPEEDER register
#define GPIOA_OSPEEDER_REG		REG32(GPIOA_BASE_ADDR + 0x08UL)/* Add ospeeder register address here. */
//PUPDR register
#define GPIOA_PUPDR_REG			REG32(GPIOA_BASE_ADDR + 0x0CUL)/* Add pupdr register address here. */
//IDR register
#define GPIOA_IDR_REG			REG32(GPIOA_BASE_ADDR + 0x10UL)/* Add idr register address here. */
//ODR register
#define GPIOA_ODR_REG			REG32(GPIOA_BASE_ADDR + 0x14UL)/* Add odr register address here. */
//BSRR register
#define GPIOA_BSRR_REG			REG32(GPIOA_BASE_ADDR + 0x18UL)/* Add bsrr register address here. */
//BRR register
#define GPIOA_BRR_REG			REG32(GPIOA_BASE_ADDR + 0x28UL)/* Add brr register address here. */

/*Reset clock control register macros */
//RCC base address
#define	RCC_BASE_ADDR			0x40021000UL/* Add rcc register address here. */
//AHBEN register
#define	RCC_AHBENR_REG			REG32(RCC_BASE_ADDR + 0x14UL)/* Add ahben register address here. */
//APB2EN register - clock for the SYSCFG peripheral
#define	RCC_APB2ENR_REG			REG32(RCC_BASE_ADDR + 0x18UL)/* Add apb2en register address here. */

/* External interrupt/event controller (EXTI) macros */
//EXTI peripheral base address
#define	EXTI_BASE_ADDR			0x40010400UL/* Add EXTI peripheral base address here. */
//IMR register - interrupt mask
#define EXTI_IMR_REG			REG32(EXTI_BASE_ADDR + 0x00UL)/* Add imr register address here. */
//RTSR register - rising edge trigger selection
#define EXTI_RTSR_REG			REG32(EXTI_BASE_ADDR + 0x08UL)/* Add rtsr register address here. */
//FTSR register - falling edge trigger selection
#define EXTI_FTSR_REG			REG32(EXTI_BASE_ADDR + 0x0CUL)/* Add ftsr register address here. */
//PR register - pending request
#define EXTI_PR_REG				REG32(EXTI_BASE_ADDR + 0x14UL)/* Add pr register address here. */

/* System configuration controller (SYSCFG) macros */
//SYSCFG peripheral base address
#define SYSCFG_BASE_ADDR		0x40010000UL/* Add SYSCFG peripheral base address here. */
//EXTICR1 register - selects the source GPIO port for EXTI lines 0..3
#define SYSCFG_EXTICR1_REG		REG32(SYSCFG_BASE_ADDR + 0x08UL)/* Add exticr1 register address here. */

/* Nested vectored interrupt controller (NVIC) macros */
//ISER0 register - interrupt set-enable, Cortex-M4 system control space
#define NVIC_ISER0_REG			REG32(0xE000E100UL)/* Add iser0 register address here. */

/* LED and button macros */
#define LED_ON					(*GPIOA_BSRR_REG = (1UL << 4))/* Add LED_ON implementation here. */
#define LED_OFF					(*GPIOA_BRR_REG = (1UL << 4))/* Add LED_OFF implementation here. */

/* Returns "1" when the input pin PA3 is high, "0" otherwise. */
#define BUTTON_GET_STATE		((*GPIOA_IDR_REG & (1UL << 3)) ? 1U : 0U)/* Add BUTTON_GET_STATE implementation here. */

/* Changes the LED state: On -> Off, Off -> On. Reads the output register ODR,
 * the input register IDR is used for the button only. */
#define LED_TOGGLE				((*GPIOA_ODR_REG & (1UL << 4)) ? LED_OFF : LED_ON)/* Add LED_TOGGLE implementation here. */


/* Debounce configuration - sampling period x number of samples = debounce window */
//Period of one input pin sample [ms]
#define SAMPLE_PERIOD_MS		1U
//How many identical samples in a row are required to accept an edge
#define DEBOUNCE_SAMPLES		100U
//Resulting debounce window [ms] - 1 ms * 100 samples = 100 ms
#define DEBOUNCE_MS				(SAMPLE_PERIOD_MS * DEBOUNCE_SAMPLES)


/* External interrupt of the button - PA3 is connected to the EXTI line 3 */
//EXTI line used by the button
#define BUTTON_EXTI_LINE		3U
//Position of the EXTI3 interrupt in the NVIC (EXTI3_IRQn = 9)
#define BUTTON_EXTI_IRQ_NUM		9U

//Is there an unhandled request on the button's EXTI line?
#define EXTI_LINE3_IS_PENDING		(*EXTI_PR_REG & (1UL << BUTTON_EXTI_LINE))
//Clear the request - the PR register bit is cleared by writing "1" to it
#define EXTI_LINE3_CLEAR_PENDING	(*EXTI_PR_REG = (1UL << BUTTON_EXTI_LINE))


/* Type of the detected edge on the input pin */
typedef enum
{
	NONE = 0,	/* no edge detected */
	RISE = 1,	/* rising edge detected  (0 -> 1) */
	FALL = 2	/* falling edge detected (1 -> 0) */
} EDGE_TYPE;


/**
 * @brief  Detects an edge on the input pin.
 *         One call of this function processes exactly one sample of the input pin.
 *         A new state must be read "samples"-times in a row to be reported as an edge.
 * @param  pin_state  current state of the input pin ("1" or "0")
 * @param  samples    number of identical samples in a row required to accept the edge
 * @retval NONE / RISE / FALL
 */
EDGE_TYPE edgeDetect(uint8_t pin_state, uint8_t samples);


#endif /* ASSIGNMENT_H_ */
