"""
External Status LED control for Raspberry Pi GPIO pins.

Controls an external LED connected to a GPIO pin on the RP5 IO header.
Uses lgpio as primary backend, RPi.GPIO as fallback.
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("ext_led")

# Try to import GPIO backends
_gpio_lib = None
try:
    import lgpio
    _gpio_lib = "lgpio"
except ImportError:
    try:
        import RPi.GPIO as GPIO
        _gpio_lib = "RPi.GPIO"
    except ImportError:
        _gpio_lib = None


class ExtStatusLED:
    """Control an external LED on a GPIO pin."""

    def __init__(self, gpio_pin: int = 27, enabled: bool = True, backend: Optional[str] = None):
        self.enabled = enabled
        self.gpio_pin = gpio_pin
        self.backend = backend or _gpio_lib
        self._lock = threading.Lock()
        self._handle = None
        self._gpio = None

        if not self.enabled:
            logger.info("External LED disabled")
            return

        if not self.backend:
            logger.warning("No GPIO library available (install lgpio or RPi.GPIO)")
            self.enabled = False
            return

        try:
            self._init_gpio()
            logger.info("LED initialized on GPIO%d using %s", self.gpio_pin, self.backend)
        except Exception as exc:
            logger.warning("Failed to initialize LED on GPIO%d: %s", self.gpio_pin, exc)
            self.enabled = False

    def _init_gpio(self):
        """Initialize GPIO depending on backend."""
        if self.backend == "lgpio":
            self._handle = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_output(self._handle, self.gpio_pin)
            lgpio.gpio_write(self._handle, self.gpio_pin, 0)
        elif self.backend == "RPi.GPIO":
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpio_pin, GPIO.OUT)
            GPIO.output(self.gpio_pin, GPIO.LOW)
        else:
            raise ValueError(f"Unknown GPIO backend: {self.backend}")

    def _set_pin(self, state: int):
        """Set the GPIO pin state (0=off, 1=on)."""
        if not self.enabled:
            return
        try:
            if self.backend == "lgpio":
                lgpio.gpio_write(self._handle, self.gpio_pin, state)
            elif self.backend == "RPi.GPIO":
                self._gpio.output(self.gpio_pin, state)
        except Exception as exc:
            logger.debug("Failed to set GPIO%d: %s", self.gpio_pin, exc)

    def _blink(self, on_ms: int, off_ms: int, count: int = 1):
        """Blink LED in a separate thread."""
        if not self.enabled:
            return
        with self._lock:
            for _ in range(count):
                self._set_pin(1)
                time.sleep(on_ms / 1000.0)
                self._set_pin(0)
                if off_ms > 0:
                    time.sleep(off_ms / 1000.0)

    # --- LED patterns ---
    def heartbeat(self):
        threading.Thread(target=self._blink, args=(250, 0, 1), daemon=True).start()

    def error(self):
        threading.Thread(target=self._blink, args=(100, 100, 3), daemon=True).start()

    def startup(self):
        threading.Thread(target=self._blink, args=(500, 0, 1), daemon=True).start()

    def stop(self):
        """Cleanup GPIO resources."""
        if not self.enabled:
            return
        try:
            self._set_pin(0)
            if self.backend == "lgpio" and self._handle:
                lgpio.gpiochip_close(self._handle)
            elif self.backend == "RPi.GPIO" and self._gpio:
                self._gpio.cleanup(self.gpio_pin)
            logger.info("LED cleaned up")
        except Exception as exc:
            logger.debug("Error during LED cleanup: %s", exc)


def init_ext_led(gpio_pin: int = 27, enabled: bool = True, backend: Optional[str] = None):
    """Compatibility wrapper."""
    try:
        return ExtStatusLED(gpio_pin=gpio_pin, enabled=enabled, backend=backend)
    except Exception:
        logger.debug("init_ext_led: failed to create ExtStatusLED", exc_info=True)
        return ExtStatusLED(enabled=False)