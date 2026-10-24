#include "debounce.h"

#include "config.h"

uint8_t debounce_update(debounce_t *d, uint8_t raw) {
    if (raw == d->stable) {
        d->count = 0;
        return 0;
    }
    if (++d->count < DEBOUNCE_MS) return 0;
    d->stable = raw;
    d->count = 0;
    return 1;
}
