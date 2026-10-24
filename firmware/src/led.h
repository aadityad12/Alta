// Status RGB LED: R = D9 (PB1), G = D10 (PB2), B = D11 (PB3), each through 220 Ω.
#ifndef LED_H
#define LED_H
#include <stdint.h>

void led_init(void);
void led_rgb(uint8_t r, uint8_t g, uint8_t b);
void led_self_test(void);   // red → green → blue, 150 ms each, then off

#endif
