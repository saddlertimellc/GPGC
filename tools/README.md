# Tools

Utility scripts for provisioning and diagnostics.

## `sht20_ch4_test.py`

Polls an SHT20 sensor via the Waveshare 4‑channel RS485 gateway.

### Usage
```bash
python sht20_ch4_test.py [--mode rtu|tcp]
```
Defaults to RTU‑over‑TCP. Override connection details with the `GW_CH4_HOST`, `GW_PORT`, `SENSOR_ADDRESS`, `REG_TEMP`, and `REG_RH` environment variables.
