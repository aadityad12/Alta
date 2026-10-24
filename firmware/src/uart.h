// USART0 at 115200 8N1, interrupt-driven both ways so printing never stalls the main loop.
#ifndef UART_H
#define UART_H
#include <stdint.h>

void uart_init(void);
void uart_putc(char c);
void uart_puts(const char *s);
void uart_write(const char *buf, uint8_t len);
void uart_put_int(int32_t v);

// Non-blocking: copies one complete received line (without \r\n) into `out` and returns its
// length, or returns -1 if no full line has arrived yet. Over-long lines are cut to fit.
int8_t uart_getline(char *out, uint8_t size);

#endif
