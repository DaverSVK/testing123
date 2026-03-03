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

/* General purpose input output port A macros */
//GPIOA peripheral base address
#define	GPIOA_BASE_ADDR			0x48000000
//MODER register
#define	GPIOA_MODER_REG			((volatile uint32_t *)(GPIOA_BASE_ADDR + 0x00))
//OTYPER register
#define	GPIOA_OTYPER_REG		((volatile uint32_t *)(GPIOA_BASE_ADDR + 0x04))
//OSPEEDER register
#define GPIOA_OSPEEDER_REG		((volatile uint32_t *)(GPIOA_BASE_ADDR + 0x08))
//PUPDR register
#define GPIOA_PUPDR_REG			((volatile uint32_t *)(GPIOA_BASE_ADDR + 0x0C))
//IDR register
#define GPIOA_IDR_REG			((volatile uint32_t *)(GPIOA_BASE_ADDR + 0x10))
//ODR register
#define GPIOA_ODR_REG			((volatile uint32_t *)(GPIOA_BASE_ADDR + 0x14))
//BSRR register
#define GPIOA_BSRR_REG			((volatile uint32_t *)(GPIOA_BASE_ADDR + 0x18))
//BRR register
#define GPIOA_BRR_REG			((volatile uint32_t *)(GPIOA_BASE_ADDR + 0x28))

/*Reset clock control register macros */
//RCC base address
#define	RCC_BASE_ADDR			0x40021000
//AHBEN register
#define	RCC_AHBENR_REG			((volatile uint32_t *)(RCC_BASE_ADDR + 0x14))

/* LED and button macros */
#define LED_ON					(*GPIOA_ODR_REG |=  (1u << 4))
#define LED_OFF					(*GPIOA_ODR_REG &= ~(1u << 4))

#define BUTTON_GET_STATE		(*GPIOA_IDR_REG &   (1u << 3))


#endif /* ASSIGNMENT_H_ */
