#!/usr/bin/env python3
"""
Waveshare 2.8" Resistive Touch LCD (ILI9341 + XPT2046) quick test
Target: Luckfox Pico Ultra W

Your wiring:
  LCD_CS  -> GPIO1_C0_d  (offset 48)
  LCD_DC  -> GPIO2_A7_d  (71)
  LCD_RST -> GPIO1_D3_d  (59)
  LCD_BL  -> GPIO2_A6_d  (70)
  TP_CS   -> GPIO1_B2_d  (42)
  TP_IRQ  -> GPIO1_B3_u  (43)
  SPI0_MOSI / SPI0_CLK wired to display
"""

import os, time, struct
import spidev, gpiod

# ---------------- CONFIG ----------------
SPI_LCD_DEV = "/dev/spidev0.0"
USE_HW_CS   = False     # using GPIO CS

GPIOCHIP = "/dev/gpiochip0"

LCD_DC   = 71
LCD_RST  = 59
LCD_BL   = 70
LCD_CS   = 48

# Touch
ENABLE_TOUCH = True
SPI_TOUCH_DEV = SPI_LCD_DEV
TOUCH_CS  = 42
TOUCH_IRQ = 43

SPI_LCD_SPEED_HZ   = 24_000_000
SPI_TOUCH_SPEED_HZ = 2_000_000

LCD_WIDTH, LCD_HEIGHT = 320, 240
# ----------------------------------------


def open_spidev(node, speed, mode=0):
    bus, dev = map(int, os.path.basename(node)[6:].split("."))
    spi = spidev.SpiDev()
    spi.open(bus, dev)
    spi.mode, spi.max_speed_hz, spi.bits_per_word = mode, speed, 8
    spi.cshigh, spi.no_cs = False, not USE_HW_CS
    return spi


class GPIOOut:
    def __init__(self, chip, offset, name):
        self.offset, self.name = offset, name
        self.line = None if offset is None else gpiod.Chip(chip).get_line(offset)
        if self.line: self.line.request(consumer=name, type=gpiod.LINE_REQ_DIR_OUT, default_val=0)
    def set(self, v): 
        if self.line: self.line.set_value(1 if v else 0)
    def __enter__(self): return self
    def __exit__(self, *a): 
        if self.line: self.line.release()


class GPIOIn:
    def __init__(self, chip, offset, name):
        self.line = None if offset is None else gpiod.Chip(chip).get_line(offset)
        if self.line: self.line.request(consumer=name, type=gpiod.LINE_REQ_DIR_IN)
    def get(self): return None if self.line is None else self.line.get_value()
    def __enter__(self): return self
    def __exit__(self, *a): 
        if self.line: self.line.release()


class ILI9341:
    def __init__(self, spi, dc, rst, cs, bl):
        self.spi, self.dc, self.rst, self.cs, self.bl = spi, dc, rst, cs, bl
    def _cmd(self, c):
        if self.cs.line: self.cs.set(0)
        self.dc.set(0); self.spi.xfer2([c]); 
        if self.cs.line: self.cs.set(1)
    def _data(self, d):
        if self.cs.line: self.cs.set(0)
        self.dc.set(1)
        for i in range(0, len(d), 4096):
            self.spi.xfer2(list(d[i:i+4096]))
        if self.cs.line: self.cs.set(1)
    def reset(self):
        if not self.rst.line: return
        self.rst.set(0); time.sleep(0.05)
        self.rst.set(1); time.sleep(0.12)
    def init(self):
        self.reset()
        self._cmd(0x11); time.sleep(0.12)   # Sleep out
        self._cmd(0x3A); self._data([0x55]) # 16bpp
        self._cmd(0x36); self._data([0x48]) # MADCTL
        self._cmd(0x29); time.sleep(0.02)   # Display on
        self.bl.set(1)
    def window(self,x0,y0,x1,y1):
        self._cmd(0x2A); self._data([x0>>8,x0&0xFF,x1>>8,x1&0xFF])
        self._cmd(0x2B); self._data([y0>>8,y0&0xFF,y1>>8,y1&0xFF])
        self._cmd(0x2C)
    def fill(self,color):
        self.window(0,0,LCD_WIDTH-1,LCD_HEIGHT-1)
        buf = color.to_bytes(2,'big')*2048
        px = LCD_WIDTH*LCD_HEIGHT
        while px>0:
            n=min(px,2048)
            self._data(buf[:n*2]); px-=n
    def rect(self,x,y,w,h,color):
        self.window(x,y,x+w-1,y+h-1)
        self._data(color.to_bytes(2,'big')*(w*h))
    @staticmethod
    def rgb565(r,g,b): return ((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)


def touch_loop():
    bus, dev = map(int, os.path.basename(SPI_TOUCH_DEV)[6:].split("."))
    spi = spidev.SpiDev(); spi.open(bus,dev)
    spi.mode, spi.max_speed_hz = 0, SPI_TOUCH_SPEED_HZ
    with GPIOOut(GPIOCHIP,TOUCH_CS,"tp-cs") as cs, GPIOIn(GPIOCHIP,TOUCH_IRQ,"tp-irq") as irq:
        print("Touch test: press screen 10s")
        end=time.time()+10
        while time.time()<end:
            if irq.get()==0 or irq.get() is None:
                def read12(cmd):
                    cs.set(0); r=spi.xfer2([cmd,0,0]); cs.set(1)
                    return ((r[1]<<8)|r[2])>>3
                y=read12(0x90); x=read12(0xD0)
                print(f"Touch raw x={x} y={y}")
                time.sleep(0.1)


def main():
    bus,dev = map(int, os.path.basename(SPI_LCD_DEV)[6:].split("."))
    spi = spidev.SpiDev(); spi.open(bus,dev)
    spi.mode=0; spi.max_speed_hz=SPI_LCD_SPEED_HZ; spi.no_cs=not USE_HW_CS
    with GPIOOut(GPIOCHIP,LCD_DC,"lcd-dc") as dc, \
         GPIOOut(GPIOCHIP,LCD_RST,"lcd-rst") as rst, \
         GPIOOut(GPIOCHIP,LCD_BL,"lcd-bl") as bl, \
         GPIOOut(GPIOCHIP,LCD_CS,"lcd-cs") as cs:
        lcd=ILI9341(spi,dc,rst,cs,bl); lcd.init()
        for c in [(255,0,0),(0,255,0),(0,0,255),(255,255,255),(0,0,0)]:
            lcd.fill(ILI9341.rgb565(*c)); time.sleep(0.4)
        lcd.fill(ILI9341.rgb565(0,0,0))
        color=ILI9341.rgb565(255,255,0); bg=ILI9341.rgb565(0,0,0)
        x=y=10; dx=4; dy=3; sz=30; t0=time.time()
        while time.time()-t0<8:
            lcd.rect(x,y,sz,sz,color); time.sleep(0.02)
            lcd.rect(x,y,sz,sz,bg)
            x+=dx; y+=dy
            if x<0 or x+sz>=LCD_WIDTH: dx=-dx; x+=dx
            if y<0 or y+sz>=LCD_HEIGHT: dy=-dy; y+=dy
    if ENABLE_TOUCH: touch_loop()
    print("Done.")


if __name__=="__main__": main()
