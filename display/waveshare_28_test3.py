#!/usr/bin/env python3
"""
Waveshare 2.8" Resistive Touch LCD (ILI9341 + XPT2046) quick test
Target: Luckfox Pico Ultra W, libgpiod v2-compatible

Wiring (your map):
  LCD_CS  -> GPIO1_C0_d  (offset 48)
  LCD_DC  -> GPIO2_A7_d  (71)
  LCD_RST -> GPIO1_D3_d  (59)
  LCD_BL  -> GPIO2_A6_d  (70)
  TP_CS   -> GPIO1_B2_d  (42)
  TP_IRQ  -> GPIO1_B3_u  (43)
  SPI0_MOSI / SPI0_CLK wired to display

Deps:
  pip install spidev gpiod pillow
"""

import os, time, struct
import spidev
import gpiod

# ---------------- CONFIG ----------------
SPI_LCD_DEV = "/dev/spidev0.0"
USE_HW_CS   = True          # kernel didn’t like no_cs; leave hardware CS on
GPIOCHIP    = "/dev/gpiochip0"

LCD_DC   = 71
LCD_RST  = 59
LCD_BL   = 70
LCD_CS   = 48               # still used as a GPIO CS; HW CS will also toggle (harmless)

# Touch (XPT2046)
ENABLE_TOUCH   = True
SPI_TOUCH_DEV  = SPI_LCD_DEV
TOUCH_CS       = 42
TOUCH_IRQ      = 43

SPI_LCD_SPEED_HZ   = 1_000_000   # your kernel cap
SPI_TOUCH_SPEED_HZ = 2_000_000

LCD_WIDTH, LCD_HEIGHT = 320, 240
# ----------------------------------------


# ---------- libgpiod helpers (v2 + v1 fallback) ----------
HAS_V2 = hasattr(gpiod, "request_lines")

if HAS_V2:
    # v2 API
    def _req_out(chip_path, offset, consumer, default=0):
        if offset is None: return None
        cfg = {offset: gpiod.LineSettings(direction=gpiod.LineDirection.OUTPUT,
                                          output_value=int(bool(default)))}
        return gpiod.request_lines(chip_path, consumer=consumer, config=cfg)

    def _req_in(chip_path, offset, consumer):
        if offset is None: return None
        cfg = {offset: gpiod.LineSettings(direction=gpiod.LineDirection.INPUT)}
        return gpiod.request_lines(chip_path, consumer=consumer, config=cfg)

    def _set(req, offset, val):
        if req is not None:
            req.set_values({offset: int(bool(val))})

    def _get(req, offset):
        if req is None: return None
        return req.get_values([offset])[offset]

    def _rel(req):
        if req is not None:
            req.release()

else:
    # v1 API
    def _req_out(chip_path, offset, consumer, default=0):
        if offset is None: return None
        chip = gpiod.Chip(chip_path, gpiod.Chip.OPEN_BY_PATH)
        line = chip.get_line(offset)
        line.request(consumer=consumer, type=gpiod.LINE_REQ_DIR_OUT, default_val=int(bool(default)))
        line._chip = chip
        return line

    def _req_in(chip_path, offset, consumer):
        if offset is None: return None
        chip = gpiod.Chip(chip_path, gpiod.Chip.OPEN_BY_PATH)
        line = chip.get_line(offset)
        line.request(consumer=consumer, type=gpiod.LINE_REQ_DIR_IN)
        line._chip = chip
        return line

    def _set(req, offset, val):
        if req is not None:
            req.set_value(int(bool(val)))

    def _get(req, offset):
        if req is None: return None
        return req.get_value()

    def _rel(req):
        if req is not None:
            try: req.set_value(0)
            except Exception: pass
            req.release()
            if hasattr(req, "_chip"):
                req._chip.close()


class GPIOOut:
    def __init__(self, chip, offset, name, default=0):
        self.offset = offset
        self.req = _req_out(chip, offset, name, default)
    def set(self, v): _set(self.req, self.offset, v)
    def __enter__(self): return self
    def __exit__(self, *a): _rel(self.req)

class GPIOIn:
    def __init__(self, chip, offset, name):
        self.offset = offset
        self.req = _req_in(chip, offset, name)
    def get(self): return _get(self.req, self.offset)
    def __enter__(self): return self
    def __exit__(self, *a): _rel(self.req)
# ----------------------------------------------------------


def open_spidev(node, speed, mode=0):
    bus, dev = map(int, os.path.basename(node)[6:].split("."))
    spi = spidev.SpiDev()
    spi.open(bus, dev)
    spi.mode = mode
    spi.max_speed_hz = speed
    spi.bits_per_word = 8
    spi.cshigh = False
    spi.no_cs = False          # IMPORTANT: your kernel errored on no_cs
    return spi


class ILI9341:
    def __init__(self, spi, dc, rst, cs, bl):
        self.spi, self.dc, self.rst, self.cs, self.bl = spi, dc, rst, cs, bl

    def _cmd(self, c):
        if self.cs.req: self.cs.set(0)
        self.dc.set(0)
        self.spi.xfer2([c & 0xFF])
        if self.cs.req: self.cs.set(1)

    def _data(self, d: bytes):
        if self.cs.req: self.cs.set(0)
        self.dc.set(1)
        for i in range(0, len(d), 4096):
            self.spi.xfer2(list(d[i:i+4096]))
        if self.cs.req: self.cs.set(1)

    def reset(self):
        if not self.rst.req: return
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
    with GPIOOut(GPIOCHIP, TOUCH_CS, "tp-cs", 1) as cs, GPIOIn(GPIOCHIP, TOUCH_IRQ, "tp-irq") as irq:
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
    # SPI
    spi = open_spidev(SPI_LCD_DEV, SPI_LCD_SPEED_HZ, mode=0)

    # GPIO control lines
    with GPIOOut(GPIOCHIP, LCD_DC,  "lcd-dc") as dc, \
         GPIOOut(GPIOCHIP, LCD_RST, "lcd-rst") as rst, \
         GPIOOut(GPIOCHIP, LCD_BL,  "lcd-bl") as bl, \
         GPIOOut(GPIOCHIP, LCD_CS,  "lcd-cs", 1) as cs:

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
