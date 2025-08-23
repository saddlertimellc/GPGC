#!/usr/bin/env python3
"""
Waveshare 2.8" Resistive Touch LCD (ILI9341 + XPT2046) quick test
Target: Luckfox Pico Ultra W, libgpiod v2

Your wiring (offsets from your table):
  LCD_CS  -> 48
  LCD_DC  -> 71
  LCD_RST -> 59
  LCD_BL  -> 70
  TP_CS   -> 42
  TP_IRQ  -> 43
SPI: /dev/spidev0.0 at 1 MHz (kernel cap)
"""

import os, glob, time
import spidev
import gpiod

# ---------------- CONFIG ----------------
SPI_LCD_DEV = "/dev/spidev0.0"
SPI_LCD_SPEED_HZ = 1_000_000  # your kernel cap
SPI_TOUCH_SPEED_HZ = 2_000_000
USE_HW_CS = True              # keep kernel CS enabled; we'll also toggle our own GPIO CS

LCD_WIDTH, LCD_HEIGHT = 320, 240

# Offsets only (we’ll auto-pick the right gpiochip for each)
LCD_DC_OFF   = 71
LCD_RST_OFF  = 59
LCD_BL_OFF   = 70
LCD_CS_OFF   = 48
TOUCH_CS_OFF = 42
TOUCH_IRQ_OFF= 43

ENABLE_TOUCH = True
SPI_TOUCH_DEV = SPI_LCD_DEV
# ----------------------------------------


# ---------- libgpiod v2 helpers with auto-probe ----------
def _all_chips():
    # Return list of chip paths sorted by name
    chips = sorted(glob.glob("/dev/gpiochip*"))
    if not chips:
        raise RuntimeError("No /dev/gpiochip* found")
    return chips

def _try_request_out(chip_path, offset, consumer, default=0):
    cfg = {offset: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT,
                                      output_value=int(bool(default)))}
    try:
        req = gpiod.request_lines(chip_path, consumer=consumer, config=cfg)
        return req
    except ValueError:
        # offset out of range for this chip
        return None

def _try_request_in(chip_path, offset, consumer):
    cfg = {offset: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT)}
    try:
        req = gpiod.request_lines(chip_path, consumer=consumer, config=cfg)
        return req
    except ValueError:
        return None

def _acquire_out(offset, name, default=0):
    for chip in _all_chips():
        req = _try_request_out(chip, offset, name, default)
        if req is not None:
            return chip, req
    raise ValueError(f"GPIO offset {offset} not found on any gpiochip")

def _acquire_in(offset, name):
    for chip in _all_chips():
        req = _try_request_in(chip, offset, name)
        if req is not None:
            return chip, req
    raise ValueError(f"GPIO offset {offset} not found on any gpiochip")

def _set(req, offset, val):
    req.set_values({offset: int(bool(val))})

def _get(req, offset):
    return req.get_values([offset])[offset]
# ---------------------------------------------------------


class GPIOOut:
    def __init__(self, offset, name, default=0):
        self.offset = offset
        self.chip, self.req = _acquire_out(offset, name, default)
    def set(self, v): _set(self.req, self.offset, v)
    def __enter__(self): return self
    def __exit__(self, *a): self.req.release()

class GPIOIn:
    def __init__(self, offset, name):
        self.offset = offset
        self.chip, self.req = _acquire_in(offset, name)
    def get(self): return _get(self.req, self.offset)
    def __enter__(self): return self
    def __exit__(self, *a): self.req.release()


def open_spidev(node, speed, mode=0):
    bus, dev = map(int, os.path.basename(node)[6:].split("."))
    spi = spidev.SpiDev(); spi.open(bus, dev)
    spi.mode = mode
    spi.max_speed_hz = speed
    spi.bits_per_word = 8
    spi.cshigh = False
    spi.no_cs = False      # IMPORTANT: your kernel errored on no_cs
    return spi


class ILI9341:
    def __init__(self, spi, dc: GPIOOut, rst: GPIOOut, cs: GPIOOut, bl: GPIOOut):
        self.spi, self.dc, self.rst, self.cs, self.bl = spi, dc, rst, cs, bl

    def _cmd(self, c):
        self.cs.set(0)
        self.dc.set(0)
        self.spi.xfer2([c & 0xFF])
        self.cs.set(1)

    def _data(self, data: bytes):
        self.cs.set(0)
        self.dc.set(1)
        for i in range(0, len(data), 4096):
            self.spi.xfer2(list(data[i:i+4096]))
        self.cs.set(1)

    def reset(self):
        self.rst.set(0); time.sleep(0.05)
        self.rst.set(1); time.sleep(0.12)

    def init(self):
        self.reset()
        self._cmd(0x11); time.sleep(0.12)     # Sleep out
        self._cmd(0x3A); self._data(bytes([0x55]))   # 16 bpp
        self._cmd(0x36); self._data(bytes([0x48]))   # MADCTL (BGR + row/col exchange)
        self._cmd(0x29); time.sleep(0.02)     # Display on
        self.bl.set(1)

    def window(self,x0,y0,x1,y1):
        self._cmd(0x2A); self._data(bytes([x0>>8,x0&0xFF,x1>>8,x1&0xFF]))
        self._cmd(0x2B); self._data(bytes([y0>>8,y0&0xFF,y1>>8,y1&0xFF]))
        self._cmd(0x2C)

    def fill(self,color):
        self.window(0,0,LCD_WIDTH-1,LCD_HEIGHT-1)
        buf = color.to_bytes(2,'big')*2048
        px = LCD_WIDTH*LCD_HEIGHT
        while px>0:
            n=min(px,2048)
            self._data(buf[:n*2]); px-=n

    def rect(self,x,y,w,h,color):
        if w<=0 or h<=0: return
        x1=min(x+w-1, LCD_WIDTH-1); y1=min(y+h-1, LCD_HEIGHT-1)
        if x1<x or y1<y: return
        self.window(x,y,x1,y1)
        self._data(color.to_bytes(2,'big')*(w*h))

    @staticmethod
    def rgb565(r,g,b): return ((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)


def touch_loop():
    bus, dev = map(int, os.path.basename(SPI_TOUCH_DEV)[6:].split("."))
    spi = spidev.SpiDev(); spi.open(bus, dev)
    spi.mode = 0; spi.max_speed_hz = SPI_TOUCH_SPEED_HZ
    with GPIOOut(TOUCH_CS_OFF, "tp-cs", 1) as cs, GPIOIn(TOUCH_IRQ_OFF, "tp-irq") as irq:
        print("Touch test: press screen 10s")
        end = time.time()+10
        while time.time() < end:
            val = irq.get()
            if val == 0 or val is None:  # active-low or polling
                def read12(cmd):
                    cs.set(0)
                    r = spi.xfer2([cmd,0,0])
                    cs.set(1)
                    return ((r[1]<<8)|r[2])>>3
                y = read12(0x90); x = read12(0xD0)
                print(f"Touch raw x={x} y={y}")
                time.sleep(0.1)
            else:
                time.sleep(0.02)


def main():
    spi = open_spidev(SPI_LCD_DEV, SPI_LCD_SPEED_HZ, mode=0)

    with GPIOOut(LCD_DC_OFF,  "lcd-dc") as dc, \
         GPIOOut(LCD_RST_OFF, "lcd-rst") as rst, \
         GPIOOut(LCD_BL_OFF,  "lcd-bl") as bl, \
         GPIOOut(LCD_CS_OFF,  "lcd-cs", 1) as cs:

        lcd = ILI9341(spi, dc, rst, cs, bl)
        lcd.init()

        # Solid fills
        for c in [(255,0,0),(0,255,0),(0,0,255),(255,255,255),(0,0,0)]:
            lcd.fill(ILI9341.rgb565(*c)); time.sleep(0.4)

        # Gradient bars
        for y in range(0, LCD_HEIGHT, 8):
            r = int(255*y/LCD_HEIGHT); b = 255 - r
            lcd.rect(0,y,LCD_WIDTH,8, ILI9341.rgb565(r,128,b))
        time.sleep(0.6)

        # Bouncing box
        lcd.fill(ILI9341.rgb565(0,0,0))
        color = ILI9341.rgb565(255,255,0); bg = ILI9341.rgb565(0,0,0)
        x=y=10; dx=4; dy=3; sz=30; t0=time.time()
        while time.time()-t0 < 8:
            lcd.rect(x,y,sz,sz,color); time.sleep(0.02)
            lcd.rect(x,y,sz,sz,bg)
            x+=dx; y+=dy
            if x<0 or x+sz>=LCD_WIDTH: dx=-dx; x+=dx
            if y<0 or y+sz>=LCD_HEIGHT: dy=-dy; y+=dy

    if ENABLE_TOUCH:
        touch_loop()

    print("Done.")


if __name__=="__main__":
    main()
