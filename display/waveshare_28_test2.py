#!/usr/bin/env python3
"""
Waveshare 2.8" Resistive Touch LCD (ILI9341 + XPT2046) quick test
Target: Luckfox Pico Ultra W, libgpiod v2 Python API

Wiring (from your table):
  LCD_CS  -> GPIO1_C0_d  (offset 48)
  LCD_DC  -> GPIO2_A7_d  (71)
  LCD_RST -> GPIO1_D3_d  (59)
  LCD_BL  -> GPIO2_A6_d  (70)
  TP_CS   -> GPIO1_B2_d  (42)
  TP_IRQ  -> GPIO1_B3_u  (43)
  SPI0_*  -> display SCLK/MOSI (MISO optional for LCD; required for touch)

Requires:
  pip install spidev gpiod pillow   # gpiod must be libgpiod v2 bindings
"""

import os, time, struct
from typing import Optional, Dict

import spidev
import gpiod  # libgpiod v2 API

# ---------------- CONFIG ----------------
SPI_LCD_DEV = "/dev/spidev0.0"
SPI_LCD_SPEED_HZ = 1_000_000     # match your kernel cap
USE_HW_CS = True                 # avoid spi.no_cs ioctl (kernel didn’t like it)

GPIOCHIP = "/dev/gpiochip0"

LCD_DC  = 71
LCD_RST = 59
LCD_BL  = 70
LCD_CS  = 48

# Touch (XPT2046)
ENABLE_TOUCH = True
SPI_TOUCH_DEV = SPI_LCD_DEV
SPI_TOUCH_SPEED_HZ = 2_000_000
TOUCH_CS  = 42
TOUCH_IRQ = 43

LCD_WIDTH, LCD_HEIGHT = 320, 240
# ---------------------------------------


# ---------- gpiod v2 helpers ----------
class LineOut:
    def __init__(self, chip_path: str, offsets: Dict[int, int], consumer: str):
        """
        offsets: {offset: initial_value}
        """
        self.path = chip_path
        self.offsets = offsets
        self.consumer = consumer
        self.lines = None

    def __enter__(self):
        cfg = {}
        for off, init in self.offsets.items():
            ls = gpiod.LineSettings()
            ls.direction = gpiod.LineDirection.OUTPUT
            ls.output_value = gpiod.LineValue.ACTIVE if init else gpiod.LineValue.INACTIVE
            cfg[off] = ls
        self.lines = gpiod.request_lines(
            self.path,
            consumer=self.consumer,
            config=cfg
        )
        return self

    def set(self, off: int, val: int):
        if self.lines is None: return
        self.lines.set_value(off, gpiod.LineValue.ACTIVE if val else gpiod.LineValue.INACTIVE)

    def __exit__(self, exc_type, exc, tb):
        if self.lines:
            # Optionally drive safe values before release:
            for off in self.offsets:
                try:
                    self.lines.set_value(off, gpiod.LineValue.INACTIVE)
                except Exception:
                    pass
            self.lines.release()


class LineIn:
    def __init__(self, chip_path: str, offset: Optional[int], consumer: str):
        self.path = chip_path
        self.offset = offset
        self.consumer = consumer
        self.lines = None

    def __enter__(self):
        if self.offset is None:
            return self
        ls = gpiod.LineSettings()
        ls.direction = gpiod.LineDirection.INPUT
        self.lines = gpiod.request_lines(
            self.path,
            consumer=self.consumer,
            config={self.offset: ls}
        )
        return self

    def get(self) -> Optional[int]:
        if self.lines is None:
            return None
        val = self.lines.get_value(self.offset)
        return 1 if val == gpiod.LineValue.ACTIVE else 0

    def __exit__(self, exc_type, exc, tb):
        if self.lines:
            self.lines.release()
# --------------------------------------


def open_spidev(node: str, speed_hz: int, mode: int = 0) -> spidev.SpiDev:
    bus, dev = map(int, os.path.basename(node)[6:].split("."))
    spi = spidev.SpiDev()
    spi.open(bus, dev)
    spi.mode = mode
    spi.max_speed_hz = speed_hz
    spi.bits_per_word = 8
    # Keep hardware CS enabled (even if not wired) to avoid no_cs ioctl
    spi.cshigh = False
    spi.no_cs = False
    return spi


class ILI9341:
    def __init__(self, spi: spidev.SpiDev, gpio: LineOut):
        self.spi = spi
        self.gpio = gpio  # manages LCD_DC, LCD_RST, LCD_BL, LCD_CS

    def _cs(self, level: int):   self.gpio.set(LCD_CS, level)
    def _dc(self, level: int):   self.gpio.set(LCD_DC, level)
    def _rst(self, level: int):  self.gpio.set(LCD_RST, level)
    def _bl(self, level: int):   self.gpio.set(LCD_BL, level)

    def _cmd(self, c: int):
        self._cs(0); self._dc(0)
        self.spi.xfer2([c & 0xFF])
        self._cs(1)

    def _data(self, d: bytes):
        self._cs(0); self._dc(1)
        for i in range(0, len(d), 4096):
            self.spi.xfer2(list(d[i:i+4096]))
        self._cs(1)

    def reset(self):
        if LCD_RST is None: return
        self._rst(0); time.sleep(0.05)
        self._rst(1); time.sleep(0.12)

    def init(self):
        self.reset()
        self._cmd(0x11); time.sleep(0.12)        # Sleep out
        self._cmd(0x3A); self._data(bytes([0x55]))  # 16bpp
        self._cmd(0x36); self._data(bytes([0x48]))  # MADCTL (BGR + row/col)
        self._cmd(0x29); time.sleep(0.02)        # Display on
        if LCD_BL is not None:
            self._bl(1)

    def window(self, x0, y0, x1, y1):
        self._cmd(0x2A); self._data(bytes([x0>>8, x0&0xFF, x1>>8, x1&0xFF]))
        self._cmd(0x2B); self._data(bytes([y0>>8, y0&0xFF, y1>>8, y1&0xFF]))
        self._cmd(0x2C)

    def fill(self, color565: int):
        self.window(0,0,LCD_WIDTH-1,LCD_HEIGHT-1)
        chunk = color565.to_bytes(2,'big') * 2048
        remain = LCD_WIDTH * LCD_HEIGHT
        while remain > 0:
            n = min(remain, 2048)
            self._data(chunk[:n*2]); remain -= n

    def rect(self, x, y, w, h, color565: int):
        if w <= 0 or h <= 0: return
        x1 = min(x+w-1, LCD_WIDTH-1); y1 = min(y+h-1, LCD_HEIGHT-1)
        if x1 < x or y1 < y: return
        self.window(x, y, x1, y1)
        self._data(color565.to_bytes(2,'big') * (w*h))

    @staticmethod
    def rgb565(r,g,b): return ((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)


def touch_loop():
    # Minimal XPT2046 raw read on shared SPI bus
    bus, dev = map(int, os.path.basename(SPI_TOUCH_DEV)[6:].split("."))
    tspi = spidev.SpiDev(); tspi.open(bus, dev)
    tspi.mode = 0; tspi.max_speed_hz = SPI_TOUCH_SPEED_HZ
    with LineOut(GPIOCHIP, {TOUCH_CS: 1}, "tp-cs") as tpcs, \
         LineIn(GPIOCHIP, TOUCH_IRQ, "tp-irq") as tpi:
        print("Touch test: press screen for 10s…")
        end = time.time() + 10
        while time.time() < end:
            irqv = tpi.get()
            if irqv == 0 or irqv is None:
                def read12(cmd):
                    tpcs.set(TOUCH_CS, 0)
                    r = tspi.xfer2([cmd, 0x00, 0x00])
                    tpcs.set(TOUCH_CS, 1)
                    return ((r[1] << 8) | r[2]) >> 3
                y = read12(0x90); x = read12(0xD0)
                print(f"Touch raw x={x} y={y}")
                time.sleep(0.1)
            else:
                time.sleep(0.02)


def main():
    # SPI open
    spi = open_spidev(SPI_LCD_DEV, SPI_LCD_SPEED_HZ, mode=0)

    # GPIO request (drive all low initially; CS idle high)
    initial = {}
    if LCD_DC  is not None: initial[LCD_DC]  = 0
    if LCD_RST is not None: initial[LCD_RST] = 1  # keep out of reset
    if LCD_BL  is not None: initial[LCD_BL]  = 0
    if LCD_CS  is not None: initial[LCD_CS]  = 1  # idle high

    with LineOut(GPIOCHIP, initial, "lcd-ctrl") as gp:
        lcd = ILI9341(spi, gp)
        lcd.init()

        # Solid fills
        for c in [(255,0,0),(0,255,0),(0,0,255),(255,255,255),(0,0,0)]:
            lcd.fill(ILI9341.rgb565(*c)); time.sleep(0.4)

        # Gradient bars
        for y in range(0, LCD_HEIGHT, 8):
            r = int(255 * y / LCD_HEIGHT)
            b = 255 - r
            lcd.rect(0, y, LCD_WIDTH, 8, ILI9341.rgb565(r, 128, b))
        time.sleep(0.6)

        # Bouncing box
        lcd.fill(ILI9341.rgb565(0,0,0))
        color = ILI9341.rgb565(255,255,0); bg = ILI9341.rgb565(0,0,0)
        x = y = 10; dx = 4; dy = 3; sz = 30; t0 = time.time()
        while time.time() - t0 < 8:
            lcd.rect(x,y,sz,sz,color); time.sleep(0.02)
            lcd.rect(x,y,sz,sz,bg)
            x += dx; y += dy
            if x < 0 or x+sz >= LCD_WIDTH:  dx = -dx; x += dx
            if y < 0 or y+sz >= LCD_HEIGHT: dy = -dy; y += dy

    if ENABLE_TOUCH:
        touch_loop()

    print("Done.")


if __name__ == "__main__":
    main()
