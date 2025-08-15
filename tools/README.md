# Tools

Utility scripts for provisioning and diagnostics.

## `sht20_ch4_test.py`

Polls an SHT20 sensor via the Waveshare 4‑channel RS485 gateway.

### Usage
```bash
python sht20_ch4_test.py [--mode rtu|tcp]
```
Defaults to RTU‑over‑TCP. Override connection details with the `RS485_GATEWAY_HOST`, `RS485_GATEWAY_PORT`, `SENSOR_ADDRESS`, `REG_TEMP`, and `REG_RH` environment variables.

Example:

```bash
export RS485_GATEWAY_HOST=192.168.1.204
export RS485_GATEWAY_PORT=4196
export SENSOR_ADDRESS=1
python sht20_ch4_test.py
```
