
#!/usr/bin/env python3
# Main data collection script for Pi Edge Sensing

import os
import time
from datetime import datetime, timezone
from pathlib import Path

# Project utility imports
from utils import (
    apply_calibration,
    csv_writer,
    ensure_dir,
    load_config,
    setup_logger,
)
from pulse import PulseCounter
from ads1115_reader import ADCManager

# Configuration paths and environment
CONFIG_PATH = os.environ.get("EDGE_CONFIG", "/home/gerrit/Projects/pi-sensing/config.yaml")
USB_MOUNT = Path(os.environ.get("USB_MOUNT", "/mnt/usb-data"))
DEVICE_ID = os.environ.get("DEVICE_ID", "pi-node-01")

# Set up logging (console and file)
logger = setup_logger("collector", logfile="collector.log")

def align_to_next_minute() -> None:
    """
    Sleep until the next clock minute to keep sampling windows aligned.
    """
    now = time.time()
    time.sleep(60 - (now % 60))

def initialize_pulse_counters(pulse_configs):
    """
    Start every configured pulse counter and return (name, counter) tuples.
    """
    counters = []
    chip_priority_env = os.environ.get("LGPIO_CHIP_PRIORITY")
    if chip_priority_env:
        logger.info("Using lgpio chip priority override: %s", chip_priority_env)
    for pulse_cfg in pulse_configs:
        counter = PulseCounter(
            gpio=int(pulse_cfg["gpio"]),
            pull_up=bool(pulse_cfg.get("pull_up", True)),
            falling=pulse_cfg.get("edge", "falling").lower() == "falling",
            debounce_us=int(pulse_cfg.get("debounce_us", 2000)),
        )
        counter.start()
        counters.append((pulse_cfg["name"], counter))
    return counters

def create_headers(counters, adc_channels):
    """
    Build CSV header names for pulse counts and ADC readings.
    """
    pulse_columns = [f"pulse_{name}_count" for name, _ in counters]
    adc_columns = [f"adc_{channel}_voltage_v" for channel in adc_channels]
    return ["timestamp_utc"] + pulse_columns + adc_columns

def main():
    """
    Main data collection loop. Reads pulses and ADC, writes to CSV.
    """
    cfg = load_config(CONFIG_PATH)
    sampling_seconds = int(cfg.get("sampling_seconds", 60))
    pulses_enabled = bool(cfg.get("pulses_enabled", True))
    device_id = cfg.get("device", {}).get("id", DEVICE_ID)
    calibration = cfg.get("calibration", {})

    # Ensure USB mount directory exists
    ensure_dir(USB_MOUNT)

    # Detect if any gpiochip character devices exist; if none, disable pulses automatically
    if pulses_enabled:
        gpiochips = sorted(Path('/dev').glob('gpiochip*'))
        if gpiochips:
            logger.info("Detected gpiochips: %s", ', '.join(p.name for p in gpiochips))
        else:
            logger.warning("No /dev/gpiochip* devices found; disabling pulse counters")
            pulses_enabled = False
    # Export config-driven backend ordering/env overrides before initializing counters
    backends_cfg = cfg.get("gpio_backends")
    if backends_cfg and isinstance(backends_cfg, list):
        os.environ.setdefault("GPIO_BACKENDS", ",".join(str(b) for b in backends_cfg))
    chip_prio_cfg = cfg.get("lgpio_chip_priority")
    if chip_prio_cfg and isinstance(chip_prio_cfg, list):
        os.environ.setdefault("LGPIO_CHIP_PRIORITY", ",".join(str(c) for c in chip_prio_cfg))

    counters = initialize_pulse_counters(cfg.get("pulses", [])) if pulses_enabled else []
    adc_manager = ADCManager(cfg.get("i2c_adcs", []))

    # Capture an initial reading to learn which ADC channels are present
    adc_channels = sorted(adc_manager.read_all().keys())
    header = create_headers(counters, adc_channels)

    # Open CSV file for writing
    file_handle, writer, csv_path = csv_writer(USB_MOUNT, device_id, header)
    logger.info("Writing CSV to %s", csv_path)

    # Uncomment to align sampling to the next minute
    # align_to_next_minute()

    while True:
        loop_started = time.time()
        timestamp_utc = datetime.now(timezone.utc).isoformat()
        # Get pulse counts (or empty list if disabled)
        pulse_values = [counter.snapshot_and_reset() for _, counter in counters] if pulses_enabled else []

        # Read raw ADC values, calibrate them, then write in column order
        adc_raw = adc_manager.read_all()
        adc_calibrated = apply_calibration(adc_raw, calibration)
        adc_values = [adc_calibrated.get(channel) for channel in adc_channels]

        # Write all sensor values to CSV
        writer.writerow([timestamp_utc] + pulse_values + adc_values)
        file_handle.flush()
        os.fsync(file_handle.fileno())

        # Sleep until next sample
        elapsed = time.time() - loop_started
        sleep_duration = max(0.0, sampling_seconds - (elapsed % sampling_seconds))
        time.sleep(sleep_duration)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
