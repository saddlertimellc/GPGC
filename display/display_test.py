#!/usr/bin/env python3
"""Simple SPI display test script with optional touch input.

Designed for the Waveshare 2.8" 320×240 resistive touch LCD:
https://www.waveshare.com/2.8inch-resistive-touch-lcd.htm
"""

from __future__ import annotations

import os
import select
import time

from PIL import Image, ImageDraw, ImageFont
import spidev

try:
    import st7789
except ImportError:  # pragma: no cover - fallback for different panels
    from adafruit_ili9341 import ILI9341 as st7789  # type: ignore


SPI_BUS = 0
SPI_DEVICE = 0
SPI_SPEED_HZ = 40_000_000


def init_display() -> "st7789.ST7789 | None":
    """Initialise and return the display object."""
    if os.getenv("GPGC_SKIP_DISPLAY"):
        print("GPGC_SKIP_DISPLAY set; skipping display initialisation")
        return None

    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEVICE)
    spi.max_speed_hz = SPI_SPEED_HZ

    try:
        display = st7789.ST7789(
            width=240,
            height=320,
            rotation=90,
            port=SPI_BUS,
            cs=SPI_DEVICE,
            dc=24,
            backlight=25,
            rst=23,
            spi_speed_hz=SPI_SPEED_HZ,
        )
    except RuntimeError:
        print(
            "No GPIO platform detected; skipping display and touch tests",
        )
        return None
    return display


def draw_test_pattern(display: "st7789.ST7789") -> None:
    """Draw a simple test pattern on the display."""
    image = Image.new("RGB", (display.width, display.height), color=(0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, display.width, display.height), fill=(0, 0, 255))
    draw.line((0, 0, display.width, display.height), fill=(255, 0, 0))
    draw.line((0, display.height, display.width, 0), fill=(0, 255, 0))

    font = ImageFont.load_default()
    draw.text((10, 10), "Hello, GPGC!", fill=(255, 255, 255), font=font)

    display.display(image)


def poll_touch_events(device: str = "/dev/input/event0") -> None:
    """Poll touch input events from the given input device."""
    try:
        from evdev import InputDevice, ecodes
    except ImportError:  # pragma: no cover
        print("evdev library not installed; skipping touch input")
        return

    try:
        dev = InputDevice(device)
        print(f"Using input device: {dev.name}")
    except FileNotFoundError:
        print(f"Touch device {device} not found")
        return

    while True:
        r, _, _ = select.select([dev], [], [], 0.1)
        if dev in r:
            for event in dev.read():
                if event.type == ecodes.EV_ABS:
                    print(f"Touch: code={event.code} value={event.value}")
        time.sleep(0.01)


def main() -> None:
    display = init_display()
    if display is None:
        return
    draw_test_pattern(display)
    poll_touch_events()


if __name__ == "__main__":
    main()
