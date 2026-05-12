"""
LED status indicator for Raspberry Pi.

Supports ACT (green) LED on Pi 4/5 for status signaling:
- Heartbeat blink on each sample
- Rapid blink on error
- Restore default trigger on stop
"""

import logging
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("led")

# Common LED paths for Raspberry Pi
LED_PATHS = {
    "ACT": Path("/sys/class/leds/ACT"),
    "PWR": Path("/sys/class/leds/PWR"),
}


class StatusLED:
    """
    Control the built-in ACT LED for status indication.
    
    Patterns:
    - heartbeat(): Single short blink (data sample taken)
    - error(): Rapid triple blink (error occurred)
    - startup(): Long blink (service started)
    """

    def __init__(self, led_name: str = "ACT", enabled: bool = True):
        self.enabled = enabled
        self.led_path = LED_PATHS.get(led_name)
        self.original_trigger: Optional[str] = None
        self._lock = threading.Lock()
        
        if not self.enabled:
            logger.info("LED status indicator disabled")
            return
            
        if not self.led_path or not self.led_path.exists():
            logger.warning("LED %s not found, status indicator disabled", led_name)
            self.enabled = False
            return
        
        # Save original trigger to restore later
        try:
            trigger_path = self.led_path / "trigger"
            content = trigger_path.read_text()
            # Find the currently active trigger (marked with [brackets])
            for part in content.split():
                if part.startswith("[") and part.endswith("]"):
                    self.original_trigger = part[1:-1]
                    break
            
            # Set trigger to none for manual control
            trigger_path.write_text("none")
            logger.info("LED %s initialized (original trigger: %s)", led_name, self.original_trigger)
        except PermissionError:
            logger.warning("No permission to control LED %s (run as root or add user to gpio group)", led_name)
            self.enabled = False
        except Exception as exc:
            logger.warning("Failed to initialize LED %s: %s", led_name, exc)
            self.enabled = False

    def _set_brightness(self, value: int) -> None:
        """Set LED brightness (0=off, 1=on)."""
        if not self.enabled:
            return
        try:
            brightness_path = self.led_path / "brightness"
            brightness_path.write_text(str(value))
        except Exception:
            pass  # Silently ignore LED errors

    def _blink(self, on_ms: int, off_ms: int, count: int = 1) -> None:
        """Blink the LED with specified timing."""
        if not self.enabled:
            return
        with self._lock:
            for _ in range(count):
                self._set_brightness(1)
                time.sleep(on_ms / 1000.0)
                self._set_brightness(0)
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
        """Restore original LED trigger."""
        if not self.enabled or not self.original_trigger:
            return
        try:
            trigger_path = self.led_path / "trigger"
            trigger_path.write_text(self.original_trigger)
            logger.info("LED trigger restored to %s", self.original_trigger)
        except Exception as exc:
            logger.warning("Failed to restore LED trigger: %s", exc)


# Convenience functions for simple usage
_default_led: Optional[StatusLED] = None


def init_led(led_name: str = "ACT", enabled: bool = True) -> StatusLED:
    """Initialize the default LED controller."""
    global _default_led
    _default_led = StatusLED(led_name, enabled)
    return _default_led


def heartbeat() -> None:
    """Trigger heartbeat blink on default LED."""
    if _default_led:
        _default_led.heartbeat()


def error() -> None:
    """Trigger error blink on default LED."""
    if _default_led:
        _default_led.error()


def startup() -> None:
    """Trigger startup blink on default LED."""
    if _default_led:
        _default_led.startup()


def stop() -> None:
    """Stop and restore default LED."""
    if _default_led:
        _default_led.stop()
