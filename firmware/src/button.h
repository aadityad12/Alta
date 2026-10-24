// Talk button on D2 (PD2) to GND, internal pull-up. Debounced in the 1 ms timer tick.
#ifndef BUTTON_H
#define BUTTON_H
#include <stdint.h>

void button_init(void);
uint8_t button_held(void);                              // debounced: 1 while held
uint8_t button_take_edge(uint8_t *down, uint32_t *t);   // 1 if an edge is waiting (oldest first)

#endif
