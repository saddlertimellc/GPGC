# Backend Environment Configuration

The backend expects gateway and sensor parameters to be supplied via environment
variables using these patterns:

- `GW_<NAME>_HOST`
- `GW_<NAME>_PORT`
- `GW_<NAME>_MODE` *(optional, "tcp" or "rtu", defaults to "tcp")*
- `GW_<NAME>_BAUDRATE` *(optional, for ``rtu`` mode)*
- `GW_<NAME>_PARITY` *(optional, for ``rtu`` mode)*
- `GW_<NAME>_STOPBITS` *(optional, for ``rtu`` mode)*
- `SENSOR<N>_GATEWAY`
- `SENSOR<N>_UNITID`
- `SENSOR<N>_TYPE`
- `SENSOR<N>_FC` *(optional)*
- `SENSOR<N>_SCALE` *(optional)*
- `SENSOR<N>_HUMID_REG` *(optional)*
- `SENSOR<N>_TEMP_REG` *(optional)*

`<NAME>` identifies a gateway while `<N>` selects a sensor. Each sensor is
associated with a gateway via the ``SENSOR<N>_GATEWAY`` variable.

## Example

```bash
GW_4XCH1_HOST=192.168.1.201
GW_4XCH1_PORT=502
GW_4XCH1_MODE=rtu
GW_4XCH1_BAUDRATE=9600
GW_4XCH1_PARITY=N
GW_4XCH1_STOPBITS=1
SENSOR1_GATEWAY=4XCH1
SENSOR1_UNITID=1
SENSOR1_TYPE=SHT20
SENSOR2_GATEWAY=4XCH1
SENSOR2_UNITID=2
SENSOR2_TYPE=SHT20
SENSOR3_GATEWAY=4XCH1
SENSOR3_UNITID=3
SENSOR3_TYPE=SHT20
SENSOR4_GATEWAY=4XCH1
SENSOR4_UNITID=4
SENSOR4_TYPE=SHT20
```

This example mirrors the typical mapping for a four channel gateway. Function
codes and register addresses are inferred from ``SENSOR_TYPES`` based on the
``SENSOR<N>_TYPE`` values but may be overridden by providing the optional
variables shown above.

## Adding sensors interactively

The ``backend`` module provides a small helper script to append new sensor
definitions to the project's ``.env`` file. Run::

    python backend/add_sensor.py

You will be prompted for the sensor type, gateway/channel name and Modbus unit
ID. Connection details and derived registers are appended to ``.env`` so that
``poller.py`` can load the configuration without manual edits.
