#include "led.h"

#include <avr/io.h>

#include "config.h"
#include "timer.h"

#define LED_MASK ((1 << PB1) | (1 << PB2) | (1 << PB3))

void led_init(void) {
    DDRB |= LED_MASK;
    led_rgb(0, 0, 0);
}

void led_rgb(uint8_t r, uint8_t g, uint8_t b) {
    uint8_t on = (r ? (1 << PB1) : 0) | (g ? (1 << PB2) : 0) | (b ? (1 << PB3) : 0);
#if LED_COMMON_ANODE
    on = (uint8_t)(~on & LED_MASK);   // common-anode: a pin LOW lights its color
#endif
    PORTB = (uint8_t)((PORTB & ~LED_MASK) | on);
}

void led_self_test(void) {
    led_rgb(1, 0, 0);
    timer_delay_ms(150);
    led_rgb(0, 1, 0);
    timer_delay_ms(150);
    led_rgb(0, 0, 1);
    timer_delay_ms(150);
    led_rgb(0, 0, 0);
}
