#!/usr/bin/env python3
import os, sys, argparse
from pymodbus.client import ModbusSerialClient, ModbusTcpClient
import pymodbus

HOST = os.getenv("RS485_GATEWAY_HOST", "192.168.1.204")
PORT = int(os.getenv("RS485_GATEWAY_PORT", "4502"))
UNIT = int(os.getenv("SENSOR_ADDRESS", "1"))
REG_TEMP = int(os.getenv("REG_TEMP", "0x0001"), 16)  # SHT20: start=1
REG_RH   = int(os.getenv("REG_RH",   "0x0002"), 16)  # next register

def read_pair(client, unit, start_addr):
    """
    FC04 read 2 input registers [temp_x10, rh_x10] with broad compatibility.
    Tries (slave=), then (unit=), then positional, finally relies on client.unit_id.
    """
    # try 1: slave kw
    try:
        rr = client.read_input_registers(address=start_addr, count=2, slave=unit)
        if rr is not None: return _ok(rr, start_addr, unit)
    except TypeError:
        pass

    # try 2: unit kw
    try:
        rr = client.read_input_registers(address=start_addr, count=2, unit=unit)
        if rr is not None: return _ok(rr, start_addr, unit)
    except TypeError:
        pass

    # try 3: positional unit
    try:
        rr = client.read_input_registers(start_addr, 2, unit)
        if rr is not None: return _ok(rr, start_addr, unit)
    except TypeError:
        pass

    # try 4: set client.unit_id and call without unit
    if hasattr(client, "unit_id"):
        client.unit_id = unit
    rr = client.read_input_registers(address=start_addr, count=2)
    return _ok(rr, start_addr, unit)

def _ok(rr, addr, unit):
    if not rr or rr.isError():
        print(f"FC04 @ {addr} (qty=2) unit {unit}: {rr}", file=sys.stderr)
        raise RuntimeError(str(rr))
    return rr.registers  # [temp_x10, rh_x10]

def make_client(mode):
    if mode == "rtu":
        # RTU-over-TCP via pyserial’s socket:// URL
        url = f"socket://{HOST}:{PORT}"
        return ModbusSerialClient(
            port=url, baudrate=9600, parity="N", stopbits=1, bytesize=8, timeout=2
        )
    else:
        return ModbusTcpClient(host=HOST, port=PORT, timeout=2)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rtu","tcp"], default="rtu",
                    help="rtu = RTU-over-TCP via socket://  |  tcp = Modbus TCP framing")
    args = ap.parse_args()

    print(f"pymodbus {pymodbus.__version__}", file=sys.stderr)

    client = make_client(args.mode)
    if not client.connect():
        print(f"Failed to connect to {HOST}:{PORT} in {args.mode} mode", file=sys.stderr)
        sys.exit(2)

    try:
        t_raw, h_raw = read_pair(client, UNIT, REG_TEMP)
        print(f"Temperature: {t_raw/10.0:.1f} °C")
        print(f"Humidity:    {h_raw/10.0:.1f} %RH")
    finally:
        client.close()

if __name__ == "__main__":
    main()
