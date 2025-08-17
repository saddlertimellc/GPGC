#!/usr/bin/env python3
"""Utility to append sensor configuration to the project's .env file.

The script interactively prompts for sensor type, gateway/channel name and
Modbus unit ID. Derived configuration such as function code and register
addresses are written along with gateway connection details so that
``poller.py`` can load them without further manual editing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from dotenv import dotenv_values

try:  # pragma: no cover - import paths differ when executed directly
    from poller import SENSOR_TYPES  # type: ignore
except Exception:  # pragma: no cover - when executed as module
    from backend.poller import SENSOR_TYPES  # type: ignore


ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _prompt(prompt: str, default: str | None = None) -> str:
    """Prompt the user for input returning ``default`` for empty responses."""

    if default is not None:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    response = input(prompt).strip()
    if not response and default is not None:
        return default
    return response


def _next_sensor_number(env: Dict[str, str]) -> int:
    """Determine the next available sensor index based on existing variables."""

    numbers: list[int] = []
    for key in env:
        if key.startswith("SENSOR") and key.endswith("_GATEWAY"):
            try:
                numbers.append(int(key[len("SENSOR") : -len("_GATEWAY")]))
            except ValueError:
                continue
    return max(numbers, default=0) + 1


def main() -> None:
    env: Dict[str, str] = {}
    if ENV_PATH.exists():
        env = {k: v for k, v in dotenv_values(ENV_PATH).items() if v is not None}

    sensor_type = _prompt("Sensor type (e.g. SHT20, SHT30)", "SHT20").upper()
    if sensor_type not in SENSOR_TYPES:
        print(f"Unknown sensor type '{sensor_type}', defaulting to SHT20")
        sensor_type = "SHT20"
    gateway = _prompt("Gateway/channel name (e.g. 4XCH1)")
    unit_str = _prompt("Modbus unit ID")
    try:
        unit_id = int(unit_str)
    except ValueError:
        raise SystemExit("Unit ID must be an integer")

    defaults = SENSOR_TYPES[sensor_type]
    fc = defaults["function_code"]
    humid_reg = defaults["humidity_register"]
    temp_reg = defaults["temperature_register"]

    sensor_number = _next_sensor_number(env)

    lines: list[str] = []
    host_key = f"GW_{gateway}_HOST"
    port_key = f"GW_{gateway}_PORT"
    if host_key not in env:
        host = _prompt(f"Gateway host for {gateway}", "localhost")
        lines.append(f"{host_key}={host}\n")
    if port_key not in env:
        port = _prompt(f"Gateway port for {gateway}", "502")
        lines.append(f"{port_key}={port}\n")

    prefix = f"SENSOR{sensor_number}"
    lines.extend(
        [
            f"{prefix}_GATEWAY={gateway}\n",
            f"{prefix}_UNITID={unit_id}\n",
            f"{prefix}_TYPE={sensor_type}\n",
            f"{prefix}_FC={fc}\n",
            f"{prefix}_HUMID_REG={humid_reg}\n",
            f"{prefix}_TEMP_REG={temp_reg}\n",
        ]
    )

    with ENV_PATH.open("a", encoding="utf8") as env_file:
        if env_file.tell() > 0:
            env_file.write("\n")
        env_file.writelines(lines)

    print(
        f"Added sensor {sensor_number}: type={sensor_type} gateway={gateway} unit={unit_id}"
    )


if __name__ == "__main__":  # pragma: no cover - manual execution only
    main()
