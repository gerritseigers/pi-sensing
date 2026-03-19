"""
Dispatches status events to a single-colour GPIO LED and a NeoPixel ring.

Simple events (heartbeat, error, stop) go to both devices.
Rich measurement-cycle events are split: ring gets animations, GPIO LED gets a
simple proxy blink so both always show something meaningful.
Startup progress goes to the ring only (it supports colour; GPIO LED cannot).
"""

import logging


class StatusLedRing:
    """Smart dispatcher for GPIO single-colour LED + NeoPixel ring."""

    def __init__(self, gpio_led, ring_led):
        self._gpio = gpio_led   # ExtStatusLED
        self._ring = ring_led   # LedRing

    def _call(self, device, method, *args):
        if device is None:
            return
        fn = getattr(device, method, None)
        if callable(fn):
            try:
                fn(*args)
            except Exception:
                logging.getLogger("app").debug(
                    "LED dispatch %s.%s failed",
                    type(device).__name__, method, exc_info=True,
                )

    # ------------------------------------------------- both devices

    def heartbeat(self):
        self._call(self._gpio, "heartbeat")
        self._call(self._ring, "heartbeat")

    def error(self):
        self._call(self._gpio, "error")
        self._call(self._ring, "error")

    def startup(self):
        self._call(self._gpio, "startup")
        self._call(self._ring, "startup")

    def stop(self):
        self._call(self._gpio, "stop")
        self._call(self._ring, "stop")

    # ----------------------------------------- measurement cycle

    def measuring(self):
        """Ring: amber walklight. GPIO LED: single heartbeat blink."""
        self._call(self._gpio, "heartbeat")
        self._call(self._ring, "measuring")

    def uploading(self):
        """Ring: solid blue. GPIO LED: stays as-is."""
        self._call(self._ring, "uploading")

    def upload_success(self):
        """Ring: green 0.5 s then off. GPIO LED: stays as-is."""
        self._call(self._ring, "upload_success")

    def upload_error(self):
        """Ring: red blink 2 s. GPIO LED: error triple-blink."""
        self._call(self._gpio, "error")
        self._call(self._ring, "upload_error")

    # ------------------------------------------ startup progress (ring only)

    def startup_step(self, step: int, total: int, success: bool = True):
        """Light up ring LEDs for this init step (blue=ok, red=fail)."""
        self._call(self._ring, "startup_step", step, total, success)

    def startup_complete(self):
        """Full blue ring pulse then clear \u2014 all init stages done."""
        self._call(self._gpio, "startup")   # single long blink on GPIO LED
        self._call(self._ring, "startup_complete")
