import threading
import time
import os
import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path
import logging

from utils import (
    apply_calibration,
    csv_writer,
    pick_storage_target,
    resolve_storage_root,
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
        """
        @brief Initialize data collector service.
        @param cfg Configuration dictionary
        @param adc_manager ADCManager instance
        @param counters List of (name, PulseCounter) tuples
        @param ext_status_led StatusLedRing instance for LED control
        @param iot IoTHubSender instance or None if IoT disabled
        @param usb_mount Preferred USB mount point
        @param logger Logger instance or None for default
        """
        self.cfg = cfg
        self.adc_manager = adc_manager
        self.counters = counters
        self.ext_status_led = ext_status_led
        self.iot = iot
        self.logger = logger or logging.getLogger("collector")

        self._running = False
        self._thread = None

        self.sampling_seconds = int(cfg.get("sampling_seconds", 60))
        self.calibration = cfg.get("calibration", {})
        iot_cfg = cfg.get("iot", {}) if isinstance(cfg, dict) else {}
        self.iot_enabled = bool(iot_cfg.get("enabled", True))
        # Device ID from config or env, used for file naming and IoT messages
        self.device_id = (
            cfg.get("device", {}).get("id")
            or os.environ.get("DEVICE_ID")
            or "pi-node-01"
        )

        preferred_mount = Path(os.environ.get("USB_MOUNT", str(usb_mount)))
        default_fallback = Path(__file__).resolve().parent.parent / "usb-data"
        fallback_mount = Path(os.environ.get("USB_MOUNT_FALLBACK", str(default_fallback)))
        self._preferred_mount = preferred_mount
        self._fallback_mount = fallback_mount
        self.usb_mount = pick_storage_target(self._preferred_mount, self._fallback_mount, logger=self.logger)
        if self.usb_mount == self._fallback_mount:
            # Keep existing explicit warning path for visibility when preferred path fails.
            self.usb_mount = resolve_storage_root(self._preferred_mount, self._fallback_mount, logger=self.logger)

        # Setup CSV
        self.adc_channels = adc_manager.get_channel_names()
        self.header = self._create_headers()
        self._open_csv_writer(self.usb_mount)
        self.logger.info("CollectorService initialized")


    # -----------------------------------------------------

    def _create_headers(self):
        pulse_columns = [f"pulse_{name}_count" for name, _ in self.counters]
        adc_columns = [f"adc_{channel}_voltage_v" for channel in self.adc_channels]
        return ["timestamp_utc"] + pulse_columns + adc_columns

    def _open_csv_writer(self, root: Path):
        self.file_handle, self.writer, self.csv_path = csv_writer(root, self.device_id, self.header)

    def _close_csv_writer(self):
        try:
            self.file_handle.close()
        except Exception:
            pass

    def _refresh_storage_target(self):
        target = pick_storage_target(self._preferred_mount, self._fallback_mount, logger=self.logger)
        if target == self.usb_mount:
            return

        prev = self.usb_mount
        self._close_csv_writer()
        if prev == self._fallback_mount and target != self._fallback_mount:
            self._sync_local_to_usb(target)
        self.usb_mount = target
        self._open_csv_writer(self.usb_mount)
        self.logger.info("Storage target switched: %s -> %s", prev, self.usb_mount)

    def _merge_csv_rows_by_timestamp(self, src_csv: Path, dst_csv: Path):
        """
        Merge rows from src into dst, deduplicating by timestamp (column 0).
        """
        existing_ts = set()
        try:
            with open(dst_csv, newline="") as f_dst:
                rdr = csv.reader(f_dst)
                next(rdr, None)  # header
                for row in rdr:
                    if row:
                        existing_ts.add(row[0])
        except FileNotFoundError:
            shutil.copy2(src_csv, dst_csv)
            return

        rows_to_add = []
        with open(src_csv, newline="") as f_src:
            rdr = csv.reader(f_src)
            next(rdr, None)  # header
            for row in rdr:
                if not row:
                    continue
                ts = row[0]
                if ts in existing_ts:
                    continue
                rows_to_add.append(row)
                existing_ts.add(ts)

        if rows_to_add:
            with open(dst_csv, "a", newline="") as f_dst:
                w = csv.writer(f_dst)
                w.writerows(rows_to_add)

    def _sync_local_to_usb(self, usb_root: Path):
        """
        Copy historical CSV data one-way from local fallback to USB.
        Existing destination CSV files are merged by timestamp.
        """
        if self._fallback_mount == usb_root:
            return

        if not self._fallback_mount.exists():
            return

        synced = 0
        merged = 0

        for src_csv in sorted(self._fallback_mount.glob("*.csv")):
            dst_csv = usb_root / src_csv.name
            if not dst_csv.exists():
                shutil.copy2(src_csv, dst_csv)
                synced += 1
            else:
                before = dst_csv.stat().st_size
                self._merge_csv_rows_by_timestamp(src_csv, dst_csv)
                after = dst_csv.stat().st_size
                if after > before:
                    merged += 1

        # Keep upload marker state aligned where possible.
        for src_ok in sorted(self._fallback_mount.glob("*.csv.ok")):
            dst_ok = usb_root / src_ok.name
            if not dst_ok.exists():
                shutil.copy2(src_ok, dst_ok)

        if synced or merged:
            self.logger.info(
                "Synced local data to USB: copied=%d merged=%d source=%s target=%s",
                synced,
                merged,
                self._fallback_mount,
                usb_root,
            )

    # -----------------------------------------------------

    def start(self):
        """
        @brief Start background data collection thread.
        """
        if self._running:
            self.logger.debug("CollectorService start ignored: already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.logger.info("CollectorService started")

    # -----------------------------------------------------

    def stop(self):
        """
        @brief Stop background data collection thread and cleanup resources.
        """
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

        self._close_csv_writer()

        self.logger.info("CollectorService stopped")

    # -----------------------------------------------------

    def _run(self):
        # next_heartbeat = time.time() + 60
        # start_time = time.time()

        while self._running:
            loop_started = time.time()

            try:
                # Re-evaluate writable storage each cycle; switch to USB automatically when available.
                self._refresh_storage_target()

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
                row = [timestamp_utc] + pulse_values + adc_values
                try:
                    self.writer.writerow(row)
                    self.file_handle.flush()
                    os.fsync(self.file_handle.fileno())
                except Exception:
                    # Storage may have disappeared mid-write; switch target and retry once.
                    self.logger.exception("Primary write failed; retrying on available storage")
                    self._refresh_storage_target()
                    self.writer.writerow(row)
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
                        sent = self.iot.send("data", payload)
                        if sent:
                            self.logger.info("IoT data sent successfully")
                            self.ext_status_led.upload_success()
                        else:
                            self.logger.warning("IoT data not sent; cloud connection unavailable")
                            # Keep orange (uploading) to indicate pending cloud connectivity.
                            self.ext_status_led.uploading()

                    except Exception:
                        self.logger.exception("IoT send failed")
                        self.ext_status_led.upload_error()
                else:
                    if self.iot_enabled:
                        # Cloud is expected but unavailable: keep pending/failure indication (orange).
                        self.logger.warning("IoT enabled but sender unavailable; cloud upload pending")
                        self.ext_status_led.uploading()
                    else:
                        # IoT intentionally disabled: local collection cycle is successful.
                        self.ext_status_led.upload_success()

            except Exception:
                self.logger.exception("Collector loop crashed")
                self.ext_status_led.error()

            # Sleep remaining interval
            elapsed = time.time() - loop_started
            sleep_duration = max(
                0.0, self.sampling_seconds - elapsed
            )
            time.sleep(sleep_duration)