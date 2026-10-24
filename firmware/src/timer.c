#include "timer.h"

#include <avr/interrupt.h>
#include <avr/io.h>
#include <util/atomic.h>

static volatile uint32_t ms;

__attribute__((weak)) void timer_tick_hook(uint32_t now_ms) { (void)now_ms; }

void timer_init(void) {
    // CTC mode, 16 MHz / 64 = 250 kHz, 250 counts = 1 ms.
    TCCR0A = (1 << WGM01);
    TCCR0B = (1 << CS01) | (1 << CS00);
    OCR0A = 249;
    TIMSK0 = (1 << OCIE0A);
}

ISR(TIMER0_COMPA_vect) {
    ms++;
    timer_tick_hook(ms);
}

uint32_t timer_millis(void) {
    uint32_t now;
    ATOMIC_BLOCK(ATOMIC_RESTORESTATE) { now = ms; }
    return now;
}

void timer_delay_ms(uint16_t d) {
    uint32_t start = timer_millis();
    while (timer_millis() - start < d) {
    }
}
