// Run the real pod firmware (build/bench.elf) in simavr, wired up like the real pod:
//   - its UART is a virtual serial port (symlink /tmp/bench-pod-sim), so the server's bridge,
//     miniterm or check scripts talk to the actual firmware binary
//   - probe voltages on A0..A3, the supply (vcc) and the talk button (D2) are set from stdin
//   - the status LED pins (D9/D10/D11) and the heartbeat (D13) are printed when they change
// Runs at real-time speed so timing (20 Hz lines, debounce, timeouts) matches the hardware.
//
//   make sim                         (or: build/sim_pod build/bench.elf [-l link] [-a] [-v])
//   stdin commands:  Y 1900 | B 5000 | G 0 | W 3300   set a probe's input in mV
//                    vcc 4987                        set the supply (AVcc) in mV
//                    noise 3                         ±mV of noise on every conversion
//                    btn down | btn up | btn [ms]    press / release / tap the talk button
//                    status | quit
//   flags: -a  LED is common-anode (pins are active-low)  ·  -v  echo UART output to stdout
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/time.h>
#include <termios.h>
#include <unistd.h>
#if defined(__APPLE__)
#include <util.h>
#else
#include <pty.h>
#endif

#include "avr_adc.h"
#include "avr_ioport.h"
#include "avr_uart.h"
#include "sim_avr.h"
#include "sim_elf.h"
#include "sim_irq.h"

#define F_CPU 16000000UL
#define BYTE_CYCLES 1400   // one UART byte at ~115200 baud
#define POLL_CYCLES 16000  // look at stdin / the pty and pace every 1 ms of simulated time

static avr_t *avr;
static int master = -1, slave = -1;
static const char *link_path = "/tmp/bench-pod-sim";
static int common_anode, verbose;
static int probe_mv[4] = {0, 0, 0, 0};
static int noise_mv = 3;
static unsigned char rx_q[512];
static int rx_len;
static int led[3];          // pin levels of D9 (R), D10 (G), D11 (B)
static int button_release_ms = -1;

static void cleanup(void) {
    char target[256];
    ssize_t n = readlink(link_path, target, sizeof target - 1);
    if (n > 0) {
        target[n] = 0;
        if (slave >= 0 && strcmp(target, ttyname(slave)) == 0) unlink(link_path);
    }
}

static void on_signal(int sig) {
    (void)sig;
    cleanup();
    _exit(0);
}

static uint64_t now_us(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000000u + tv.tv_usec;
}

static uint32_t sim_ms(void) { return (uint32_t)(avr->cycle / (F_CPU / 1000)); }

// ---- UART: firmware → pty ----
static void uart_out(struct avr_irq_t *irq, uint32_t value, void *param) {
    (void)irq, (void)param;
    unsigned char c = (unsigned char)value;
    if (write(master, &c, 1) < 0 && errno == EAGAIN) tcflush(slave, TCIFLUSH);  // nobody reading
    if (verbose) fputc(c, stdout), fflush(stdout);
}

// ---- ADC: answer each conversion the firmware starts ----
static void adc_trigger(struct avr_irq_t *irq, uint32_t value, void *param) {
    (void)irq, (void)param;
    union { avr_adc_mux_t mux; uint32_t v; } e = {.v = value};
    if (e.mux.kind != ADC_MUX_SINGLE || e.mux.src > 3) return;   // bandgap etc: simavr handles it
    int mv = probe_mv[e.mux.src];
    if (noise_mv) mv += (rand() % (2 * noise_mv + 1)) - noise_mv;
    if (mv < 0) mv = 0;
    avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_ADC0 + e.mux.src), (uint32_t)mv);
}

// ---- GPIO outputs ----
static void print_led(void) {
    int on[3];
    for (int i = 0; i < 3; i++) on[i] = common_anode ? !led[i] : led[i];
    const char *name = "other";
    if (!on[0] && !on[1] && !on[2]) name = "off";
    else if (on[0] && !on[1] && !on[2]) name = "red";
    else if (!on[0] && on[1] && !on[2]) name = "green";
    else if (!on[0] && !on[1] && on[2]) name = "blue";
    else if (on[0] && on[1] && on[2]) name = "white";
    printf("[%7u ms] LED %s (R%d G%d B%d)\n", sim_ms(), name, on[0], on[1], on[2]);
    fflush(stdout);
}

static void led_pin(struct avr_irq_t *irq, uint32_t value, void *param) {
    (void)irq;
    int i = (int)(intptr_t)param;
    if (led[i] == (int)value) return;
    led[i] = (int)value;
    print_led();
}

static void set_button(int down) {
    avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ('D'), 2), down ? 0 : 1);
    printf("[%7u ms] button %s\n", sim_ms(), down ? "down" : "up");
    fflush(stdout);
}

// ---- stdin commands ----
static void command(char *line) {
    char what[16] = {0};
    int v = 0;
    int n = sscanf(line, "%15s %d", what, &v);
    if (n < 1) return;
    const char *probes = "YBGW";
    if (strlen(what) == 1 && strchr(probes, what[0]) && n == 2) {
        probe_mv[strchr(probes, what[0]) - probes] = v;
    } else if (!strcmp(what, "vcc") && n == 2) {
        avr->vcc = avr->avcc = (uint32_t)v;
    } else if (!strcmp(what, "noise") && n == 2) {
        noise_mv = v;
    } else if (!strcmp(what, "btn")) {
        char arg[16] = {0};
        sscanf(line, "%*s %15s", arg);
        if (!strcmp(arg, "down")) set_button(1);
        else if (!strcmp(arg, "up")) set_button(0);
        else {
            set_button(1);
            button_release_ms = (int)sim_ms() + (arg[0] ? atoi(arg) : 300);
        }
    } else if (!strcmp(what, "status")) {
        printf("probes Y %d B %d G %d W %d mV · vcc %u mV · sim %u ms\n", probe_mv[0], probe_mv[1],
               probe_mv[2], probe_mv[3], avr->avcc, sim_ms());
    } else if (!strcmp(what, "quit")) {
        cleanup();
        exit(0);
    } else {
        printf("? %s", line);
    }
    fflush(stdout);
}

static void poll_io(void) {
    fd_set fds;
    struct timeval tv = {0, 0};
    FD_ZERO(&fds);
    FD_SET(0, &fds);
    FD_SET(master, &fds);
    if (select(master + 1, &fds, NULL, NULL, &tv) <= 0) return;
    if (FD_ISSET(master, &fds) && rx_len < (int)sizeof rx_q) {
        ssize_t n = read(master, rx_q + rx_len, sizeof rx_q - rx_len);
        if (n > 0) rx_len += (int)n;
    }
    if (FD_ISSET(0, &fds)) {
        static char buf[256];
        static int len;
        ssize_t n = read(0, buf + len, sizeof buf - 1 - len);
        if (n <= 0) return;
        len += (int)n;
        buf[len] = 0;
        char *nl;
        while ((nl = strchr(buf, '\n'))) {
            *nl = 0;
            command(buf);
            memmove(buf, nl + 1, strlen(nl + 1) + 1);
            len = (int)strlen(buf);
        }
    }
}

int main(int argc, char **argv) {
    const char *elf = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-a")) common_anode = 1;
        else if (!strcmp(argv[i], "-v")) verbose = 1;
        else if (!strcmp(argv[i], "-l") && i + 1 < argc) link_path = argv[++i];
        else elf = argv[i];
    }
    if (!elf) {
        fprintf(stderr, "usage: sim_pod build/bench.elf [-l /tmp/bench-pod-sim] [-a] [-v]\n");
        return 2;
    }

    elf_firmware_t fw;
    memset(&fw, 0, sizeof fw);
    if (elf_read_firmware(elf, &fw)) return fprintf(stderr, "can't read %s\n", elf), 1;
    avr = avr_make_mcu_by_name("atmega328p");
    avr_init(avr);
    avr_load_firmware(avr, &fw);
    avr->frequency = F_CPU;
    avr->vcc = avr->avcc = 4987;     // USB 5 V as the Uno sees it
    avr->aref = 1100;
    avr->log = 0;

    // Serial port + stable link (same idea as server/tools/mock_pod.py).
    if (openpty(&master, &slave, NULL, NULL, NULL)) return perror("openpty"), 1;
    struct termios t;
    tcgetattr(slave, &t);
    cfmakeraw(&t);
    tcsetattr(slave, TCSANOW, &t);
    fcntl(master, F_SETFL, fcntl(master, F_GETFL) | O_NONBLOCK);
    unlink(link_path);
    if (symlink(ttyname(slave), link_path)) perror("symlink");
    atexit(cleanup);
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGHUP, on_signal);
    setvbuf(stdout, NULL, _IOLBF, 0);

    uint32_t flags = 0;
    avr_ioctl(avr, AVR_IOCTL_UART_GET_FLAGS('0'), &flags);
    flags &= ~AVR_UART_FLAG_STDIO;
    avr_ioctl(avr, AVR_IOCTL_UART_SET_FLAGS('0'), &flags);
    avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_OUTPUT), uart_out, NULL);
    avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_OUT_TRIGGER), adc_trigger, NULL);
    for (int i = 0; i < 3; i++)
        avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ('B'), 1 + i), led_pin, (void *)(intptr_t)i);
    for (int i = 0; i < 3; i++) led[i] = common_anode;   // "off" before the firmware drives the pins
    avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ('D'), 2), 1);   // button released (pull-up)

    printf("sim pod: %s on %s (link %s)%s\n", elf, ttyname(slave), link_path, common_anode ? " · common-anode LED" : "");
    printf("  → POD_PORT=%s · stdin: Y 1900 | vcc 4987 | btn | status | quit\n", link_path);

    uint64_t t0 = now_us();
    avr_cycle_count_t next_poll = 0, next_byte = 0;
    for (;;) {
        int state = avr_run(avr);
        if (state == cpu_Done || state == cpu_Crashed) {
            fprintf(stderr, "firmware stopped (state %d) at %u ms\n", state, sim_ms());
            return 1;
        }
        if (avr->cycle >= next_byte && rx_len) {
            avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_INPUT), rx_q[0]);
            memmove(rx_q, rx_q + 1, --rx_len);
            next_byte = avr->cycle + BYTE_CYCLES;
        }
        if (avr->cycle >= next_poll) {
            next_poll = avr->cycle + POLL_CYCLES;
            poll_io();
            if (button_release_ms >= 0 && (int)sim_ms() >= button_release_ms) {
                button_release_ms = -1;
                set_button(0);
            }
            // Real-time pacing: never run ahead of the wall clock.
            uint64_t sim_us = avr->cycle / (F_CPU / 1000000);
            uint64_t wall_us = now_us() - t0;
            if (sim_us > wall_us + 2000) usleep((useconds_t)(sim_us - wall_us));
        }
    }
}
