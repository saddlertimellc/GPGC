#!/usr/bin/env python3
"""Simple display and touch panel test for the Luckfox Pico Ultra.

This script assumes a Waveshare 2.8" 320x240 resistive touch LCD wired to
the board using the default pinout.  It draws a basic colour pattern on the
screen and then reports touch coordinates until interrupted.

The code deliberately avoids any platform detection and is intended to be run
directly on the target hardware.
"""

from __future__ import annotations

import signal
import time
from dataclasses import dataclass

import gpiod
import spidev
from PIL import Image, ImageDraw, ImageFont
import st7789

# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

SPI_BUS = 0
SPI_DEVICE = 0
SPI_SPEED_HZ = 40_000_000

# LCD control pins (chip path, line offset)
LCD_DC = ("/dev/gpiochip2", 7)
LCD_RST = ("/dev/gpiochip1", 27)
LCD_BL = ("/dev/gpiochip2", 6)

# Touch controller pins
TP_CS = ("/dev/gpiochip1", 10)
TP_IRQ = ("/dev/gpiochip1", 11)

WIDTH = 240
HEIGHT = 320


# ---------------------------------------------------------------------------
# GPIO helpers
# ---------------------------------------------------------------------------

@dataclass
class GPIOPin:
    request: gpiod.LineRequest
    offset: int


def request_output(pin: tuple[str, int], name: str) -> GPIOPin:
    """Request a GPIO line configured as an output."""

    chip = gpiod.Chip(pin[0])
    req = chip.request_lines(
        consumer=name,
        config={pin[1]: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT)},
    )
    return GPIOPin(req, pin[1])


def request_input(pin: tuple[str, int], name: str) -> GPIOPin:
    """Request a GPIO line configured as an input with falling-edge detection."""

    chip = gpiod.Chip(pin[0])
    req = chip.request_lines(
        consumer=name,
        config={
            pin[1]: gpiod.LineSettings(
                direction=gpiod.line.Direction.INPUT,
                edge_detection=gpiod.line.Edge.FALLING,
            )
        },
    )
    return GPIOPin(req, pin[1])


# ---------------------------------------------------------------------------
# Display handling
# ---------------------------------------------------------------------------


def init_display(rotation: int = 0) -> st7789.ST7789:
    """Initialise the ST7789 display and return the driver object."""

    dc = request_output(LCD_DC, "disp-dc")
    rst = request_output(LCD_RST, "disp-rst")
    bl = request_output(LCD_BL, "disp-bl")

    display = st7789.ST7789(
        width=WIDTH,
        height=HEIGHT,
        rotation=rotation,
        port=SPI_BUS,
        cs=SPI_DEVICE,
        dc=(dc.request, dc.offset),
        rst=(rst.request, rst.offset),
        backlight=(bl.request, bl.offset),
        spi_speed_hz=SPI_SPEED_HZ,
    )
    return display


def draw_pattern(display: st7789.ST7789) -> None:
    """Display a simple series of colour bars with some text."""

    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    colours = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (0, 255, 255),
    ]
    bar_h = HEIGHT // len(colours)
    for i, colour in enumerate(colours):
        draw.rectangle((0, i * bar_h, WIDTH, (i + 1) * bar_h), fill=colour)

    font = ImageFont.load_default()
    draw.text((10, 10), "Touch the screen", fill=(0, 0, 0), font=font)

    display.display(img)


# ---------------------------------------------------------------------------
# Touch handling
# ---------------------------------------------------------------------------


class TouchPanel:
    """Minimal XPT2046 touch panel reader."""

    def __init__(self) -> None:
        self.cs = request_output(TP_CS, "tp-cs")
        self.irq = request_input(TP_IRQ, "tp-irq")

        self.spi = spidev.SpiDev()
        self.spi.open(SPI_BUS, SPI_DEVICE)
        self.spi.max_speed_hz = 2_000_000

    def _read_channel(self, command: int) -> int:
        """Read a 12-bit value from the touch controller."""

        resp = self.spi.xfer2([command, 0x00, 0x00])
        return ((resp[1] << 8) | resp[2]) >> 4

    def read(self) -> tuple[int, int] | None:
        """Return (x, y) when the panel is pressed, otherwise ``None``."""

        if self.irq.request.get_value(self.irq.offset):
            return None

        self.cs.request.set_value(self.cs.offset, 0)
        x = self._read_channel(0xD0)  # X position
        y = self._read_channel(0x90)  # Y position
        self.cs.request.set_value(self.cs.offset, 1)
        return x, y

    def close(self) -> None:
        self.spi.close()


# ---------------------------------------------------------------------------
# Main program
# ---------------------------------------------------------------------------


def main() -> None:
    display = init_display()
    draw_pattern(display)
    touch = TouchPanel()

    def handle_sigint(signum, frame):  # type: ignore[override]
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handle_sigint)

    print("Touch the panel to see coordinates (Ctrl+C to exit)")
    try:
        while True:
            pos = touch.read()
            if pos is not None:
                # Convert raw 12-bit coordinates to screen space
                x = WIDTH - pos[0] * WIDTH // 4095
                y = pos[1] * HEIGHT // 4095
                print(f"Touch at x={x:3d}, y={y:3d}")
                time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        touch.close()
        display.set_backlight(False)
        display._spi.close()


if __name__ == "__main__":
    main()

