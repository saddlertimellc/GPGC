import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from pymodbus.client import AsyncModbusTcpClient

HUMIDITY_REGISTER = 1
TEMPERATURE_REGISTER = 2
DEFAULT_INTERVAL = 60.0


def load_sensor_addresses() -> list[int]:
    """Collect sensor addresses from environment variables."""
    addresses: list[int] = []
    for key, value in os.environ.items():
        if key.startswith("SENSOR") and key.endswith("_ADDRESS"):
            try:
                addresses.append(int(value))
            except ValueError:
                logging.warning("Invalid sensor address %s=%s", key, value)
    return sorted(addresses)


async def read_sensor(client: AsyncModbusTcpClient, address: int) -> None:
    """Read and log humidity and temperature for a sensor."""
    if not client.connected:
        logging.error("Modbus client not connected")
        return
    try:
        result = await client.read_holding_registers(
            HUMIDITY_REGISTER, 2, slave=address
        )
    except Exception as exc:  # pragma: no cover - network failure
        logging.error("Sensor %s read exception: %s", address, exc)
        return
    if result.isError():
        logging.error("Sensor %s read error: %s", address, result)
        return
    humidity_raw, temperature_raw = result.registers
    humidity = -6 + 125 * humidity_raw / 65536.0
    temperature = -46.85 + 175.72 * temperature_raw / 65536.0
    logging.info(
        "address=%s timestamp=%s humidity=%.2f%% temperature=%.2f°C",
        address,
        datetime.utcnow().isoformat(),
        humidity,
        temperature,
    )


async def poll_loop(interval: float) -> None:
    load_dotenv()
    host = os.getenv("RS485_GATEWAY_HOST", "localhost")
    port = int(os.getenv("RS485_GATEWAY_PORT", "502"))
    addresses = load_sensor_addresses()
    if not addresses:
        logging.warning("No sensor addresses configured")
        return

    while True:
        try:
            async with AsyncModbusTcpClient(host, port=port) as client:
                if not client.connected:
                    logging.error("Modbus client not connected")
                else:
                    for address in addresses:
                        await read_sensor(client, address)
        except Exception as exc:  # pragma: no cover - network failure
            logging.error("Connection error: %s", exc)
        await asyncio.sleep(interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll RS485 sensors")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="Polling interval in seconds (default: %(default)s)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(poll_loop(args.interval))
    except KeyboardInterrupt:
        logging.info("Poller stopped")


if __name__ == "__main__":
    main()
