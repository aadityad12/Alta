#include "proto.h"

#include "config.h"

static char *put_str(char *p, const char *s) {
    while (*s) *p++ = *s++;
    return p;
}

static char *put_uint(char *p, uint32_t u) {
    char tmp[10];
    uint8_t n = 0;
    do {
        tmp[n++] = (char)('0' + u % 10);
        u /= 10;
    } while (u);
    while (n) *p++ = tmp[--n];
    return p;
}

static char *put_int(char *p, int32_t v) {
    if (v < 0) {
        *p++ = '-';
        return put_uint(p, (uint32_t)(-v));
    }
    return put_uint(p, (uint32_t)v);
}

static char *put_array(char *p, const char *key, const int16_t v[4]) {
    p = put_str(p, key);
    *p++ = '[';
    for (uint8_t i = 0; i < 4; i++) {
        if (i) *p++ = ',';
        p = put_int(p, v[i]);
    }
    *p++ = ']';
    return p;
}

static uint8_t finish(char *buf, char *p) {
    *p++ = '\n';
    *p = '\0';
    return (uint8_t)(p - buf);
}

uint8_t proto_hello(char *buf) {
    // Leading \n ends any line a reset cut off, so it can't swallow the hello.
    return finish(buf, put_str(buf, "\n{\"hello\":\"bench-pod\",\"fw\":\"" FW_VERSION
                                    "\",\"probes\":[\"Y\",\"B\",\"G\",\"W\"]}"));
}

uint8_t proto_sample(char *buf, uint32_t seq, uint32_t t, const int16_t mv[4], const int16_t lo[4],
                     const int16_t hi[4], uint16_t vcc, uint8_t btn) {
    char *p = put_str(buf, "{\"seq\":");
    p = put_uint(p, seq);
    p = put_str(p, ",\"t\":");
    p = put_uint(p, t);
    p = put_array(p, ",\"mv\":", mv);
    p = put_array(p, ",\"lo\":", lo);
    p = put_array(p, ",\"hi\":", hi);
    p = put_str(p, ",\"vcc\":");
    p = put_uint(p, vcc);
    p = put_str(p, ",\"btn\":");
    *p++ = btn ? '1' : '0';
    *p++ = '}';
    return finish(buf, p);
}

uint8_t proto_btn_evt(char *buf, uint8_t down, uint32_t t) {
    char *p = put_str(buf, "{\"evt\":\"btn\",\"down\":");
    *p++ = down ? '1' : '0';
    p = put_str(p, ",\"t\":");
    p = put_uint(p, t);
    *p++ = '}';
    return finish(buf, p);
}

uint8_t proto_pong(char *buf) { return finish(buf, put_str(buf, "{\"pong\":1,\"fw\":\"" FW_VERSION "\"}")); }

uint8_t proto_err(char *buf) { return finish(buf, put_str(buf, "{\"err\":\"unknown_cmd\"}")); }

static uint8_t is(const char *line, uint8_t len, const char *word) {
    uint8_t i = 0;
    for (; word[i]; i++)
        if (i >= len || line[i] != word[i]) return 0;
    return i == len;
}

cmd_t proto_parse_cmd(const char *line) {
    uint8_t len = 0;
    while (line[len]) len++;
    while (len && (line[len - 1] == ' ' || line[len - 1] == '\r' || line[len - 1] == '\t')) len--;
    if (!len) return CMD_NONE;
    if (is(line, len, "PING")) return CMD_PING;
    if (is(line, len, "LED IDLE")) return CMD_LED_IDLE;
    if (is(line, len, "LED LISTEN")) return CMD_LED_LISTEN;
    if (is(line, len, "LED THINK")) return CMD_LED_THINK;
    if (is(line, len, "LED SPEAK")) return CMD_LED_SPEAK;
    if (is(line, len, "LED ERROR")) return CMD_LED_ERROR;
    return CMD_UNKNOWN;
}
