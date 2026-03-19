import threading
import time
import os
from datetime import datetime, timezone
from pathlib import Path
import logging

from utils import (
    apply_calibration,
    csv_writer,
    ensure_dir,
)

logger = logging.getLogger("collector")


class CollectorService:
    """
    Background service responsible for:
    - Reading pulses
    - Reading ADC values
    - Writing CSV
    - Sending IoT messages
    - Blinking LED
    """

    def __init__(
        self,
        cfg: dict,
        adc_manager,
        counters,
        ext_status_led,
        iot=None,
        usb_mount=Path("/mnt/usb-data"),
        logger=None
    ):
        self.cfg = cfg
        self.adc_manager = adc_manager
        self.counters = counters
        self.ext_status_led = ext_status_led
        self.iot = iot
        self.usb_mount = usb_mount
        self.logger = logger or logging.getLogger("collector")

        self._running = False
        self._thread = None

        self.sampling_seconds = int(cfg.get("sampling_seconds", 60))
        self.calibration = cfg.get("calibration", {})
        # Device ID from config or env, used for file naming and IoT messages
        self.device_id = (
            cfg.get("device", {}).get("id")
            or os.environ.get("DEVICE_ID")
            or "pi-node-01"
        )

        ensure_dir(self.usb_mount)

        # Setup CSV
        self.adc_channels = adc_manager.get_channel_names()
        self.header = self._create_headers()
        self.file_handle, self.writer, self.csv_path = csv_writer(
            self.usb_mount, self.device_id, self.header
        )
        self.logger.info("CollectorService initialized")


    # -----------------------------------------------------

    def _create_headers(self):
        pulse_columns = [f"pulse_{name}_count" for name, _ in self.counters]
        adc_columns = [f"adc_{channel}_voltage_v" for channel in self.adc_channels]
        return ["timestamp_utc"] + pulse_columns + adc_columns

    # -----------------------------------------------------

    def start(self):
        self.logger.info("CollectorService started")
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # -----------------------------------------------------

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

        try:
            self.file_handle.close()
        except Exception:
            pass

        self.logger.info("CollectorService stopped")

    # -----------------------------------------------------

    def _run(self):
        # next_heartbeat = time.time() + 60
        # start_time = time.time()

        while self._running:
            loop_started = time.time()

            try:
                # Amber walklight while collecting data
                self.ext_status_led.measuring()

                #timestamp_utc = datetime.now(timezone.utc).isoformat()
                timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                self.logger.info("Collecting data at %s", timestamp_utc)

                # Read out all pulse counters and reset for next interval
                pulse_values = [
                    counter.snapshot_and_reset()
                    for _, counter in self.counters
                ]

                # Read ADC values, apply calibration, and prepare for CSV
                adc_raw = self.adc_manager.read_all()
                adc_calibrated = apply_calibration(adc_raw, self.calibration)
                adc_values = [
                    adc_calibrated.get(channel)
                    for channel in self.adc_channels
                ]

                # Write CSV with last known values (even if ADC read failed)
                self.writer.writerow(
                    [timestamp_utc] + pulse_values + adc_values
                )
                self.file_handle.flush()
                os.fsync(self.file_handle.fileno())

                # IoT send — show upload status on LEDs
                if self.iot:
                    self.ext_status_led.uploading()
                    payload = {
                        "timestamp": timestamp_utc,
                        "pulses": {name: val for (name, _), val in zip(self.counters, pulse_values)},
                        "adc": dict(zip(self.adc_channels, adc_values)),
                    }
                    try:
                        self.iot.send("data", payload)
                        self.logger.info("IoT data sent successfully")
                        self.ext_status_led.upload_success()

                    except Exception:
                        self.logger.exception("IoT send failed")
                        self.ext_status_led.upload_error()
                else:
                    # No IoT — still confirm data cycle completed
                    self.ext_status_led.upload_success()

            except Exception:
                self.logger.exception("Collector loop crashed")

            # Sleep remaining interval
            elapsed = time.time() - loop_started
            sleep_duration = max(
                0.0, self.sampling_seconds - elapsed
            )
            time.sleep(sleep_duration)