import time
import bme680
from smbus2 import SMBus


def main() -> None:
    """Poll BME688 sensor and log readings every second."""
    try:
        sensor = bme680.BME680(
            i2c_addr=bme680.I2C_ADDR_SECONDARY, i2c_device=SMBus(2)
        )
    except FileNotFoundError as exc:
        raise RuntimeError("I2C device not found. Adjust bus number if necessary.") from exc

    sensor.set_humidity_oversample(bme680.OS_2X)
    sensor.set_pressure_oversample(bme680.OS_4X)
    sensor.set_temperature_oversample(bme680.OS_8X)
    sensor.set_filter(bme680.FILTER_SIZE_3)
    sensor.set_gas_status(bme680.ENABLE_GAS_MEAS)

    print("Polling BME688 sensor. Press Ctrl+C to exit.")
    try:
        while True:
            if sensor.get_sensor_data():
                data = sensor.data
                temp_f = data.temperature * 9 / 5 + 32
                print(
                    f"Temperature: {temp_f:.2f} °F, "
                    f"Humidity: {data.humidity:.2f} %, "
                    f"Pressure: {data.pressure:.2f} hPa, "
                    f"Gas resistance: {data.gas_resistance:.2f} Ω"
                )
            time.sleep(1)
    finally:
        sensor.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error: {exc}")
