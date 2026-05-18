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
        """
        @brief Initialize status LED dispatcher for dual-LED setup.
        @param gpio_led ExtStatusLED instance (single-colour GPIO pin)
        @param ring_led LedRing instance (NeoPixel ring with RGB colours)
        """
        self._gpio = gpio_led   # ExtStatusLED
        self._ring = ring_led   # LedRing

    def _call(self, device, method, *args):
        """
        @brief Safely call a method on a device, catching and logging exceptions.
        @param device LED device instance (ExtStatusLED or LedRing)
        @param method Method name to call
        @param args Positional arguments for the method
        """
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
        """
        @brief Signal heartbeat on both LEDs (both devices show active status).
        """
        self._call(self._gpio, "heartbeat")
        self._call(self._ring, "heartbeat")

    def error(self):
        """
        @brief Signal error on both LEDs (both devices show error indication).
        """
        self._call(self._gpio, "error")
        self._call(self._ring, "error")

    def startup(self):
        """
        @brief Signal startup on both LEDs (initialization pattern).
        """
        self._call(self._gpio, "startup")
        self._call(self._ring, "startup")

    def stop(self):
        """
        @brief Stop both LEDs and cleanup resources.
        """
        self._call(self._gpio, "stop")
        self._call(self._ring, "stop")

    # ----------------------------------------- measurement cycle

    def measuring(self):
        """Ring: blinking orange. GPIO LED: single heartbeat blink.
        @brief Signal data collection in progress.
        """
        self._call(self._gpio, "heartbeat")
        self._call(self._ring, "measuring")

    def measuring_problem(self):
        """Ring: magenta double-pulse blink. GPIO LED: distinct warning blink.
        @brief Signal measurement read problems (e.g. ADC unavailable/invalid data).
        """
        self._call(self._gpio, "measuring_problem")
        self._call(self._ring, "measuring_problem")

    def uploading(self):
        """Ring: blinking orange. GPIO LED: stays as-is.
        @brief Signal data upload in progress (ring only).
        """
        self._call(self._ring, "uploading")

    def upload_success(self):
        """Ring: solid green. GPIO LED: stays as-is.
        @brief Signal successful upload (ring only).
        """
        self._call(self._ring, "upload_success")

    def upload_error(self):
        """Ring: red blink. GPIO LED: error triple-blink.
        @brief Signal upload error on both LEDs.
        """
        self._call(self._gpio, "error")
        self._call(self._ring, "upload_error")

    # ------------------------------------------ startup progress (ring only)

    def startup_step(self, step: int, total: int, success: bool = True):
        """Light up ring LEDs for this init step (blue=ok, red=fail).
        @brief Signal initialization progress step (ring only).
        @param step Current step number (0-based)
        @param total Total number of steps
        @param success True if this step succeeded, False for failure
        """
        self._call(self._ring, "startup_step", step, total, success)

    def startup_complete(self):
        """Full blue ring pulse then clear — all init stages done.
        @brief Signal initialization complete (both LEDs).
        """
        self._call(self._gpio, "startup")   # single long blink on GPIO LED
        self._call(self._ring, "startup_complete")
