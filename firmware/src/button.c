#include "button.h"

#include <avr/io.h>
#include <util/atomic.h>

#include "debounce.h"
#include "timer.h"

#define EDGES 4   // power of two; a human can't press 4 times between two main-loop passes

static debounce_t deb;
static volatile uint8_t held;
static volatile struct { uint8_t down; uint32_t t; } edges[EDGES];
static volatile uint8_t e_head, e_tail;

void button_init(void) {
    DDRD &= ~(1 << PD2);
    PORTD |= (1 << PD2);   // pull-up: released = high, pressed = low
}

// 1 ms tick (from the Timer0 ISR).
void timer_tick_hook(uint32_t now_ms) {
    uint8_t pressed = !(PIND & (1 << PD2));
    if (!debounce_update(&deb, pressed)) return;
    held = deb.stable;
    uint8_t next = (e_head + 1) & (EDGES - 1);
    if (next != e_tail) {
        edges[e_head].down = deb.stable;
        edges[e_head].t = now_ms;
        e_head = next;
    }
}

uint8_t button_held(void) { return held; }

uint8_t button_take_edge(uint8_t *down, uint32_t *t) {
    uint8_t got = 0;
    ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
        if (e_tail != e_head) {
            *down = edges[e_tail].down;
            *t = edges[e_tail].t;
            e_tail = (e_tail + 1) & (EDGES - 1);
            got = 1;
        }
    }
    return got;
}
