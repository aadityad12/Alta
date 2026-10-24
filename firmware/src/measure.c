#include "measure.h"

#include "config.h"

void stat_reset(stat_t *s) {
    s->sum = 0;
    s->count = 0;
    s->min = 0xFFFF;
    s->max = 0;
}

void stat_add(stat_t *s, uint16_t raw) {
    s->sum += raw;
    s->count++;
    if (raw < s->min) s->min = raw;
    if (raw > s->max) s->max = raw;
}

uint16_t measure_vcc_mv(uint16_t bandgap_raw) {
    if (!bandgap_raw) return 0;
    return (uint16_t)((BANDGAP_MV * 1023UL + bandgap_raw / 2) / bandgap_raw);
}

int16_t measure_mv(uint32_t raw, uint16_t vcc_mv) {
    return (int16_t)((raw * vcc_mv + 511) / 1023);
}

uint8_t measure_window(const stat_t *s, uint16_t vcc_mv, int16_t *mv, int16_t *lo, int16_t *hi) {
    if (!s->count) return 0;
    // mean in mV = sum·vcc / (count·1023). sum ≤ 1023·count and a window holds ~60 reads, so
    // sum·vcc stays far below 2^32.
    uint32_t den = (uint32_t)s->count * 1023UL;
    *mv = (int16_t)((s->sum * vcc_mv + den / 2) / den);
    *lo = measure_mv(s->min, vcc_mv);
    *hi = measure_mv(s->max, vcc_mv);
    return 1;
}
