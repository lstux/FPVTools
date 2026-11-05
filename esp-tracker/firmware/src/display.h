// Status screen + buttons of the LilyGO TTGO TS (ST7735 160x128). Compiled only with HAS_TFT=1.
// The text of each page comes from lib/tracker_core/screen.cpp; this file only paints it and reads
// the buttons.
#pragma once
#include <stdint.h>

#include "screen.h"

enum ButtonEvent : uint8_t { BTN_NONE, BTN_SHORT, BTN_LONG };

class Display {
public:
    void begin();
    // Repaints only the lines that changed (no flicker).
    void draw(const ScreenLine *lines, int n);
    // Shows a message instead of the last line for a couple of seconds.
    void toast(const char *text, uint8_t color, uint32_t now_ms);
    bool toastActive(uint32_t now_ms) const { return now_ms < toastUntil_; }

    // Button handling: call often (every loop). Returns one event per button.
    void pollButtons(uint32_t now_ms, ButtonEvent ev[3]);

private:
    void paintLine(int idx, const ScreenLine &l);
    ScreenLine shown_[SCREEN_LINES];
    bool valid_[SCREEN_LINES] = {false};
    int shownN_ = 0;
    char toastText_[SCREEN_COLS + 1] = "";
    uint8_t toastColor_ = 0;
    uint32_t toastUntil_ = 0;

    struct Btn {
        int pin;
        bool down;
        bool longSent;
        uint32_t changedMs;
        uint32_t downMs;
    };
    Btn btn_[3];
};
