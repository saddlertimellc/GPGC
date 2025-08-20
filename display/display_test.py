#!/usr/bin/env python3
"""Simple SPI display test script with optional touch input.

Designed for the Waveshare 2.8" 320×240 resistive touch LCD:
https://www.waveshare.com/2.8inch-resistive-touch-lcd.htm
"""

from __future__ import annotations

import argparse
import os
import time

from PIL import Image, ImageDraw, ImageFont
import gpiod
import spidev
import st7789


# Pin mappings for the Luckfox Pico Ultra board.
# Adjust these constants if you wire the screen differently.
SPI_BUS = 0
SPI_DEVICE = 0
SPI_SPEED_HZ = 40_000_000

# LCD control pins
LCD_CS = 48
LCD_DC = 71
LCD_RST = 59
LCD_BL = 70

# Optional touch controller pins
TP_CS = 42
TP_IRQ = 43

DEFAULT_WIDTH = 240
DEFAULT_HEIGHT = 320
DEFAULT_ROTATION = 0


def init_display(rotation: int) -> "st7789.ST7789 | None":
    """Initialise and return the display object."""
    if os.getenv("GPGC_SKIP_DISPLAY"):
        print("GPGC_SKIP_DISPLAY set; skipping display initialisation")
        return None

    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEVICE)
    spi.max_speed_hz = SPI_SPEED_HZ

    try:
        chip = gpiod.Chip("/dev/gpiochip0")

        cs_req = chip.request_lines(
            consumer="display-test-cs",
            config={
                LCD_CS: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT),
            },
        )
        dc_req = chip.request_lines(
            consumer="display-test-dc",
            config={
                LCD_DC: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT),
            },
        )
        rst_req = chip.request_lines(
            consumer="display-test-rst",
            config={
                LCD_RST: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT),
            },
        )
        bl_req = chip.request_lines(
            consumer="display-test-bl",
            config={
                LCD_BL: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT),
            },
        )

        display = st7789.ST7789(
            width=DEFAULT_WIDTH,
            height=DEFAULT_HEIGHT,
            rotation=rotation,
            port=SPI_BUS,
            cs=(cs_req, LCD_CS),
            dc=(dc_req, LCD_DC),
            backlight=(bl_req, LCD_BL),
            rst=(rst_req, LCD_RST),
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


def init_touch() -> gpiod.LineRequest | None:
    """Initialise touch controller SPI device and IRQ line."""
    try:
        chip = gpiod.Chip("/dev/gpiochip0")
        _tp_cs_req = chip.request_lines(
            consumer="display-test-tp-cs",
            config={
                TP_CS: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT),
            },
        )
        tp_irq_req = chip.request_lines(
            consumer="display-test-tp-irq",
            config={
                TP_IRQ: gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT,
                    edge_detection=gpiod.line.Edge.FALLING,
                ),
            },
        )

        _tp_spi = spidev.SpiDev()
        _tp_spi.open(SPI_BUS, SPI_DEVICE)
        _tp_spi.max_speed_hz = SPI_SPEED_HZ

        return tp_irq_req
    except Exception:
        print("Touch controller not available; skipping touch initialisation")
        return None


def poll_touch_events(tp_irq: gpiod.LineRequest | None) -> None:
    """Poll the touch controller IRQ line for events."""
    if tp_irq is None:
        return

    print("Polling touch events (press Ctrl+C to exit)")
    while True:
        events = tp_irq.read_edge_events()
        for _ in events:
            print("Touch event detected")
        time.sleep(0.01)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rotation",
        type=int,
        default=DEFAULT_ROTATION,
        choices=[0, 180, 270],
        help="Display rotation (0, 180 or 270)",
    )
    args = parser.parse_args()

    display = init_display(args.rotation)
    if display is None:
        return
    draw_test_pattern(display)

    tp_irq = init_touch()
    poll_touch_events(tp_irq)


if __name__ == "__main__":
    main()
