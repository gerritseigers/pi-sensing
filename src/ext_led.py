"""
External Status LED control for Raspberry Pi GPIO pins.

Controls an external LED connected to a GPIO pin on the RP5 IO header.
Similar to StatusLED but uses GPIO digital output instead of built-in LED.

Patterns:
- heartbeat(): Single short blink (data sample taken)
- error(): Rapid triple blink (error occurred)
- startup(): Long blink (service started)
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("ext_led")

# Try to import available GPIO libraries
_gpio_lib = None
_gpio_backend = None

try:
    import lgpio
    _gpio_lib = "lgpio"
except ImportError:
    pass

if not _gpio_lib:
    try:
        import RPi.GPIO as GPIO
        _gpio_lib = "RPi.GPIO"
    except ImportError:
        pass

if not _gpio_lib:
    try:
        import pigpio
        _gpio_lib = "pigpio"
    except ImportError:
        pass


class ExtStatusLED:
    """
    Control an external LED on a GPIO pin for status indication.
    
    Supports multiple GPIO backends (lgpio, RPi.GPIO, pigpio).
    Default pin is GPIO27 (pin 13 on Raspberry Pi header).
    
    Patterns:
    - heartbeat(): Single short blink (data sample taken)
    - error(): Rapid triple blink (error occurred)
    - startup(): Long blink (service started)
    """

    def __init__(self, gpio_pin: int = 27, enabled: bool = True, backend: Optional[str] = None):
        """
        Initialize external status LED.
        
        Args:
            gpio_pin: GPIO pin number (BCM numbering). Default: 27 (pin 13)
            enabled: Whether LED control is enabled
            backend: GPIO backend to use ("lgpio", "RPi.GPIO", "pigpio"). Auto-detect if None.
        """
        self.enabled = enabled
        self.gpio_pin = gpio_pin
        self.backend = backend or _gpio_lib
        self._lock = threading.Lock()
        self._handle = None
        self._gpio = None
        
        if not self.enabled:
            logger.info("External LED status indicator disabled")
            return
        
        if not self.backend:
            logger.warning("No GPIO library available (install lgpio, RPi.GPIO, or pigpio)")
            self.enabled = False
            return
        
        try:
            self._init_gpio()
            logger.info("External LED initialized on GPIO%d using %s", gpio_pin, self.backend)
        except Exception as exc:
            logger.warning("Failed to initialize external LED on GPIO%d: %s", gpio_pin, exc)
            self.enabled = False

    def _init_gpio(self) -> None:
        """Initialize GPIO based on available backend."""
        if self.backend == "lgpio":
            import lgpio
            # Try to find available gpiochip
            self._handle = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_output(self._handle, self.gpio_pin)
            lgpio.gpio_write(self._handle, self.gpio_pin, 0)
            
        elif self.backend == "RPi.GPIO":
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpio_pin, GPIO.OUT)
            GPIO.output(self.gpio_pin, GPIO.LOW)
            
        elif self.backend == "pigpio":
            import pigpio
            self._handle = pigpio.pi()
            if not self._handle.connected:
                raise RuntimeError("pigpio daemon not running")
            self._handle.set_mode(self.gpio_pin, pigpio.OUTPUT)
            self._handle.write(self.gpio_pin, 0)
        else:
            raise ValueError(f"Unknown GPIO backend: {self.backend}")

    def _set_pin(self, state: int) -> None:
        """Set GPIO pin state (0=off, 1=on)."""
        if not self.enabled or self._handle is None and self._gpio is None:
            return
        try:
            if self.backend == "lgpio":
                import lgpio
                lgpio.gpio_write(self._handle, self.gpio_pin, state)
            elif self.backend == "RPi.GPIO":
                self._gpio.output(self.gpio_pin, state)
            elif self.backend == "pigpio":
                self._handle.write(self.gpio_pin, state)
        except Exception as exc:
            logger.debug("Failed to set GPIO%d: %s", self.gpio_pin, exc)

    def _blink(self, on_ms: int, off_ms: int, count: int = 1) -> None:
        """Blink the LED with specified timing."""
        if not self.enabled:
            return
        with self._lock:
            for _ in range(count):
                self._set_pin(1)
                time.sleep(on_ms / 1000.0)
                self._set_pin(0)
                if off_ms > 0:
                    time.sleep(off_ms / 1000.0)

    def heartbeat(self) -> None:
        """Single short blink indicating successful sample."""
        threading.Thread(target=self._blink, args=(50, 0, 1), daemon=True).start()

    def error(self) -> None:
        """Rapid triple blink indicating an error."""
        threading.Thread(target=self._blink, args=(100, 100, 3), daemon=True).start()

    def startup(self) -> None:
        """Long blink indicating service startup."""
        threading.Thread(target=self._blink, args=(500, 0, 1), daemon=True).start()

    def stop(self) -> None:
        """Clean up GPIO resources."""
        if not self.enabled:
            return
        try:
            self._set_pin(0)
            if self.backend == "lgpio" and self._handle is not None:
                import lgpio
                lgpio.gpiochip_close(self._handle)
            elif self.backend == "RPi.GPIO" and self._gpio is not None:
                self._gpio.cleanup(self.gpio_pin)
            elif self.backend == "pigpio" and self._handle is not None:
                self._handle.stop()
            logger.info("External LED cleaned up")
        except Exception as exc:
            logger.debug("Error during LED cleanup: %s", exc)
