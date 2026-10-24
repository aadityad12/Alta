#include "adc.h"

#include <avr/interrupt.h>
#include <avr/io.h>
#include <util/atomic.h>

#define CH_BANDGAP   4
#define MUX_BANDGAP  0x0E   // MUX3..0 = 1110: internal 1.1 V
#define BG_SETTLE    10     // throw-away conversions after switching to the bandgap (~1 ms)
#define BG_KEEP      4      // averaged bandgap conversions

static volatile stat_t acc[4];
static volatile uint8_t vcc_req, vcc_ready;
static volatile uint16_t vcc_raw;
static uint16_t first_vcc_raw;
static uint8_t ch, discard, bg_n;
static uint16_t bg_sum;

static void select_channel(uint8_t c) {
    ADMUX = (1 << REFS0) | (c == CH_BANDGAP ? MUX_BANDGAP : c);   // reference = AVcc
}

static uint16_t read_blocking(void) {
    ADCSRA |= (1 << ADSC);
    while (ADCSRA & (1 << ADSC)) {
    }
    return ADC;
}

void adc_init(void) {
    DIDR0 = 0x0F;   // A0..A3 are analog only: disable their digital input buffers
    ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0);   // 16 MHz / 128 = 125 kHz
    select_channel(CH_BANDGAP);
    uint16_t sum = 0;
    for (uint8_t i = 0; i < BG_SETTLE + BG_KEEP; i++) {
        uint16_t raw = read_blocking();
        if (i >= BG_SETTLE) sum += raw;
    }
    first_vcc_raw = (uint16_t)((sum + BG_KEEP / 2) / BG_KEEP);
    for (uint8_t i = 0; i < 4; i++) stat_reset((stat_t *)&acc[i]);
}

uint16_t adc_first_vcc_raw(void) { return first_vcc_raw; }

void adc_start(void) {
    ch = 0;
    discard = 1;
    select_channel(0);
    ADCSRA |= (1 << ADIE) | (1 << ADSC);
}

// One conversion done (~104 µs each). Pick the next channel and start the next conversion.
ISR(ADC_vect) {
    uint16_t raw = ADC;
    if (discard) {
        discard--;
    } else if (ch < CH_BANDGAP) {
        stat_add((stat_t *)&acc[ch], raw);
        ch = (ch + 1) & 3;
        if (ch == 0 && vcc_req) {
            ch = CH_BANDGAP;
            discard = BG_SETTLE;
            bg_sum = 0;
            bg_n = 0;
        } else {
            discard = 1;   // the sample-and-hold needs one conversion to settle after a mux switch
        }
        select_channel(ch);
    } else {
        bg_sum += raw;
        if (++bg_n == BG_KEEP) {
            vcc_raw = (uint16_t)((bg_sum + BG_KEEP / 2) / BG_KEEP);
            vcc_ready = 1;
            vcc_req = 0;
            ch = 0;
            discard = 1;
            select_channel(0);
        }
    }
    ADCSRA |= (1 << ADSC);
}

void adc_snapshot(stat_t out[4]) {
    ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
        for (uint8_t i = 0; i < 4; i++) {
            out[i] = *(stat_t *)&acc[i];
            stat_reset((stat_t *)&acc[i]);
        }
    }
}

void adc_request_vcc(void) { vcc_req = 1; }

uint8_t adc_take_vcc_raw(uint16_t *raw) {
    uint8_t ready = 0;
    ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
        if (vcc_ready) {
            *raw = vcc_raw;
            vcc_ready = 0;
            ready = 1;
        }
    }
    return ready;
}
