
# Dummy ADC reader for testing on non-Pi systems
from typing import Dict, List
from time import sleep
# import board, busio
# from adafruit_ads1x15.ads1115 import ADS1115
# from adafruit_ads1x15.analog_in import AnalogIn

# Gain mapping for ADS1115
GAIN_MAP = {2/3: 2/3, 1: 1, 2: 2, 4: 4, 8: 8, 16: 16}

class ADS1115Group:
    """
    Represents a group of ADS1115 ADC channels.
    Hardware-specific code is commented out for testing.
    """
    def __init__(self, i2c, address, name, gain, channels: List[dict]):
        self.name = name
        # self.ads = ADS1115(i2c, address=address)
        # self.ads.mode = ADS1115.MODE_CONTINUOUS
        # self.ads.gain = GAIN_MAP.get(gain, 1)
        self.inputs = {}
        # for ch in channels:
        #     idx = int(ch["channel"])
        #     nm = ch["name"]
        #     self.inputs[nm] = {"cfg": ch, "ain": AnalogIn(self.ads, getattr(ADS1115, f"P{idx}"))}
        pass

    def read_voltages(self) -> Dict[str, float]:
        """
        Read voltages from all ADC channels in the group.
        (Dummy implementation for testing.)
        """
        pass

class ADCManager:
    """
    Manages multiple ADS1115Group instances.
    Hardware-specific code is commented out for testing.
    """
    def __init__(self, cfg_list: List[dict]):
        # self.i2c = busio.I2C(board.SCL, board.SDA)
        # self.groups = [ADS1115Group(self.i2c, address=int(g["address"]), name=g["name"], gain=float(g.get("gain", 1)), channels=g.get("channels", [])) for g in (cfg_list or [])]
        pass

    def read_all(self) -> Dict[str, float]:
        """
        Read all voltages from all ADC groups.
        Returns dummy values for testing on non-Pi systems.
        """
        return {"volt_1": 0.0, "volt_2": 0.0, "volt_3": 0.0, "volt_4": 0.0}