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
        "humidity_register": 2,
        "temperature_register": 1,
        "serial": {"baudrate": 9600, "parity": "N", "stopbits": 1},
    },
    "SHT30": {
        "function_code": 3,
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


def load_sensor_configs() -> dict[str, dict[int, SensorConfig]]:
    """Collect sensor configuration from environment variables.

    Sensors are declared using numbered environment variable groups. Each group
    must provide a gateway name and unit ID, e.g.::

        SENSOR1_GATEWAY=4XCH1
        SENSOR1_UNITID=1
        SENSOR1_TYPE=SHT20

    Optional variables ``SENSOR<N>_FC``, ``SENSOR<N>_SCALE``,
    ``SENSOR<N>_HUMID_REG`` and ``SENSOR<N>_TEMP_REG`` may override defaults
    derived from ``SENSOR_TYPES``.

    Returns:
        Mapping of gateway name to mapping of unit ID to ``SensorConfig``.
    """

    configs: dict[str, dict[int, SensorConfig]] = {}
    for key, value in os.environ.items():
        if not key.startswith("SENSOR") or not key.endswith("_GATEWAY"):
            continue
        sensor_prefix = key[: -len("_GATEWAY")]
        gateway_name = value

        unit_key = f"{sensor_prefix}_UNITID"
        try:
            unit_id = int(os.getenv(unit_key, ""))
        except ValueError:
            logging.warning("Invalid unit id %s=%s", unit_key, os.getenv(unit_key))
            continue

        type_key = f"{sensor_prefix}_TYPE"
        sensor_type = os.getenv(type_key, "SHT20").upper()
        defaults = SENSOR_TYPES.get(sensor_type, SENSOR_TYPES["SHT20"])

        fc_key = f"{sensor_prefix}_FC"
        try:
            fc = int(os.getenv(fc_key, str(defaults["function_code"])))
        except ValueError:
            logging.warning("Invalid function code %s=%s", fc_key, os.getenv(fc_key))
            fc = defaults["function_code"]
        if fc not in (3, 4):
            logging.warning("Unsupported function code %s=%s", fc_key, fc)
            fc = defaults["function_code"]

        scale_key = f"{sensor_prefix}_SCALE"
        scale_env = os.getenv(scale_key, "1")
        if scale_env.lower() == "auto":
            scale: float | str = "auto"
        else:
            try:
                scale = float(scale_env)
            except ValueError:
                logging.warning("Invalid scale %s=%s", scale_key, scale_env)
                scale = 1.0

        humid_key = f"{sensor_prefix}_HUMID_REG"
        try:
            humid_reg = int(
                os.getenv(humid_key, str(defaults["humidity_register"]))
            )
        except ValueError:
            logging.warning("Invalid humidity register %s=%s", humid_key, os.getenv(humid_key))
            humid_reg = defaults["humidity_register"]

        temp_key = f"{sensor_prefix}_TEMP_REG"
        try:
            temp_reg = int(
                os.getenv(temp_key, str(defaults["temperature_register"]))
            )
        except ValueError:
            logging.warning(
                "Invalid temperature register %s=%s", temp_key, os.getenv(temp_key)
            )
            temp_reg = defaults["temperature_register"]

        cfg = SensorConfig(
            function_code=fc,
            scale=scale,
            humid_register=humid_reg,
            temp_register=temp_reg,
            sensor_type=sensor_type,
        )

        gateway_sensors = configs.setdefault(gateway_name, {})
        gateway_sensors[unit_id] = cfg

    return {
        gw: dict(sorted(sensors.items()))
        for gw, sensors in sorted(configs.items())
    }


def load_gateway_configs() -> list[GatewayConfig]:
    """Collect gateway connection details and their sensors from environment."""

    sensor_groups = load_sensor_configs()
    gateways: list[GatewayConfig] = []

    for gateway_name, sensors in sensor_groups.items():
        host = os.getenv(f"GW_{gateway_name}_HOST", "localhost")
        try:
            port = int(os.getenv(f"GW_{gateway_name}_PORT", "502"))
        except ValueError:
            logging.warning("Invalid port for GW_%s", gateway_name)
            continue
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
