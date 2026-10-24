// Host unit tests for the hardware-free firmware code: `make test` (no Uno needed).
// The expected strings are the example lines from docs/CONTRACTS.md §2–3, byte for byte.
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "config.h"
#include "debounce.h"
#include "measure.h"
#include "proto.h"

static int fails, checks;

#define CHECK(cond, ...)                                  \
    do {                                                  \
        checks++;                                         \
        if (!(cond)) {                                    \
            fails++;                                      \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);   \
            printf(__VA_ARGS__);                          \
            printf("\n");                                 \
        }                                                 \
    } while (0)

static void expect_line(const char *got, uint8_t len, const char *want) {
    CHECK(strcmp(got, want) == 0, "\n  got:  %s  want: %s", got, want);
    CHECK(len == strlen(want), "length %u, want %zu", len, strlen(want));
}

static void test_lines(void) {
    char buf[PROTO_LINE_MAX];
    uint8_t n;

    n = proto_hello(buf);
    expect_line(buf, n, "\n{\"hello\":\"bench-pod\",\"fw\":\"0.1.0\",\"probes\":[\"Y\",\"B\",\"G\",\"W\"]}\n");

    // §2 example sample line
    int16_t mv[4] = {5012, 1921, -1, 3}, lo[4] = {4990, 1900, -1, 0}, hi[4] = {5030, 1940, -1, 8};
    n = proto_sample(buf, 812, 40600, mv, lo, hi, 4987, 0);
    expect_line(buf, n,
                "{\"seq\":812,\"t\":40600,\"mv\":[5012,1921,-1,3],\"lo\":[4990,1900,-1,0],"
                "\"hi\":[5030,1940,-1,8],\"vcc\":4987,\"btn\":0}\n");

    // Longest possible sample line must fit the buffer.
    int16_t big[4] = {-1, 5100, 5100, 5100};
    n = proto_sample(buf, UINT32_MAX, UINT32_MAX, big, big, big, 65535, 1);
    CHECK(n < PROTO_LINE_MAX, "worst-case line is %u bytes, buffer %d", n, PROTO_LINE_MAX);
    printf("  worst-case sample line: %u bytes\n", n);

    n = proto_btn_evt(buf, 1, 40612);   // §2 example event line
    expect_line(buf, n, "{\"evt\":\"btn\",\"down\":1,\"t\":40612}\n");
    n = proto_btn_evt(buf, 0, 0);
    expect_line(buf, n, "{\"evt\":\"btn\",\"down\":0,\"t\":0}\n");
    n = proto_pong(buf);                // §3
    expect_line(buf, n, "{\"pong\":1,\"fw\":\"0.1.0\"}\n");
    n = proto_err(buf);
    expect_line(buf, n, "{\"err\":\"unknown_cmd\"}\n");
}

static void test_commands(void) {
    struct { const char *line; cmd_t want; } cases[] = {
        {"LED IDLE", CMD_LED_IDLE},     {"LED LISTEN", CMD_LED_LISTEN}, {"LED THINK", CMD_LED_THINK},
        {"LED SPEAK", CMD_LED_SPEAK},   {"LED ERROR", CMD_LED_ERROR},   {"PING", CMD_PING},
        {"PING\r", CMD_PING},           {"LED THINK  ", CMD_LED_THINK}, {"", CMD_NONE},
        {"\r", CMD_NONE},               {"ping", CMD_UNKNOWN},          {"LED think", CMD_UNKNOWN},
        {"LED", CMD_UNKNOWN},           {"LED PURPLE", CMD_UNKNOWN},    {"LEDTHINK", CMD_UNKNOWN},
        {"PINGPONG", CMD_UNKNOWN},      {"LED THINKING", CMD_UNKNOWN},  {" PING", CMD_UNKNOWN},
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++)
        CHECK(proto_parse_cmd(cases[i].line) == cases[i].want, "parse(%s) = %d, want %d", cases[i].line,
              proto_parse_cmd(cases[i].line), cases[i].want);
}

static void test_measure(void) {
    // 1.1 V bandgap read against a 5.0 V AVcc: raw = 1100·1023/5000 ≈ 225.
    CHECK(measure_vcc_mv(225) == 5001, "vcc(225) = %u", measure_vcc_mv(225));
    CHECK(measure_vcc_mv(220) == 5115, "vcc(220) = %u", measure_vcc_mv(220));
    CHECK(measure_vcc_mv(0) == 0, "vcc(0) must not divide by zero");

    CHECK(measure_mv(0, 4987) == 0, "0 counts = 0 mV");
    CHECK(measure_mv(1023, 4987) == 4987, "full scale = vcc, got %d", measure_mv(1023, 4987));
    CHECK(measure_mv(390, 5001) == 1907, "390 counts at 5001 mV = %d", measure_mv(390, 5001));

    stat_t s;
    stat_reset(&s);
    int16_t mv = 7, lo = 7, hi = 7;
    CHECK(measure_window(&s, 5000, &mv, &lo, &hi) == 0 && mv == 7, "empty window leaves outputs alone");
    uint16_t reads[] = {389, 390, 391, 390, 388, 392};
    for (size_t i = 0; i < 6; i++) stat_add(&s, reads[i]);
    CHECK(measure_window(&s, 5001, &mv, &lo, &hi) == 1, "window has data");
    CHECK(mv == 1907 && lo == measure_mv(388, 5001) && hi == measure_mv(392, 5001),
          "window mv/lo/hi = %d/%d/%d", mv, lo, hi);
    CHECK(lo <= mv && mv <= hi, "lo <= mv <= hi");

    // A full 50 ms window at full scale must not overflow 32-bit maths (~60 reads; test 200).
    stat_reset(&s);
    for (int i = 0; i < 200; i++) stat_add(&s, 1023);
    measure_window(&s, 5100, &mv, &lo, &hi);
    CHECK(mv == 5100 && hi == 5100, "200 full-scale reads at 5100 mV → %d", mv);
}

static void test_debounce(void) {
    debounce_t d = {0, 0};
    int edges = 0, t_down = -1, t_up = -1;
    // ms 0–9 bouncing, 10–109 held, 110–114 bouncing, then released.
    for (int t = 0; t < 200; t++) {
        uint8_t raw = t < 10 ? (uint8_t)(t % 2) : t < 110 ? 1 : t < 115 ? (uint8_t)(t % 2) : 0;
        if (debounce_update(&d, raw)) {
            edges++;
            if (d.stable) t_down = t;
            else t_up = t;
        }
    }
    CHECK(edges == 2, "a bouncy press + release gives exactly 2 edges, got %d", edges);
    CHECK(t_down == 9 + DEBOUNCE_MS - 1, "press reported at %d ms (held from 9 ms: the last bounce is high)", t_down);
    CHECK(t_up > 110 && t_up <= 115 + DEBOUNCE_MS, "release reported at %d ms", t_up);

    debounce_t g = {0, 0};
    edges = 0;
    for (int t = 0; t < 100; t++) edges += debounce_update(&g, (t % 20) == 0);  // 1 ms glitches
    CHECK(edges == 0, "1 ms glitches are ignored, got %d edges", edges);
}

int main(void) {
    test_lines();
    test_commands();
    test_measure();
    test_debounce();
    printf("%d/%d checks passed\n", checks - fails, checks);
    return fails ? 1 : 0;
}
