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


def load_sensor_configs() -> dict[int, int]:
    """Collect sensor addresses and function codes from environment variables.

    Sensors are configured using pairs of environment variables:

    ``SENSOR1_ADDRESS=1`` and ``SENSOR1_FC=4`` for example. If the function
    code is missing or invalid, function code 3 is assumed.

    Returns:
        Mapping of sensor address to Modbus function code (3 or 4).
    """

    configs: dict[int, int] = {}
    for key, value in os.environ.items():
        if key.startswith("SENSOR") and key.endswith("_ADDRESS"):
            prefix = key[: -len("_ADDRESS")]
            try:
                address = int(value)
            except ValueError:
                logging.warning("Invalid sensor address %s=%s", key, value)
                continue

            fc_key = f"{prefix}_FC"
            try:
                fc = int(os.getenv(fc_key, "3"))
            except ValueError:
                logging.warning("Invalid function code %s=%s", fc_key, os.getenv(fc_key))
                fc = 3
            if fc not in (3, 4):
                logging.warning("Unsupported function code %s=%s", fc_key, fc)
                fc = 3
            configs[address] = fc

    return dict(sorted(configs.items()))


async def read_sensor(
    client: AsyncModbusTcpClient, address: int, function_code: int
) -> None:
    """Read and log humidity and temperature for a sensor."""
    if not client.connected:
        logging.error("Modbus client not connected")
        return
    try:
        if function_code == 4:
            result = await client.read_input_registers(
                HUMIDITY_REGISTER, 2, slave=address
            )
        else:
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
    sensor_configs = load_sensor_configs()
    if not sensor_configs:
        logging.warning("No sensor addresses configured")
        return

    while True:
        try:
            async with AsyncModbusTcpClient(host, port=port) as client:
                if not client.connected:
                    logging.error("Modbus client not connected")
                else:
                    for address, fc in sensor_configs.items():
                        await read_sensor(client, address, fc)
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
