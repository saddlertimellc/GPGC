import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from google.cloud import firestore
from pymodbus.client import (
    AsyncModbusSerialClient,
    AsyncModbusTcpClient,
    ModbusBaseClient,
)

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


load_dotenv()
DEGREES_F = os.getenv("DEGREES_F", "").lower() in {"1", "true", "yes"}
FIRESTORE_PROJECT = os.getenv("FIRESTORE_PROJECT")
FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION")
try:  # pragma: no cover - requires credentials
    firestore_client = firestore.AsyncClient(project=FIRESTORE_PROJECT)
except Exception as exc:  # pragma: no cover - credentials misconfigured
    logging.warning("Firestore client init failed: %s", exc)
    firestore_client = None


@dataclass
class SensorConfig:
    """Configuration for an individual sensor."""
    device_id: str
    function_code: int
    scale: float | str
    humid_register: int
    temp_register: int
    sensor_type: str
    conversion: str


@dataclass
class GatewayConfig:
    """Connection and sensor details for a single gateway."""

    name: str
    host: str
    port: int
    sensors: dict[int, SensorConfig]
    mode: str = "tcp"
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1


def load_sensor_configs() -> dict[str, dict[int, SensorConfig]]:
    """Collect sensor configuration from environment variables.

    Sensors are declared using numbered environment variable groups. Each group
    must provide a gateway name and unit ID, e.g.::

        SENSOR1_GATEWAY=4XCH1
        SENSOR1_UNITID=1
        SENSOR1_TYPE=SHT20

    Optional variables ``SENSOR<N>_DEVID``, ``SENSOR<N>_FC``, ``SENSOR<N>_SCALE``,
    ``SENSOR<N>_HUMID_REG`` and ``SENSOR<N>_TEMP_REG`` may override defaults
    derived from ``SENSOR_TYPES``. ``SENSOR<N>_CONVERSION`` controls how raw
    register values are converted into human readable units and accepts either
    ``"sht_formula"`` or ``"scaled"``.

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

        devid_key = f"{sensor_prefix}_DEVID"
        device_id = os.getenv(devid_key, sensor_prefix)

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

        conv_key = f"{sensor_prefix}_CONVERSION"
        default_conv = "scaled" if sensor_type in {"SHT20", "SHT30"} else "sht_formula"
        conv_env = os.getenv(conv_key, default_conv)
        conv_env_lower = conv_env.lower()
        if conv_env_lower not in {"sht_formula", "scaled"}:
            logging.warning("Invalid conversion %s=%s", conv_key, conv_env)
            conversion = default_conv
        else:
            conversion = conv_env_lower

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
            device_id=device_id,
            function_code=fc,
            scale=scale,
            humid_register=humid_reg,
            temp_register=temp_reg,
            sensor_type=sensor_type,
            conversion=conversion,
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
        mode = os.getenv(f"GW_{gateway_name}_MODE", "tcp").lower()
        if mode not in {"tcp", "rtu"}:
            logging.warning("Invalid mode for GW_%s", gateway_name)
            mode = "tcp"

        # Determine serial defaults based on the first sensor type
        serial_defaults = {"baudrate": 9600, "parity": "N", "stopbits": 1}
        if sensors:
            first_sensor = next(iter(sensors.values()))
            serial_defaults = SENSOR_TYPES.get(first_sensor.sensor_type, {}).get(
                "serial", serial_defaults
            )

        def _env_int(key: str, default: int) -> int:
            try:
                return int(os.getenv(key, str(default)))
            except ValueError:
                logging.warning("Invalid %s for GW_%s", key, gateway_name)
                return default

        baudrate = _env_int(f"GW_{gateway_name}_BAUDRATE", serial_defaults["baudrate"])
        parity = os.getenv(
            f"GW_{gateway_name}_PARITY", serial_defaults["parity"]
        ).upper()
        stopbits = _env_int(
            f"GW_{gateway_name}_STOPBITS", serial_defaults["stopbits"]
        )

        gateways.append(
            GatewayConfig(
                name=gateway_name,
                host=host,
                port=port,
                sensors=sensors,
                mode=mode,
                baudrate=baudrate,
                parity=parity,
                stopbits=stopbits,
            )
        )

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


async def read_pair(
    client: ModbusBaseClient, unit: int, start_addr: int, fc: int
) -> list[int]:
    """Read two consecutive registers using either FC03 or FC04.

    Tries a variety of parameter conventions for maximum compatibility with
    different ``pymodbus`` versions: ``slave=`` first, then ``unit=``, then a
    positional unit, finally falling back to setting ``client.unit_id`` and
    calling without a unit argument.
    """

    def _ok(rr: Any) -> list[int]:
        if not rr or rr.isError():
            raise RuntimeError(
                f"FC{fc:02d} @ {start_addr} (qty=2) unit {unit}: {rr}"
            )
        return rr.registers

    func = (
        client.read_input_registers
        if fc == 4
        else client.read_holding_registers
    )

    try:
        rr = await func(address=start_addr, count=2, slave=unit)
        return _ok(rr)
    except TypeError:
        pass

    try:
        rr = await func(address=start_addr, count=2, unit=unit)
        return _ok(rr)
    except TypeError:
        pass

    try:
        rr = await func(start_addr, 2, unit)
        return _ok(rr)
    except TypeError:
        pass

    if hasattr(client, "unit_id"):
        client.unit_id = unit
    try:
        rr = await func(address=start_addr, count=2)
        return _ok(rr)
    except Exception as exc:  # pragma: no cover - network failure
        host = getattr(client, "host", None)
        port = getattr(client, "port", None)
        params = getattr(client, "comm_params", None) or getattr(client, "params", None)
        if params:
            host = host or getattr(params, "host", None) or getattr(params, "address", None)
            port = port or getattr(params, "port", None)
            if isinstance(params, dict):
                host = host or params.get("host") or params.get("address")
                port = port or params.get("port")
        logging.error(
            "FC%02d read failed from %s:%s unit %s: %s",
            fc,
            host,
            port,
            unit,
            exc,
        )
        raise


async def publish_reading(
    dev_id: str, channel: str, ts: str, temp_c: float, rh: float
) -> None:
    if firestore_client is None or not FIRESTORE_COLLECTION:
        return
    doc = (
        firestore_client.collection(FIRESTORE_COLLECTION)
        .document(dev_id)
        .collection("readings")
        .document(str(ts))
    )
    await doc.set({"channel": channel, "temp_c": temp_c, "rh": rh})


async def read_sensor(
    client: ModbusBaseClient, address: int, cfg: SensorConfig, channel: str
) -> None:
    """Read and log humidity and temperature for a sensor."""
    if not client.connected:
        logging.error("Modbus client not connected")
        return
    start_addr = min(cfg.humid_register, cfg.temp_register)
    try:
        regs = await read_pair(client, address, start_addr, cfg.function_code)
    except Exception as exc:  # pragma: no cover - network failure
        logging.error("Sensor %s read exception: %s", address, exc)
        return

    if cfg.humid_register < cfg.temp_register:
        humidity_raw, temperature_raw = regs[0], regs[1]
    else:
        temperature_raw, humidity_raw = regs[0], regs[1]

    if cfg.conversion == "scaled":
        if cfg.scale == 1:
            humidity = humidity_raw / 10.0
            temperature = temperature_raw / 10.0
        else:
            humidity = _apply_scale(humidity_raw, cfg.scale)
            temperature = _apply_scale(temperature_raw, cfg.scale)
    else:
        humidity_raw = _apply_scale(humidity_raw, cfg.scale)
        temperature_raw = _apply_scale(temperature_raw, cfg.scale)
        humidity = -6 + 125 * humidity_raw / 65536.0
        temperature = -46.85 + 175.72 * temperature_raw / 65536.0

    if DEGREES_F:
        temperature = temperature * 9 / 5 + 32
        temp_unit = "°F"
    else:
        temp_unit = "°C"

    debug_info = [cfg.device_id, channel]
    ts = datetime.utcnow().isoformat()
    logging.info(
        "address=%s device=%s channel=%s timestamp=%s humidity=%.2f%% temperature=%.2f%s debug=%s",
        address,
        cfg.device_id,
        channel,
        ts,
        humidity,
        temperature,
        temp_unit,
        debug_info,
    )
    await publish_reading(cfg.device_id, channel, ts, temperature, humidity)


async def poll_loop(interval: float) -> None:
    load_dotenv()
    gateways = load_gateway_configs()
    if not gateways:
        logging.warning("No gateways configured")
        return

    while True:
        for gateway in gateways:
            try:
                if gateway.mode == "rtu":
                    async with AsyncModbusSerialClient(
                        port=f"socket://{gateway.host}:{gateway.port}",
                        baudrate=gateway.baudrate,
                        parity=gateway.parity,
                        stopbits=gateway.stopbits,
                    ) as client:
                        if not client.connected:
                            logging.error(
                                "Modbus client not connected to %s:%s",
                                gateway.host,
                                gateway.port,
                            )
                        else:
                            for address, cfg in gateway.sensors.items():
                                await read_sensor(client, address, cfg, gateway.name)
                else:
                    async with AsyncModbusTcpClient(
                        gateway.host, port=gateway.port
                    ) as client:
                        if not client.connected:
                            logging.error(
                                "Modbus client not connected to %s:%s",
                                gateway.host,
                                gateway.port,
                            )
                        else:
                            for address, cfg in gateway.sensors.items():
                                await read_sensor(client, address, cfg, gateway.name)
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
