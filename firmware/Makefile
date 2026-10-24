# Bench probe pod firmware (bare-metal C, ATmega328P / Arduino Uno).
#
#   make                 build build/bench.hex
#   make flash           flash it (auto-detects the Uno; or PORT=/dev/cu.usbmodemXXXX)
#   make size            flash/RAM use
#   make test            host unit tests for the protocol, maths and debounce (no hardware)
#   make sim             run bench.elf in simavr; its UART appears at /tmp/bench-pod-sim
#   make monitor         serial monitor (close it, and the server, before flashing)
#
# Options: LED=ca for a common-anode status LED · BAUD=57600 for old-bootloader clones.

MCU    := atmega328p
F_CPU  := 16000000UL
BUILD  := build
TARGET := $(BUILD)/bench
LED    ?= cc
BAUD   ?= 115200
PORT   ?= $(firstword $(wildcard /dev/cu.usbmodem* /dev/cu.usbserial* /dev/cu.wchusbserial* /dev/ttyACM* /dev/ttyUSB*))

# Toolchain: avr-gcc on PATH (brew tap osx-cross/avr; apt install gcc-avr avr-libc avrdude),
# else the copy arduino-cli installs with the arduino:avr core.
ARDUINO_TOOLS := $(HOME)/Library/Arduino15/packages/arduino/tools
AVR_BIN := $(if $(shell command -v avr-gcc),,$(lastword $(wildcard $(ARDUINO_TOOLS)/avr-gcc/*/bin))/)
AVRDUDE := $(if $(shell command -v avrdude),avrdude,$(lastword $(wildcard $(ARDUINO_TOOLS)/avrdude/*/bin/avrdude)))
CC      := $(AVR_BIN)avr-gcc
OBJCOPY := $(AVR_BIN)avr-objcopy
SIZE    := $(AVR_BIN)avr-size

CFLAGS  := -mmcu=$(MCU) -DF_CPU=$(F_CPU) -Os -Wall -Wextra -std=c11 -g \
           -ffunction-sections -fdata-sections -MMD -MP
ifeq ($(LED),ca)
CFLAGS  += -DLED_COMMON_ANODE=1
endif
LDFLAGS := -mmcu=$(MCU) -Wl,--gc-sections

SRCS := $(wildcard src/*.c)
OBJS := $(SRCS:src/%.c=$(BUILD)/%.o)

.PHONY: all flash size test sim monitor clean
all: $(TARGET).hex

$(BUILD)/%.o: src/%.c | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(TARGET).elf: $(OBJS)
	$(CC) $(LDFLAGS) $^ -o $@

$(TARGET).hex: $(TARGET).elf
	$(OBJCOPY) -O ihex -R .eeprom $< $@
	@$(SIZE) --mcu=$(MCU) -C $< | grep -E 'Program|Data'

$(BUILD):
	mkdir -p $@

flash: $(TARGET).hex
	@test -n "$(PORT)" || { echo "No Uno found. Plug it in, or pass PORT=/dev/cu.usbmodemXXXX"; exit 1; }
	$(AVRDUDE) -c arduino -p m328p -b $(BAUD) -P $(PORT) -U flash:w:$<:i

size: $(TARGET).elf
	$(SIZE) --mcu=$(MCU) -C $<

# ---- host-side checks (no Uno needed) ----
HOST_CC   ?= cc
HOST_SRCS := src/proto.c src/measure.c src/debounce.c

test: | $(BUILD)
	$(HOST_CC) -std=c11 -Wall -Wextra -O1 -Isrc test/test_host.c $(HOST_SRCS) -o $(BUILD)/test_host
	$(BUILD)/test_host

SIMAVR := $(shell brew --prefix simavr 2>/dev/null)
SIM_CFLAGS := -std=gnu11 -O2 -Wall -I$(SIMAVR)/include/simavr -I$(SIMAVR)/include
SIM_LIBS := -L$(SIMAVR)/lib -lsimavr $(shell pkg-config --libs libelf 2>/dev/null || echo -lelf) -lutil

$(BUILD)/sim_pod: sim/sim_pod.c | $(BUILD)
	$(HOST_CC) $(SIM_CFLAGS) $(shell pkg-config --cflags libelf 2>/dev/null) $< -o $@ $(SIM_LIBS)

sim: $(TARGET).elf $(BUILD)/sim_pod
	$(BUILD)/sim_pod $(TARGET).elf $(SIMFLAGS)

monitor:
	@test -n "$(PORT)" || { echo "No Uno found. Pass PORT=..."; exit 1; }
	python3 -m serial.tools.miniterm $(PORT) 115200

clean:
	rm -rf $(BUILD)

-include $(OBJS:.o=.d)
