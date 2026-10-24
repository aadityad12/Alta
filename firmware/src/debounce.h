// Button debounce, fed once per 1 ms tick. Pure C: also built by `make test`.
#ifndef DEBOUNCE_H
#define DEBOUNCE_H
#include <stdint.h>

typedef struct {
    uint8_t stable;   // debounced state: 1 = pressed
    uint8_t count;    // ms the raw input has disagreed with `stable`
} debounce_t;

// Feed the raw state (1 = pressed). Returns 1 on the tick the debounced state changes.
uint8_t debounce_update(debounce_t *d, uint8_t raw);

#endif
