#!/usr/bin/env python3
"""
Waveshare 2.8" Resistive Touch LCD (SPI) quick test
Target: Luckfox Pico Ultra W (Linux), Python 3.10+
Display IC: ILI9341 (320x240). Touch IC: XPT2046 (optional).

Requirements:
  pip install spidev gpiod pillow

Wiring expectations:
  - SPI bus connected to LCD (SCLK, MOSI, MISO [optional], and a CS line).
  - Separate GPIO lines for LCD DC (data/command), LCD RST, optional BL (backlight).
  - Touch (XPT2046) shares SPI but uses its own CS and an IRQ line to signal touch.

Edit the CONFIG section below to match your gpiochip and line offsets.
Find line offsets: `gpiodetect` and `gpioinfo` (from libgpiod).

Run:
  python3 waveshare_28_test.py

Exit:
  Ctrl+C
"""
import os
import time
import struct
from typing import Tuple, Optional

import spidev
import gpiod
from PIL import Image

# ---------------------------- CONFIG ----------------------------
# SPI device node for the LCD. Likely one of: /dev/spidev0.0, /dev/spidev1.0, etc.
SPI_LCD_DEV = "/dev/spidev0.0"     # <-- ADJUST if needed

# If your LCD CS is wired to the same CS as this spidev node, set USE_HW_CS=True.
# If you wired CS to an arbitrary GPIO, set USE_HW_CS=False and provide LCD_CS below.
USE_HW_CS = True

# GPIO chip and line offsets for control pins (use `gpioinfo` to discover offsets).
GPIOCHIP = "/dev/gpiochip0"        # <-- ADJUST

LCD_DC   = 0    # <-- ADJUST: line offset for LCD D/C
LCD_RST  = 0    # <-- ADJUST: line offset for LCD RESET (or None if tied to board reset)
LCD_BL   = None # <-- optional backlight line offset; set to an int if controlled by GPIO

# If using software CS (USE_HW_CS=False), provide the GPIO line offset here:
LCD_CS   = None # <-- set to int offset if you need software CS

# --- Touch (optional) ---
ENABLE_TOUCH = False
SPI_TOUCH_DEV = SPI_LCD_DEV        # typically same SPI bus
TOUCH_CS  = None                   # XPT2046 CS (int offset) if using software CS
TOUCH_IRQ = None                   # XPT2046 IRQ (int offset); if provided we can poll it efficiently

# SPI speeds (Hz)
SPI_LCD_SPEED_HZ = 48_000_000      # ILI9341 can typically do 40-50 MHz on short wires
SPI_TOUCH_SPEED_HZ = 2_000_000     # XPT2046 works fine at 2MHz

# Display geometry
LCD_WIDTH  = 320
LCD_HEIGHT = 240
# ------------------------- END CONFIG --------------------------


def open_spidev(node: str, max_speed_hz: int, mode: int = 0, bits_per_word: int = 8) -> spidev.SpiDev:
    # node like "/dev/spidev0.0" => bus=0, cs=0
    base = os.path.basename(node)
    assert base.startswith("spidev"), f"Bad SPI node: {node}"
    bus, dev = map(int, base[len("spidev"):].split("."))
    spi = spidev.SpiDev()
    spi.open(bus, dev)
    spi.mode = mode
    spi.max_speed_hz = max_speed_hz
    spi.bits_per_word = bits_per_word
    spi.cshigh = False
    spi.no_cs = not USE_HW_CS
    return spi


class GPIOOut:
    def __init__(self, chip_path: str, line_offset: int, name: str):
        self.chip_path = chip_path
        self.line_offset = line_offset
        self.name = name
        self.line = None

    def __enter__(self):
        if self.line_offset is None:
            return self
        chip = gpiod.Chip(self.chip_path, gpiod.Chip.OPEN_BY_PATH)
        self.line = chip.get_line(self.line_offset)
        self.line.request(consumer=self.name, type=gpiod.LINE_REQ_DIR_OUT, default_val=0)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.line is not None:
            self.line.set_value(0)
            self.line.release()

    def set(self, val: int):
        if self.line is not None:
            self.line.set_value(1 if val else 0)


class GPIOIn:
    def __init__(self, chip_path: str, line_offset: Optional[int], name: str):
        self.chip_path = chip_path
        self.line_offset = line_offset
        self.name = name
        self.line = None

    def __enter__(self):
        if self.line_offset is None:
            return self
        chip = gpiod.Chip(self.chip_path, gpiod.Chip.OPEN_BY_PATH)
        self.line = chip.get_line(self.line_offset)
        self.line.request(consumer=self.name, type=gpiod.LINE_REQ_DIR_IN)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.line is not None:
            self.line.release()

    def get(self) -> Optional[int]:
        if self.line is None:
            return None
        return self.line.get_value()


class ILI9341:
    def __init__(self, spi: spidev.SpiDev, dc: GPIOOut, rst: GPIOOut, cs: GPIOOut, bl: GPIOOut):
        self.spi = spi
        self.dc = dc
        self.rst = rst
        self.cs = cs
        self.bl = bl

    def _write_cmd(self, cmd: int):
        if self.cs.line is not None:
            self.cs.set(0)
        self.dc.set(0)
        self.spi.xfer2([cmd & 0xFF])
        if self.cs.line is not None:
            self.cs.set(1)

    def _write_data(self, data: bytes):
        if self.cs.line is not None:
            self.cs.set(0)
        self.dc.set(1)
        # chunk to avoid large transfers on slow drivers
        for i in range(0, len(data), 4096):
            self.spi.xfer2(list(data[i:i+4096]))
        if self.cs.line is not None:
            self.cs.set(1)

    def reset(self):
        if self.rst.line is None:
            return
        self.rst.set(0); time.sleep(0.05)
        self.rst.set(1); time.sleep(0.12)

    def init(self):
        # Basic init sequence for ILI9341 320x240
        self.reset()
        # Exit sleep
        self._write_cmd(0x11); time.sleep(0.12)

        # Pixel format = 16bpp
        self._write_cmd(0x3A)
        self._write_data(bytes([0x55]))  # 16-bit/pixel

        # Memory access control (MADCTL) - set orientation (MX, MY, MV)
        # 0x48 => row/col exchange + BGR, adjust as needed
        self._write_cmd(0x36)
        self._write_data(bytes([0x48]))

        # Porch control / frame rate (optional defaults okay for a quick test)

        # Display on
        self._write_cmd(0x29); time.sleep(0.02)

        # Turn on backlight if available
        self.bl.set(1)

    def set_window(self, x0: int, y0: int, x1: int, y1: int):
        # Column addr set
        self._write_cmd(0x2A)
        self._write_data(struct.pack(">HH", x0, x1))
        # Row addr set
        self._write_cmd(0x2B)
        self._write_data(struct.pack(">HH", y0, y1))
        # RAM write
        self._write_cmd(0x2C)

    def fill_color(self, color565: int):
        # Fill entire screen
        self.set_window(0, 0, LCD_WIDTH - 1, LCD_HEIGHT - 1)
        # Prepare a chunk of pixels
        chunk = struct.pack(">H", color565) * 2048
        pixels = LCD_WIDTH * LCD_HEIGHT
        while pixels > 0:
            n = min(pixels, 2048)
            self._write_data(chunk[:n*2])
            pixels -= n

    def draw_rect(self, x: int, y: int, w: int, h: int, color565: int):
        if x < 0 or y < 0:
            return
        x1 = min(x + w - 1, LCD_WIDTH - 1)
        y1 = min(y + h - 1, LCD_HEIGHT - 1)
        if x1 < x or y1 < y:
            return
        self.set_window(x, y, x1, y1)
        chunk = struct.pack(">H", color565) * (w*h)
        self._write_data(chunk)

    @staticmethod
    def rgb_to_565(r: int, g: int, b: int) -> int:
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def main():
    # SPI
    lcd_spi = open_spidev(SPI_LCD_DEV, SPI_LCD_SPEED_HZ, mode=0)

    # Control GPIOs
    with GPIOOut(GPIOCHIP, LCD_DC,  "lcd-dc") as dc, \
         GPIOOut(GPIOCHIP, LCD_RST, "lcd-rst") as rst, \
         GPIOOut(GPIOCHIP, LCD_BL,  "lcd-bl") as bl, \
         GPIOOut(GPIOCHIP, LCD_CS,  "lcd-cs") as cs:

        lcd = ILI9341(lcd_spi, dc, rst, cs, bl)
        lcd.init()

        # Test 1: solid color fills
        colors = [
            ILI9341.rgb_to_565(255, 0, 0),   # red
            ILI9341.rgb_to_565(0, 255, 0),   # green
            ILI9341.rgb_to_565(0, 0, 255),   # blue
            ILI9341.rgb_to_565(255, 255, 255), # white
            ILI9341.rgb_to_565(0, 0, 0)      # black
        ]
        for c in colors:
            lcd.fill_color(c); time.sleep(0.5)

        # Test 2: gradient
        for y in range(0, LCD_HEIGHT, 8):
            r = int(255 * y / LCD_HEIGHT)
            g = 128
            b = 255 - r
            lcd.draw_rect(0, y, LCD_WIDTH, 8, ILI9341.rgb_to_565(r, g, b))

        time.sleep(0.75)

        # Test 3: moving square
        sq = 30
        color = ILI9341.rgb_to_565(255, 255, 0)
        bg    = ILI9341.rgb_to_565(0, 0, 0)
        lcd.fill_color(bg)
        x, y, dx, dy = 10, 10, 4, 3
        t0 = time.time()
        while time.time() - t0 < 8:
            lcd.draw_rect(x, y, sq, sq, color)
            time.sleep(0.02)
            lcd.draw_rect(x, y, sq, sq, bg)
            x += dx; y += dy
            if x < 0 or x+sq >= LCD_WIDTH:  dx = -dx; x += dx
            if y < 0 or y+sq >= LCD_HEIGHT: dy = -dy; y += dy

        # Leave a final screen
        lcd.fill_color(ILI9341.rgb_to_565(0, 0, 0))

    # Optional: touch sanity (XPT2046). Only runs if ENABLE_TOUCH and CS defined.
    if ENABLE_TOUCH and TOUCH_CS is not None:
        with open_spidev(SPI_TOUCH_DEV, SPI_TOUCH_SPEED_HZ, mode=0) as tspi, \
             GPIOOut(GPIOCHIP, TOUCH_CS, "tp-cs") as tpcs, \
             GPIOIn(GPIOCHIP, TOUCH_IRQ, "tp-irq") as tpirq:

            print("Touch test: press the screen (10s window).")
            end = time.time() + 10
            while time.time() < end:
                irq = tpirq.get()
                if irq == 0 or irq is None:  # active-low IRQ, or poll anyway if no IRQ
                    # XPT2046: read X and Y with command bytes 0x90 (Y) and 0xD0 (X)
                    def read12(cmd):
                        tpcs.set(0)
                        resp = tspi.xfer2([cmd, 0x00, 0x00])
                        tpcs.set(1)
                        # 12-bit value: combine last two bytes
                        return ((resp[1] << 8) | resp[2]) >> 3
                    y_raw = read12(0x90)
                    x_raw = read12(0xD0)
                    print(f"Touch raw: x={x_raw} y={y_raw}")
                    time.sleep(0.1)
                else:
                    time.sleep(0.02)

    print("Done.")
    

if __name__ == "__main__":
    main()
