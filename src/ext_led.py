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
        """
        @brief Initialize external status LED on GPIO pin.
        @param gpio_pin GPIO pin number (BCM numbering, default 27)
        @param enabled Whether LED control is enabled
        @param backend GPIO backend: "lgpio", "RPi.GPIO", or None for auto-detect
        """
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
        """
        @brief Initialize GPIO depending on backend.
        @throws ValueError if backend is unknown
        """
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
        """
        @brief Set the GPIO pin state (0=off, 1=on).
        @param state Pin state: 0 (low/off) or 1 (high/on)
        """
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
        """
        @brief Blink LED in a separate thread.
        @param on_ms Duration LED is on (milliseconds)
        @param off_ms Duration LED is off (milliseconds)
        @param count Number of blink cycles
        """
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
        """
        @brief Blink LED once (heartbeat pattern).
        """
        threading.Thread(target=self._blink, args=(250, 0, 1), daemon=True).start()

    def error(self):
        """
        @brief Blink LED three times rapidly (error pattern).
        """
        threading.Thread(target=self._blink, args=(100, 100, 3), daemon=True).start()

    def startup(self):
        """
        @brief Single long blink (startup pattern).
        """
        threading.Thread(target=self._blink, args=(500, 0, 1), daemon=True).start()

    def stop(self):
        """
        @brief Cleanup GPIO resources and turn off LED.
        """
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
    """
    @brief Compatibility wrapper to initialize external status LED.
    @param gpio_pin GPIO pin number (BCM numbering)
    @param enabled Whether LED control is enabled
    @param backend GPIO backend name or None for auto-detect
    @return ExtStatusLED instance (disabled if initialization fails)
    """
    try:
        return ExtStatusLED(gpio_pin=gpio_pin, enabled=enabled, backend=backend)
    except Exception:
        logger.debug("init_ext_led: failed to create ExtStatusLED", exc_info=True)
        return ExtStatusLED(enabled=False)