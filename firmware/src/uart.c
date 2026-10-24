#include "uart.h"

#include <avr/interrupt.h>
#include <avr/io.h>

#define RX_SIZE 64      // power of two
#define TX_SIZE 256     // two whole sample lines; a full buffer just makes uart_putc wait

static volatile char rx_buf[RX_SIZE];
static volatile uint8_t rx_head, rx_tail;
static volatile char tx_buf[TX_SIZE];
static volatile uint8_t tx_head, tx_tail;   // uint8_t wraps at 256 = TX_SIZE

void uart_init(void) {
    // U2X0 = 1, UBRR0 = 16 → 117647 baud (+2.1%), which the Uno's USB chip handles fine.
    UCSR0A = (1 << U2X0);
    UBRR0 = 16;
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
    UCSR0B = (1 << RXEN0) | (1 << TXEN0) | (1 << RXCIE0);
}

ISR(USART_RX_vect) {
    char c = UDR0;
    uint8_t next = (rx_head + 1) & (RX_SIZE - 1);
    if (next != rx_tail) {      // full: drop the byte (the command will come back as err)
        rx_buf[rx_head] = c;
        rx_head = next;
    }
}

ISR(USART_UDRE_vect) {
    if (tx_head == tx_tail) {
        UCSR0B &= ~(1 << UDRIE0);
        return;
    }
    UDR0 = tx_buf[tx_tail++];
}

void uart_putc(char c) {
    uint8_t next = tx_head + 1;
    while (next == tx_tail) {
        // Buffer full: wait for the UDRE interrupt to drain a byte.
    }
    tx_buf[tx_head] = c;
    tx_head = next;
    UCSR0B |= (1 << UDRIE0);
}

void uart_puts(const char *s) {
    while (*s) uart_putc(*s++);
}

void uart_write(const char *buf, uint8_t len) {
    while (len--) uart_putc(*buf++);
}

void uart_put_int(int32_t v) {
    char tmp[11];
    uint8_t n = 0;
    uint32_t u = v < 0 ? (uint32_t)(-v) : (uint32_t)v;
    if (v < 0) uart_putc('-');
    do {
        tmp[n++] = (char)('0' + u % 10);
        u /= 10;
    } while (u);
    while (n) uart_putc(tmp[--n]);
}

int8_t uart_getline(char *out, uint8_t size) {
    static char line[48];
    static uint8_t len;
    while (rx_tail != rx_head) {
        char c = rx_buf[rx_tail];
        rx_tail = (rx_tail + 1) & (RX_SIZE - 1);
        if (c == '\n') {
            uint8_t n = len < size - 1 ? len : size - 1;
            for (uint8_t i = 0; i < n; i++) out[i] = line[i];
            out[n] = '\0';
            len = 0;
            return (int8_t)n;
        }
        if (c != '\r' && len < sizeof line) line[len++] = c;
    }
    return -1;
}
