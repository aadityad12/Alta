// Pod-wide settings. Wire format: docs/CONTRACTS.md §2–3. Wiring: firmware/WIRING.md.
#ifndef CONFIG_H
#define CONFIG_H

#define FW_VERSION      "0.1.0"
#define NPROBES         4       // Y, B, G, W on A0..A3
#define SAMPLE_MS       50      // one sample line every 50 ms (20 Hz)
#define VCC_EVERY_MS    500     // re-measure the supply this often
#define BANDGAP_MV      1100L   // internal 1.1 V reference; tune per board in #10
#define DEBOUNCE_MS     20      // button must be stable this long

// Status LED wiring (#5). Build with `make LED=ca` for a common-anode LED.
#ifndef LED_COMMON_ANODE
#define LED_COMMON_ANODE 0
#endif

#endif
