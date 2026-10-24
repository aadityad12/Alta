// The pod's wire format (docs/CONTRACTS.md §2–3). Pure C, no hardware: also built by `make test`.
#ifndef PROTO_H
#define PROTO_H
#include <stdint.h>

#define PROTO_LINE_MAX 160   // longest possible sample line is ~130 bytes

// Each formatter writes one complete line ending in \n into buf and returns its length.
uint8_t proto_hello(char *buf);
uint8_t proto_sample(char *buf, uint32_t seq, uint32_t t, const int16_t mv[4], const int16_t lo[4],
                     const int16_t hi[4], uint16_t vcc, uint8_t btn);
uint8_t proto_btn_evt(char *buf, uint8_t down, uint32_t t);
uint8_t proto_pong(char *buf);
uint8_t proto_err(char *buf);

typedef enum {
    CMD_NONE,       // empty line: ignore
    CMD_LED_IDLE,
    CMD_LED_LISTEN,
    CMD_LED_THINK,
    CMD_LED_SPEAK,
    CMD_LED_ERROR,
    CMD_PING,
    CMD_UNKNOWN,
} cmd_t;

// One received line (without \n). Exact, case-sensitive matches; trailing spaces/\r are ignored.
cmd_t proto_parse_cmd(const char *line);

#endif
