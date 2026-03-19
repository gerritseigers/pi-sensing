"""
NeoPixel LED ring status indicator for Raspberry Pi 5.

Uses adafruit-circuitpython-neopixel-spi via hardware SPI (GPIO10 / SPI0 MOSI).
rpi-ws281x does not support the Pi 5 RP1 chip; this library works without root.

Startup sequence:
  startup_step(step, total, success) — blue (ok) / red (fail) LED progress fill
  startup_complete()                 — full blue pulse then clear

Measurement cycle:
  measuring()       — amber walklight while collecting data
  uploading()       — solid blue ring while sending to cloud
  upload_success()  — solid green ring for 0.5 s then off
  upload_error()    — blinking red for 2 s then off

Legacy compat (also called via StatusLedRing fan-out to ext GPIO LED):
  heartbeat() / error() / startup() / stop()
"""

import logging
import threading
import time

logger = logging.getLogger("led_ring")

try:
    import board
    import busio
    import neopixel_spi
    _neopixel_available = True
except ImportError:
    _neopixel_available = False


class LedRing:
    """Control a WS281x NeoPixel ring on Raspberry Pi 5 via SPI MOSI (GPIO10)."""

    def __init__(
        self,
        led_count: int = 12,
        brightness: float = 0.375,
        enabled: bool = True,
        pixel_order=None,
        # gpio_pin kept for API compatibility but ignored on Pi 5 (SPI uses GPIO10)
        gpio_pin: int = 10,
        **_kwargs,
    ):
        self.enabled = enabled
        self.led_count = led_count
        self.brightness = max(0.0, min(1.0, float(brightness) if brightness <= 1.0 else brightness / 255.0))

        self._lock = threading.Lock()
        self._pixels = None
        self._cancel = threading.Event()
        self._anim_thread = None

        if not self.enabled:
            logger.info("LED ring disabled")
            return

        if not _neopixel_available:
            logger.warning(
                "adafruit-circuitpython-neopixel-spi not available; "
                "install with: pip install adafruit-circuitpython-neopixel-spi"
            )
            self.enabled = False
            return

        try:
            spi = busio.SPI(board.SCLK, MOSI=board.MOSI)
            self._pixels = neopixel_spi.NeoPixel_SPI(
                spi,
                self.led_count,
                brightness=self.brightness,
                auto_write=False,
                pixel_order=pixel_order or neopixel_spi.GRBW,  # 4-channel RGBW ring
            )
            self._clear()
            logger.info("LED ring initialized: %d pixels via SPI MOSI (GPIO10)", self.led_count)
        except Exception as exc:
            logger.warning("Failed to initialize LED ring: %s", exc)
            self.enabled = False

    # ------------------------------------------------------------------ helpers

    def _start_animation(self, target, *args):
        """Cancel any running animation and start a new daemon thread."""
        self._cancel.set()
        if self._anim_thread and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=0.5)
        self._cancel.clear()
        self._anim_thread = threading.Thread(target=target, args=args, daemon=True)
        self._anim_thread.start()

    def _wheel(self, position: int):
        """Colour wheel — returns (R, G, B, W) tuple for position 0-255."""
        position = 255 - (position % 256)
        if position < 85:
            return (255 - position * 3, 0, position * 3, 0)
        if position < 170:
            position -= 85
            return (0, position * 3, 255 - position * 3, 0)
        position -= 170
        return (position * 3, 255 - position * 3, 0, 0)

    def _clear(self):
        if not self.enabled or not self._pixels:
            return
        self._pixels.fill((0, 0, 0, 0))
        self._pixels.show()

    def _fill(self, r: int, g: int, b: int, w: int = 0):
        if not self.enabled or not self._pixels:
            return
        self._pixels.fill((r, g, b, w))
        self._pixels.show()

    # -------------------------------------------------------- startup sequence

    def startup_step(self, step: int, total: int, success: bool = True):
        """
        Light up the ring LEDs for this init step.
        Blue = component OK, Red = component failed.
        Divides the ring evenly across `total` steps.
        Called directly from the main thread (not threaded).
        """
        if not self.enabled or not self._pixels:
            return
        leds_per_step = max(1, self.led_count // total)
        start_i = step * leds_per_step
        end_i = start_i + leds_per_step if step < total - 1 else self.led_count
        color = (0, 0, 255, 0) if success else (255, 0, 0, 0)
        with self._lock:
            for i in range(start_i, end_i):
                self._pixels[i] = color
            self._pixels.show()
        time.sleep(0.4)   # hold long enough for the user to see this step

    def startup_complete(self):
        """Pulse the full ring blue to signal all init stages done, then clear."""
        if not self.enabled or not self._pixels:
            return
        with self._lock:
            self._pixels.fill((0, 0, 255, 0))
            self._pixels.show()
        time.sleep(1.0)   # let the full-blue ring burn for a second
        with self._lock:
            self._pixels.fill((0, 0, 0, 0))
            self._pixels.show()

    # ----------------------------------------- measurement cycle animations

    def _measuring_loop(self):
        """Amber walklight that loops until _cancel is set."""
        step = 0
        while not self._cancel.is_set():
            pixel = step % self.led_count
            with self._lock:
                self._pixels.fill((0, 0, 0, 0))
                self._pixels[pixel] = (255, 160, 0, 0)  # amber, W=0
                self._pixels.show()
            step += 1
            self._cancel.wait(timeout=0.07)

    def measuring(self):
        """Start amber walklight — data collection in progress."""
        if not self.enabled or not self._pixels:
            return
        self._start_animation(self._measuring_loop)

    def uploading(self):
        """Stop measuring, fill ring solid blue — sending to cloud."""
        if not self.enabled or not self._pixels:
            return
        self._cancel.set()
        if self._anim_thread and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=0.5)
        self._cancel.clear()
        with self._lock:
            self._pixels.fill((0, 0, 255, 0))  # solid blue — uploading
            self._pixels.show()
        time.sleep(0.3)   # make blue visible before success/error follows

    def _success_anim(self):
        with self._lock:
            self._pixels.fill((0, 255, 0, 0))  # solid green
            self._pixels.show()
        self._cancel.wait(timeout=1.0)   # hold green for 1 s
        with self._lock:
            self._pixels.fill((0, 0, 0, 0))
            self._pixels.show()

    def upload_success(self):
        """Solid green ring for 0.5 s then off — cloud send succeeded."""
        if not self.enabled or not self._pixels:
            return
        self._start_animation(self._success_anim)

    def _error_anim(self):
        deadline = time.time() + 2.0
        while not self._cancel.is_set() and time.time() < deadline:
            with self._lock:
                self._pixels.fill((255, 0, 0, 0))  # red blink
                self._pixels.show()
            if self._cancel.wait(timeout=0.2):
                break
            with self._lock:
                self._pixels.fill((0, 0, 0, 0))
                self._pixels.show()
            if self._cancel.wait(timeout=0.2):
                break
        with self._lock:
            self._pixels.fill((0, 0, 0, 0))
            self._pixels.show()

    def upload_error(self):
        """Blink red for 2 s then off — cloud send failed."""
        if not self.enabled or not self._pixels:
            return
        self._start_animation(self._error_anim)

    # ---------------------------------------------------- legacy compat API

    def heartbeat(self):
        """Delegates to measuring() — amber walklight."""
        self.measuring()

    def error(self):
        """Delegates to upload_error() — red blink 2 s."""
        self.upload_error()

    def startup(self):
        """Legacy no-op — startup is handled via startup_step/startup_complete."""
        pass

    def stop(self):
        """Shutdown — solid green then off."""
        if not self.enabled:
            return
        self._cancel.set()
        if self._anim_thread and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=0.5)
        with self._lock:
            self._fill(0, 255, 0, 0)


def init_led_ring(
    led_count: int = 12,
    brightness: float = 0.375,
    enabled: bool = True,
    # Legacy kwargs from rpi-ws281x config accepted and ignored
    **_kwargs,
) -> "LedRing":
    """Factory wrapper for constructing LedRing."""
    try:
        return LedRing(led_count=led_count, brightness=brightness, enabled=enabled)
    except Exception:
        logger.debug("init_led_ring: failed to create LedRing", exc_info=True)
        return LedRing(enabled=False)
