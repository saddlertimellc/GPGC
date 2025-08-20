#!/usr/bin/env python3
"""Simple SPI display test script with optional touch input.

Designed for the Waveshare 2.8" 320×240 resistive touch LCD:
https://www.waveshare.com/2.8inch-resistive-touch-lcd.htm
"""

from __future__ import annotations

import argparse
import os
import select
import time

from PIL import Image, ImageDraw, ImageFont
import gpiod
import spidev

try:
    import st7789
except ImportError:  # pragma: no cover - fallback for different panels
    from adafruit_ili9341 import ILI9341 as st7789  # type: ignore


SPI_BUS = 0
SPI_DEVICE = 0
SPI_SPEED_HZ = 40_000_000

DEFAULT_WIDTH = 240
DEFAULT_HEIGHT = 320
DEFAULT_ROTATION = 180

# Luckfox Pico Ultra GPIO offsets mapping:
# - GPIO2_A7_d (DC)
# - GPIO1_D3_d (Reset)
# - GPIO2_A6_d (Backlight)
DC_PIN = 71  # GPIO2_A7_d
RST_PIN = 59  # GPIO1_D3_d
BACKLIGHT_PIN = 70  # GPIO2_A6_d


def init_display(width: int, height: int, rotation: int) -> "st7789.ST7789 | None":
    """Initialise and return the display object."""
    if os.getenv("GPGC_SKIP_DISPLAY"):
        print("GPGC_SKIP_DISPLAY set; skipping display initialisation")
        return None

    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEVICE)
    spi.max_speed_hz = SPI_SPEED_HZ

    try:
        chip = gpiod.Chip("/dev/gpiochip0")

        dc_req = chip.request_lines(
            consumer="display-test-dc",
            config={
                DC_PIN: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT),
            },
        )
        rst_req = chip.request_lines(
            consumer="display-test-rst",
            config={
                RST_PIN: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT),
            },
        )
        bl_req = chip.request_lines(
            consumer="display-test-bl",
            config={
                BACKLIGHT_PIN: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT),
            },
        )

        display = st7789.ST7789(
            width=width,
            height=height,
            rotation=rotation,
            port=SPI_BUS,
            cs=SPI_DEVICE,
            dc=(dc_req, DC_PIN),
            backlight=(bl_req, BACKLIGHT_PIN),
            rst=(rst_req, RST_PIN),
            spi_speed_hz=SPI_SPEED_HZ,
        )
    except RuntimeError:
        print(
            "No GPIO platform detected; skipping display and touch tests",
        )
        return None
    except OSError:
        print("GPIO chip not found; skipping display and touch tests")
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Display width in pixels")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="Display height in pixels")
    parser.add_argument(
        "--rotation",
        type=int,
        default=DEFAULT_ROTATION,
        choices=[0, 180],
        help="Display rotation (0 or 180)",
    )
    args = parser.parse_args()

    display = init_display(args.width, args.height, args.rotation)
    if display is None:
        return
    draw_test_pattern(display)
    poll_touch_events()


if __name__ == "__main__":
    main()
