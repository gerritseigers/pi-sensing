
from typing import Dict, List
import time
import logging

import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn


# Gain mapping for ADS1115; defaults to 1 if an unsupported value is given.
GAIN_MAP = {2 / 3: 2 / 3, 1: 1, 2: 2, 4: 4, 8: 8, 16: 16}

logger = logging.getLogger("ads1115")


class ADS1115Group:
    """
    Represents a group of ADS1115 ADC channels.
    """

    def __init__(self, i2c, address, name, gain, channels: List[dict]):
        self.name = name
        self.ads = ADS1115(i2c, address=int(address))
        self.ads.gain = GAIN_MAP.get(float(gain), 1)
        self.inputs = {}
        logger.info("Init ADS1115 group %s addr=0x%02X gain=%s channels=%d", self.name, int(address), self.ads.gain, len(channels or []))
        for ch in channels or []:
            idx = int(ch["channel"])
            nm = ch["name"]
            samples = max(1, int(ch.get("samples", 1)))
            self.inputs[nm] = {"cfg": ch, "samples": samples, "ain": AnalogIn(self.ads, idx)}

    def read_voltages(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for name, meta in self.inputs.items():
            ain = meta["ain"]
            samples = meta["samples"]
            total = 0.0
            for _ in range(samples):
                total += ain.voltage
                if samples > 1:
                    time.sleep(0.005)
            out[name] = total / samples
            logger.debug("%s ch=%s samples=%d V=%.6f", self.name, name, samples, out[name])
        return out

    def read_raw_and_voltage(self) -> Dict[str, dict]:
        """
        Return both raw ADC counts and averaged voltage for each input.
        Structure: {name: {"raw": int, "voltage": float, "gain": float}}
        """
        out: Dict[str, dict] = {}
        for name, meta in self.inputs.items():
            ain = meta["ain"]
            samples = meta.get("samples", 1)
            total_v = 0.0
            total_raw = 0
            for _ in range(samples):
                # AnalogIn provides both .voltage and .value
                total_v += ain.voltage
                total_raw += getattr(ain, "value", 0)
                if samples > 1:
                    time.sleep(0.005)
            avg_v = total_v / samples
            avg_raw = int(total_raw / samples)
            out[name] = {"raw": avg_raw, "voltage": avg_v, "gain": getattr(self.ads, "gain", None)}
            logger.debug("%s ch=%s samples=%d raw=%d V=%.6f", self.name, name, samples, avg_raw, avg_v)
        return out


import threading
from collections import deque
from typing import Optional


class ADCManager:
    """
    Manages multiple ADS1115Group instances and samples them in a background thread.

    It keeps a small moving window per channel (deque) and exposes thread-safe
    averaged values via `read_all()` and `read_all_raw()`.

    Configuration: pass a list of ADC group dicts as before. Optional kwargs:
      - sample_interval_ms: sampling interval in milliseconds (default 200)
      - window_size: number of samples in moving window (default 5)
    """

    def __init__(self, cfg_list: List[dict], sample_interval_ms: int = 200, window_size: int = 5):
        self.i2c = busio.I2C(board.SCL, board.SDA)
        self.groups = [
            ADS1115Group(
                self.i2c,
                address=g.get("address", 0x48),
                name=g.get("name", "ads"),
                gain=g.get("gain", 1),
                channels=g.get("channels", []),
            )
            for g in (cfg_list or [])
        ]
        logger.info("ADCManager initialized with %d group(s)", len(self.groups))

        # Sampling configuration
        self.sample_interval_ms = max(10, int(sample_interval_ms))
        self.window_size = max(1, int(window_size))

        # prepopulate _data structure with empty deques for all channels to avoid key errors later
        self._data = {}
        self._lock = threading.Lock()
        for grp in self.groups:
            for name in grp.inputs.keys():
                self._data[name] = {
                    "raw": deque(maxlen=self.window_size),
                    "voltage": deque(maxlen=self.window_size),
                    "gain": grp.ads.gain,  # or None if you prefer
                }

        # Internal storage for recent samples: {channel: {"raw": deque, "voltage": deque, "gain": last_gain}}
        self._running = True
        self._thread: Optional[threading.Thread] = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self):
        """Background sampling loop: poll all groups and store samples."""
        sleep_s = self.sample_interval_ms / 1000.0
        while self._running:
            try:
                for grp in self.groups:
                    try:
                        readings = grp.read_raw_and_voltage()
                    except Exception:
                        readings = {}
                    with self._lock:
                        for name, meta in readings.items():
                            entry = self._data.get(name)
                            if not entry:
                                entry = {"raw": deque(maxlen=self.window_size), "voltage": deque(maxlen=self.window_size), "gain": meta.get("gain")}
                                self._data[name] = entry
                            entry["raw"].append(meta.get("raw"))
                            entry["voltage"].append(meta.get("voltage"))
                            entry["gain"] = meta.get("gain")

                time.sleep(sleep_s)
            except Exception:
                # Keep thread alive on transient errors
                time.sleep(sleep_s)

    def stop(self, timeout: Optional[float] = 1.0):
        """Stop the background sampler and wait for thread to finish (best-effort)."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)

    def read_all(self) -> Dict[str, float]:
        """Return averaged voltages per channel.

        Returns: {channel_name: averaged_voltage}
        """
        out: Dict[str, float] = {}
        with self._lock:
            for name, entry in self._data.items():
                vols = [v for v in entry["voltage"] if v is not None]
                out[name] = float(sum(vols) / len(vols)) if vols else None
        return out

    def read_all_raw(self) -> Dict[str, dict]:
        """Return averaged raw+voltage readings for all channels.

        Returns: {channel_name: {"raw": avg_raw, "voltage": avg_voltage, "gain": last_gain}}
        """
        out: Dict[str, dict] = {}
        with self._lock:
            for name, entry in self._data.items():
                raws = [r for r in entry["raw"] if r is not None]
                vols = [v for v in entry["voltage"] if v is not None]
                avg_raw = int(sum(raws) / len(raws)) if raws else None
                avg_volt = float(sum(vols) / len(vols)) if vols else None
                out[name] = {"raw": avg_raw, "voltage": avg_volt, "gain": entry.get("gain")}
        return out

    # Keep compatibility helper for manual single-shot reads (reads from hardware directly)
    def read_once(self) -> Dict[str, float]:
        readings: Dict[str, float] = {}
        for grp in self.groups:
            try:
                readings.update(grp.read_voltages())
            except Exception:
                pass
        return readings

    def get_channel_names(self) -> list[str]:
        return sorted(self._data.keys())