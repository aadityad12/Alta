// Bench probe pod firmware. Protocol: docs/CONTRACTS.md §2–3 (source of truth: issue #2).
//
// Every 50 ms: snapshot the ADC window stats for A0..A3, convert to mV against the measured
// supply, print one sample line. Everything slow (ADC, serial out, 1 ms tick) runs on
// interrupts, so the main loop never waits on hardware.
#include <avr/interrupt.h>
#include <avr/io.h>

#include "adc.h"
#include "button.h"
#include "config.h"
#include "led.h"
#include "measure.h"
#include "proto.h"
#include "timer.h"
#include "uart.h"

static char line[PROTO_LINE_MAX];

static void handle_command(const char *cmd) {
    switch (proto_parse_cmd(cmd)) {
        case CMD_NONE: break;
        case CMD_LED_IDLE: led_rgb(0, 0, 0); break;
        case CMD_LED_LISTEN: led_rgb(0, 1, 0); break;
        case CMD_LED_THINK: led_rgb(0, 0, 1); break;
        case CMD_LED_SPEAK: led_rgb(1, 1, 1); break;
        case CMD_LED_ERROR: led_rgb(1, 0, 0); break;
        case CMD_PING: uart_write(line, proto_pong(line)); break;
        case CMD_UNKNOWN: uart_write(line, proto_err(line)); break;
    }
}

int main(void) {
    DDRB |= (1 << PB5);     // D13 on-board LED: toggles with every sample line
    timer_init();
    uart_init();
    led_init();
    button_init();
    adc_init();
    sei();
    led_self_test();

    uint16_t vcc = measure_vcc_mv(adc_first_vcc_raw());
    uart_write(line, proto_hello(line));
    adc_start();

    int16_t mv[4] = {0}, lo[4] = {0}, hi[4] = {0};
    uint32_t seq = 0;
    uint32_t next_sample = timer_millis() + SAMPLE_MS;
    uint32_t next_vcc = timer_millis() + VCC_EVERY_MS;

    for (;;) {
        char cmd[24];
        while (uart_getline(cmd, sizeof cmd) >= 0) handle_command(cmd);

        // Button edges go out immediately, not on the 50 ms tick (#2).
        uint8_t down;
        uint32_t t;
        while (button_take_edge(&down, &t)) uart_write(line, proto_btn_evt(line, down, t));

        uint16_t raw;
        if (adc_take_vcc_raw(&raw)) vcc = measure_vcc_mv(raw);

        uint32_t now = timer_millis();
        if ((int32_t)(now - next_vcc) >= 0) {
            next_vcc += VCC_EVERY_MS;
            adc_request_vcc();
        }
        if ((int32_t)(now - next_sample) >= 0) {
            next_sample += SAMPLE_MS;
            if ((int32_t)(now - next_sample) >= 0) next_sample = now + SAMPLE_MS;   // fell behind: resync
            stat_t s[4];
            adc_snapshot(s);
            for (uint8_t i = 0; i < 4; i++) measure_window(&s[i], vcc, &mv[i], &lo[i], &hi[i]);
            uart_write(line, proto_sample(line, seq++, now, mv, lo, hi, vcc, button_held()));
            PORTB ^= (1 << PB5);
        }
    }
}
