
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


class ADCManager:
    """
    Manages multiple ADS1115Group instances.
    """

    def __init__(self, cfg_list: List[dict]):
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

    def read_all(self) -> Dict[str, float]:
        readings: Dict[str, float] = {}
        for grp in self.groups:
            readings.update(grp.read_voltages())
        return readings