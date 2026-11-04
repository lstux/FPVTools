#include "board.h"

#if HAS_TFT

#include "display.h"

#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <Arduino.h>
#include <SPI.h>
#include <string.h>

namespace {

Adafruit_ST7735 tft(&SPI, PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_RST);

const uint32_t DEBOUNCE_MS = 30;
const uint32_t LONG_MS = 1000;

uint16_t rgb(uint8_t r, uint8_t g, uint8_t b)
{
#if TFT_SWAP_RB
    uint8_t t = r;
    r = b;
    b = t;
#endif
    return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

uint16_t color565(uint8_t c)
{
    switch (c) {
    case SC_GREEN: return rgb(61, 220, 132);
    case SC_AMBER: return rgb(255, 176, 32);
    case SC_RED: return rgb(255, 77, 77);
    case SC_CYAN: return rgb(79, 214, 255);
    case SC_MAGENTA: return rgb(255, 90, 209);
    case SC_GREY: return rgb(142, 156, 171);
    default: return rgb(228, 235, 242);
    }
}

const uint16_t BG = 0x0000;

// y position of each line: header, big line, small lines, last line pinned to the bottom
int lineY(int idx, int n, const ScreenLine *l)
{
    if (idx == n - 1) return 128 - 8;
    int y = 0;
    for (int i = 0; i < idx; ++i) y += (l[i].size == 2 ? 18 : 10) + (i == 0 ? 2 : 0);
    return y;
}

} // namespace

void Display::begin()
{
#if PIN_TFT_BL >= 0
    pinMode(PIN_TFT_BL, OUTPUT);
    digitalWrite(PIN_TFT_BL, HIGH);
#endif
    SPI.begin(PIN_TFT_SCLK, -1, PIN_TFT_MOSI, PIN_TFT_CS);
    tft.initR(TFT_TAB);
    tft.setRotation(1); // landscape, buttons on the right... use 3 to turn it upside down
    tft.fillScreen(BG);
    tft.setTextWrap(false);
    tft.setTextSize(1);
    tft.setTextColor(color565(SC_WHITE), BG);
    tft.setCursor(4, 56);
    tft.print("esp-tracker " FW_VERSION);

    const int pins[3] = {PIN_BTN1, PIN_BTN2, PIN_BTN3};
    for (int i = 0; i < 3; ++i) {
        btn_[i] = {pins[i], false, false, 0, 0};
        // 34..39 are input-only and have no internal pull-up: the board provides them.
        if (pins[i] >= 0) pinMode(pins[i], pins[i] >= 34 ? INPUT : INPUT_PULLUP);
    }
}

void Display::paintLine(int idx, const ScreenLine &l)
{
    const int y = lineY(idx, shownN_, shown_);
    const int cols = l.size == 2 ? SCREEN_COLS / 2 : SCREEN_COLS;
    char padded[SCREEN_COLS + 1];
    snprintf(padded, sizeof(padded), "%-*s", cols, l.text); // spaces overwrite the old text: no flicker
    tft.setTextSize(l.size);
    if (idx == 0) {
        // header: dark text on a bar of the status colour
        tft.fillRect(0, 0, 160, 10, color565(l.color));
        tft.setTextColor(BG, color565(l.color));
        tft.setCursor(1, 1);
    } else {
        tft.setTextColor(color565(l.color), BG);
        tft.setCursor(1, y);
    }
    tft.print(padded);
}

void Display::draw(const ScreenLine *in, int n)
{
    ScreenLine lines[SCREEN_LINES];
    if (n > SCREEN_LINES) n = SCREEN_LINES;
    memcpy(lines, in, sizeof(ScreenLine) * (size_t)n);
    if (toastActive(millis()) && n > 0) {
        strncpy(lines[n - 1].text, toastText_, sizeof(lines[n - 1].text));
        lines[n - 1].text[SCREEN_COLS] = '\0';
        lines[n - 1].color = toastColor_;
        lines[n - 1].size = 1;
    }
    bool layoutChanged = n != shownN_;
    for (int i = 0; i < n && !layoutChanged; ++i) layoutChanged = valid_[i] && shown_[i].size != lines[i].size;
    if (layoutChanged) {
        tft.fillScreen(BG);
        for (int i = 0; i < SCREEN_LINES; ++i) valid_[i] = false;
    }
    shownN_ = n;
    for (int i = 0; i < n; ++i) {
        if (valid_[i] && shown_[i].color == lines[i].color && strcmp(shown_[i].text, lines[i].text) == 0) continue;
        shown_[i] = lines[i];
        valid_[i] = true;
        paintLine(i, lines[i]);
    }
}

void Display::toast(const char *text, uint8_t color, uint32_t now)
{
    strncpy(toastText_, text, SCREEN_COLS);
    toastText_[SCREEN_COLS] = '\0';
    toastColor_ = color;
    toastUntil_ = now + 2500;
}

void Display::pollButtons(uint32_t now, ButtonEvent ev[3])
{
    for (int i = 0; i < 3; ++i) {
        ev[i] = BTN_NONE;
        Btn &b = btn_[i];
        if (b.pin < 0) continue;
        const bool pressed = digitalRead(b.pin) == BTN_ACTIVE_LEVEL;
        if (pressed != b.down) {
            if (now - b.changedMs < DEBOUNCE_MS) continue;
            b.changedMs = now;
            b.down = pressed;
            if (pressed) {
                b.downMs = now;
                b.longSent = false;
            } else if (!b.longSent) {
                ev[i] = BTN_SHORT;
            }
        } else if (b.down && !b.longSent && now - b.downMs >= LONG_MS) {
            b.longSent = true; // long press fires while still held, once
            ev[i] = BTN_LONG;
        }
    }
}

#endif // HAS_TFT
