// 1 ms system tick on Timer0. Also drives the button debounce.
#ifndef TIMER_H
#define TIMER_H
#include <stdint.h>

void timer_init(void);
uint32_t timer_millis(void);
void timer_delay_ms(uint16_t ms);

// Called from the 1 ms tick ISR (weak no-op until a module provides it).
void timer_tick_hook(uint32_t now_ms);

#endif
