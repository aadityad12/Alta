// Per-window probe statistics and ADC → millivolt maths. Pure C: also built by `make test`.
#ifndef MEASURE_H
#define MEASURE_H
#include <stdint.h>

// Raw 10-bit ADC readings seen on one channel during one 50 ms window.
typedef struct {
    uint32_t sum;
    uint16_t count, min, max;
} stat_t;

void stat_reset(stat_t *s);
void stat_add(stat_t *s, uint16_t raw);

// Supply voltage from a reading of the internal 1.1 V bandgap against AVcc.
uint16_t measure_vcc_mv(uint16_t bandgap_raw);

// Raw count → mV, relative to the measured supply (the ADC reference is AVcc).
int16_t measure_mv(uint32_t raw, uint16_t vcc_mv);

// mean / min / max of a window in mV. Returns 0 (outputs untouched) if the window is empty.
uint8_t measure_window(const stat_t *s, uint16_t vcc_mv, int16_t *mv, int16_t *lo, int16_t *hi);

#endif
