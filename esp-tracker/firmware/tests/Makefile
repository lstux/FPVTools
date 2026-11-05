# Host-side tests for the portable core. Needs only g++ (no ESP toolchain).
#   make test      run the unit tests
#   make golden    regenerate ../../backend/tests/fixtures/firmware_events.jsonl
#   make syntax    compile-check src/main.cpp against the stub Arduino headers in stubs/
CORE   := ../lib/tracker_core
SRCS   := $(wildcard $(CORE)/*.cpp)
CXX    ?= g++
# gnu++11 is the lowest standard used by the Arduino-ESP32 toolchains we target
CXXFLAGS := -std=gnu++11 -O1 -g -Wall -Wextra -Werror -I$(CORE)

.PHONY: test golden syntax clean
test: build/test_core
	./build/test_core

build/test_core: test_core.cpp $(SRCS) $(wildcard $(CORE)/*.h)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -fsanitize=address,undefined -o $@ test_core.cpp $(SRCS)

build/dump_events: dump_events.cpp $(SRCS) $(wildcard $(CORE)/*.h)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -o $@ dump_events.cpp $(SRCS)

golden: build/dump_events
	./build/dump_events > ../../backend/tests/fixtures/firmware_events.jsonl
	@echo wrote ../../backend/tests/fixtures/firmware_events.jsonl

# Catches typos / type errors in the hardware glue. It is NOT a substitute for a real
# PlatformIO build: the stubs only mimic the subset of the Arduino-ESP32 API that main.cpp uses.
GLUE := ../src/main.cpp ../src/sensors.cpp ../src/display.cpp
SYN  := $(CXX) -std=gnu++11 -fsyntax-only -Wall -Wextra -Werror -Istubs -I$(CORE) -I../include
syntax:
	# C3-like: USB-CDC, no sensors, no screen
	for f in $(GLUE); do $(SYN) -DARDUINO_USB_CDC_ON_BOOT=1 -DPIN_PAN=4 -DPIN_TILT=5 $$f || exit 1; done
	# classic ESP32 with LED, I2C sensors and GPS
	for f in $(GLUE); do $(SYN) -DPIN_PAN=25 -DPIN_TILT=26 -DPIN_LED=2 -DPIN_SDA=21 -DPIN_SCL=22 -DPIN_GPS_RX=16 -DPIN_GPS_TX=17 $$f || exit 1; done
	# TTGO TS: everything
	for f in $(GLUE); do $(SYN) -DPIN_PAN=26 -DPIN_TILT=33 -DPIN_SDA=21 -DPIN_SCL=22 -DPIN_GPS_RX=32 -DPIN_GPS_TX=-1 \
	  -DHAS_TFT=1 -DPIN_TFT_CS=16 -DPIN_TFT_DC=17 -DPIN_TFT_MOSI=23 -DPIN_TFT_SCLK=5 -DPIN_TFT_RST=-1 -DPIN_TFT_BL=27 \
	  -DPIN_BTN1=34 -DPIN_BTN2=35 -DPIN_BTN3=39 $$f || exit 1; done

clean:
	rm -rf build
