// Interrupt-driven ADC: cycles A0..A3 continuously (one throw-away + one kept conversion per
// channel after each mux switch) and, on request, measures the supply via the 1.1 V bandgap.
#ifndef ADC_H
#define ADC_H
#include <stdint.h>

#include "measure.h"

void adc_init(void);                     // also takes a first supply reading (blocking, ~2 ms)
void adc_start(void);                    // start the background conversions
void adc_snapshot(stat_t out[4]);        // copy and reset the per-channel window stats (atomic)
void adc_request_vcc(void);              // measure the bandgap after the current A0..A3 pass
uint8_t adc_take_vcc_raw(uint16_t *raw); // 1 when a new bandgap reading is ready
uint16_t adc_first_vcc_raw(void);

#endif
