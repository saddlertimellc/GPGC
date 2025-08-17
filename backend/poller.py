import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime

from dotenv import load_dotenv
from pymodbus.client import AsyncModbusTcpClient

SENSOR_TYPES = {
    "SHT20": {
        "function_code": 4,
        "humidity_register": 1,
        "temperature_register": 2,
        "serial": {"baudrate": 9600, "parity": "N", "stopbits": 1},
    },
    "SHT30": {
        "function_code": 4,
        "humidity_register": 1,
        "temperature_register": 0,
        "serial": {"baudrate": 9600, "parity": "N", "stopbits": 1},
    },
}

DEFAULT_INTERVAL = 60.0


@dataclass
class SensorConfig:
    """Configuration for an individual sensor."""

    function_code: int
    scale: float | str
    humid_register: int
    temp_register: int
    sensor_type: str


@dataclass
class GatewayConfig:
    """Connection and sensor details for a single gateway."""

    host: str
    port: int
    sensors: dict[int, SensorConfig]


def load_sensor_configs(prefix: str = "") -> dict[int, SensorConfig]:
    """Collect sensor addresses and configuration from environment variables.

    Sensors are configured using environment variable triples. With no prefix,
    variables look like ``SENSOR1_ADDRESS=1``, ``SENSOR1_FC=4`` and
    ``SENSOR1_SCALE=10``. For gateway‑specific sensors a prefix such as
    ``GW1_`` is applied, e.g., ``GW1_SENSOR1_ADDRESS``. If the function code is
    missing or invalid, function code 3 is assumed. If the scale is missing or
    invalid, a scale of 1 is used.

    Args:
        prefix: Optional prefix for environment variable names, including the
            trailing underscore (e.g., ``"GW1_"``).

    Returns:
        Mapping of sensor address to configuration.
    """

    configs: dict[int, SensorConfig] = {}
    for key, value in os.environ.items():
        if prefix:
            if not key.startswith(prefix):
                continue
            key_body = key[len(prefix) :]
        else:
            key_body = key
        if key_body.startswith("SENSOR") and key_body.endswith("_ADDRESS"):
            sensor_prefix = key_body[: -len("_ADDRESS")]
            try:
                address = int(value)
            except ValueError:
                logging.warning("Invalid sensor address %s=%s", key, value)
                continue

            type_key = f"{prefix}{sensor_prefix}_TYPE"
            sensor_type = os.getenv(type_key, "SHT20").upper()
            defaults = SENSOR_TYPES.get(sensor_type, SENSOR_TYPES["SHT20"])

            fc_key = f"{prefix}{sensor_prefix}_FC"
            try:
                fc = int(os.getenv(fc_key, str(defaults["function_code"])))
            except ValueError:
                logging.warning("Invalid function code %s=%s", fc_key, os.getenv(fc_key))
                fc = defaults["function_code"]
            if fc not in (3, 4):
                logging.warning("Unsupported function code %s=%s", fc_key, fc)
                fc = defaults["function_code"]

            scale_key = f"{prefix}{sensor_prefix}_SCALE"
            scale_env = os.getenv(scale_key, "1")
            if scale_env.lower() == "auto":
                scale: float | str = "auto"
            else:
                try:
                    scale = float(scale_env)
                except ValueError:
                    logging.warning("Invalid scale %s=%s", scale_key, scale_env)
                    scale = 1.0

            humid_key = f"{prefix}{sensor_prefix}_HUMID_REG"
            try:
                humid_reg = int(
                    os.getenv(humid_key, str(defaults["humidity_register"]))
                )
            except ValueError:
                logging.warning("Invalid humidity register %s=%s", humid_key, os.getenv(humid_key))
                humid_reg = defaults["humidity_register"]

            temp_key = f"{prefix}{sensor_prefix}_TEMP_REG"
            try:
                temp_reg = int(
                    os.getenv(temp_key, str(defaults["temperature_register"]))
                )
            except ValueError:
                logging.warning("Invalid temperature register %s=%s", temp_key, os.getenv(temp_key))
                temp_reg = defaults["temperature_register"]

            configs[address] = SensorConfig(
                function_code=fc,
                scale=scale,
                humid_register=humid_reg,
                temp_register=temp_reg,
                sensor_type=sensor_type,
            )

    return dict(sorted(configs.items()))


def load_gateway_configs() -> list[GatewayConfig]:
    """Collect gateway connection details and their sensors from environment."""

    gateways: list[GatewayConfig] = []

    prefixes: set[str] = set()
    for key in os.environ:
        if key.startswith("GW") and key.endswith("_HOST"):
            prefixes.add(key[: -len("_HOST")])

    for prefix in sorted(prefixes):
        host = os.getenv(f"{prefix}_HOST", "localhost")
        try:
            port = int(os.getenv(f"{prefix}_PORT", "502"))
        except ValueError:
            logging.warning("Invalid port for %s", prefix)
            continue
        sensors = load_sensor_configs(f"{prefix}_")
        if not sensors:
            logging.warning("No sensor addresses configured for %s", prefix)
        gateways.append(GatewayConfig(host, port, sensors))

    if not gateways:
        # Fallback to legacy single-gateway configuration
        host = os.getenv("RS485_GATEWAY_HOST", "localhost")
        try:
            port = int(os.getenv("RS485_GATEWAY_PORT", "502"))
        except ValueError:
            logging.warning("Invalid RS485 gateway port")
            return []
        sensors = load_sensor_configs()
        if sensors:
            gateways.append(GatewayConfig(host, port, sensors))

    return gateways


def _apply_scale(value: int, scale: float | str) -> float:
    """Apply a scaling factor to a Modbus register value.

    When ``scale`` is ``"auto"`` the function attempts a simple inference based
    on the magnitude of ``value``.
    """

    if scale == "auto":
        if value > 10000:
            return value / 100.0
        if value > 1000:
            return value / 10.0
        return float(value)
    return value / float(scale)


async def read_sensor(
    client: AsyncModbusTcpClient, address: int, cfg: SensorConfig
) -> None:
    """Read and log humidity and temperature for a sensor."""
    if not client.connected:
        logging.error("Modbus client not connected")
        return
    try:
        if cfg.function_code == 4:
            humid_res = await client.read_input_registers(
                cfg.humid_register, 1, unit=address
            )
            temp_res = await client.read_input_registers(
                cfg.temp_register, 1, unit=address
            )
        else:
            humid_res = await client.read_holding_registers(
                cfg.humid_register, 1, unit=address
            )
            temp_res = await client.read_holding_registers(
                cfg.temp_register, 1, unit=address
            )
    except Exception as exc:  # pragma: no cover - network failure
        logging.error("Sensor %s read exception: %s", address, exc)
        return
    if humid_res.isError() or temp_res.isError():
        logging.error("Sensor %s read error: %s %s", address, humid_res, temp_res)
        return
    humidity_raw = humid_res.registers[0]
    temperature_raw = temp_res.registers[0]
    humidity_raw = _apply_scale(humidity_raw, cfg.scale)
    temperature_raw = _apply_scale(temperature_raw, cfg.scale)
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
    gateways = load_gateway_configs()
    if not gateways:
        logging.warning("No gateways configured")
        return

    while True:
        for gateway in gateways:
            try:
                async with AsyncModbusTcpClient(gateway.host, port=gateway.port) as client:
                    if not client.connected:
                        logging.error(
                            "Modbus client not connected to %s:%s", gateway.host, gateway.port
                        )
                    else:
                        for address, cfg in gateway.sensors.items():
                            await read_sensor(
                                client,
                                address,
                                cfg,
                            )
            except Exception as exc:  # pragma: no cover - network failure
                logging.error(
                    "Connection error %s:%s %s", gateway.host, gateway.port, exc
                )
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
