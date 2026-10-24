// Bench probe pod firmware. Protocol: docs/CONTRACTS.md §2–3 (source of truth: issue #2).
#include <avr/interrupt.h>
#include <avr/io.h>

#include "config.h"
#include "timer.h"
#include "uart.h"

int main(void) {
    DDRB |= (1 << PB5);     // D13 on-board LED: heartbeat
    timer_init();
    uart_init();
    sei();

    // Leading \n ends any line a reset cut off, so it can't swallow the hello.
    uart_puts("\n{\"hello\":\"bench-pod\",\"fw\":\"" FW_VERSION "\",\"probes\":[\"Y\",\"B\",\"G\",\"W\"]}\n");

    uint32_t next = timer_millis();
    for (;;) {
        if ((int32_t)(timer_millis() - next) >= 0) {
            next += 500;
            PORTB ^= (1 << PB5);
        }
    }
}
