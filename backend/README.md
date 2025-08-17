# Backend Environment Configuration

The backend expects gateway and sensor parameters to be supplied via environment variables using these patterns:

- `GW_<NAME>_HOST`
- `GW_<NAME>_PORT`
- `GW_<NAME>_SENSOR<N>_ADDRESS`
- `GW_<NAME>_SENSOR<N>_FC`
- `GW_<NAME>_SENSOR<N>_SCALE`

`<NAME>` identifies a gateway while `<N>` selects a sensor on that gateway.

## Example

```bash
GW_4XCH1_HOST=192.168.1.201
GW_4XCH1_PORT=502
GW_4XCH1_SENSOR1_ADDRESS=0
GW_4XCH1_SENSOR1_FC=3
GW_4XCH1_SENSOR1_SCALE=1
GW_4XCH1_SENSOR2_ADDRESS=2
GW_4XCH1_SENSOR2_FC=3
GW_4XCH1_SENSOR2_SCALE=1
GW_4XCH1_SENSOR3_ADDRESS=4
GW_4XCH1_SENSOR3_FC=3
GW_4XCH1_SENSOR3_SCALE=1
GW_4XCH1_SENSOR4_ADDRESS=6
GW_4XCH1_SENSOR4_FC=3
GW_4XCH1_SENSOR4_SCALE=1
```

This example mirrors the typical mapping for a four channel gateway.
