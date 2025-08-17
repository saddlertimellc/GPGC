import argparse, os, sys, time
from pymodbus.client import ModbusSerialClient, ModbusTcpClient

HOST = os.getenv("RS485_GATEWAY_HOST", "192.168.1.204")
PORT = int(os.getenv("RS485_GATEWAY_PORT", "4502"))
SENSOR_ADDRESS = int(os.getenv("SENSOR_ADDRESS", "1"))
REG_TEMP = int(os.getenv("REG_TEMP", "0x0001"), 16)
REG_RH   = int(os.getenv("REG_RH",   "0x0002"), 16)

def read_one(client, unit, addr):
    r = client.read_input_registers(addr, 1, unit=unit)
    if r.isError(): raise RuntimeError(str(r))
    return r.registers[0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rtu","tcp"], default="rtu",
                    help="rtu = RTU-over-TCP via socket://  |  tcp = Modbus TCP framing")
    args = ap.parse_args()

    if args.mode == "rtu":
        # RTU-over-TCP: raw RTU frames inside a TCP socket
        url = f"socket://{HOST}:{PORT}"
        client = ModbusSerialClient(method="rtu", port=url, baudrate=9600,
                                    parity="N", stopbits=1, bytesize=8, timeout=2)
    else:
        # Modbus TCP (unlikely for your Waveshare setup, but here if needed)
        client = ModbusTcpClient(host=HOST, port=PORT, timeout=2)

    if not client.connect():
        print(f"Failed to connect to {HOST}:{PORT} in {args.mode} mode", file=sys.stderr)
        sys.exit(2)

    try:
        t_raw = read_one(client, SENSOR_ADDRESS, REG_TEMP)  # °C × 10
        h_raw = read_one(client, SENSOR_ADDRESS, REG_RH)    # %RH × 10
        print(f"Temperature: {t_raw/10.0:.1f} °C")
        print(f"Humidity:    {h_raw/10.0:.1f} %RH")
    finally:
        client.close()

if __name__ == "__main__":
    main()
