/*
 * assignment.h
 *
 *  Created on: 27. 9. 2020
 *      Author: Stancoj
 */

#ifndef ASSIGNMENT_H_
#define ASSIGNMENT_H_

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

/* LED and button macros */
#define LED_ON					(*GPIOA_BSRR_REG = (1UL << 4))/* Add LED_ON implementation here. */
#define LED_OFF					(*GPIOA_BRR_REG = (1UL << 4))/* Add LED_OFF implementation here. */

#define BUTTON_GET_STATE		(*GPIOA_IDR_REG & (1UL << 3))/* Add BUTTON_GET_STATE implementation here. */


#endif /* ASSIGNMENT_H_ */
