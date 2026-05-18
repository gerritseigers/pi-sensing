"""
NeoPixel LED ring status indicator for Raspberry Pi 5.

Uses adafruit-circuitpython-neopixel-spi via hardware SPI (GPIO10 / SPI0 MOSI).
rpi-ws281x does not support the Pi 5 RP1 chip; this library works without root.

Startup sequence:
  startup_step(step, total, success) — blue (ok) / red (fail) LED progress fill
    startup_complete()                 — solid green

Measurement cycle:
    measuring()       — blinking orange while collecting data
    measuring_problem() — magenta double-pulse while measurement read is degraded
    uploading()       — blinking orange while uploading
    upload_success()  — solid green
    upload_error()    — blinking red (persistent until next state)

Legacy compat (also called via StatusLedRing fan-out to ext GPIO LED):
  heartbeat() / error() / startup() / stop()
"""

import logging
import threading
import time
import math

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
        led_count: int = 3,
        brightness: float = 0.375,
        enabled: bool = True,
        pixel_order=None,
        # gpio_pin kept for API compatibility but ignored on Pi 5 (SPI uses GPIO10)
        gpio_pin: int = 10,
        **_kwargs,
    ):
        """
        @brief Initialize NeoPixel ring control via SPI.
        @param led_count Number of LEDs in ring (default 3)
        @param brightness LED brightness 0.0-1.0 (default 0.375)
        @param enabled Whether ring control is enabled
        @param pixel_order Pixel color order (GRB, RGB, GRBW, RGBW, etc.)
        @param gpio_pin Legacy parameter, ignored on Pi 5 (GPIO10 used for SPI MOSI)
        """
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
                pixel_order=pixel_order if pixel_order is not None else neopixel_spi.GRB,  # WS2812B 3-channel GRB
            )
            self._clear()
            logger.info("LED ring initialized: %d pixels via SPI MOSI (GPIO10)", self.led_count)
        except Exception as exc:
            logger.warning("Failed to initialize LED ring: %s", exc)
            self.enabled = False

    # ------------------------------------------------------------------ helpers

    def _start_animation(self, target, *args):
        """
        @brief Cancel any running animation and start a new daemon thread.
        @param target Function to run as animation
        @param args Arguments to pass to target function
        """
        self._cancel.set()
        if self._anim_thread and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=0.5)
        self._cancel.clear()
        self._anim_thread = threading.Thread(target=target, args=args, daemon=True)
        self._anim_thread.start()

    def _wheel(self, position: int):
        """
        @brief Generate colour from colour wheel.
        @param position Position 0-255 on colour wheel
        @return (R, G, B) colour tuple
        """
        position = 255 - (position % 256)
        if position < 85:
            return (255 - position * 3, 0, position * 3)
        if position < 170:
            position -= 85
            return (0, position * 3, 255 - position * 3)
        position -= 170
        return (position * 3, 255 - position * 3, 0)

    def _clear(self):
        """
        @brief Turn off all LEDs (black).
        """
        if not self.enabled or not self._pixels:
            return
        self._pixels.fill((0, 0, 0))
        self._pixels.show()

    def _fill(self, r: int, g: int, b: int):
        """
        @brief Fill all LEDs with solid colour.
        @param r Red component (0-255)
        @param g Green component (0-255)
        @param b Blue component (0-255)
        """
        if not self.enabled or not self._pixels:
            return
        self._pixels.fill((r, g, b))
        self._pixels.show()

    # -------------------------------------------------------- startup sequence

    def startup_step(self, step: int, total: int, success: bool = True):
        """
        @brief Signal initialization progress (blue=ok, red=fail).
        @param step Current step number (0-based)
        @param total Total number of initialization steps
        @param success True if this step succeeded, False for failure
        
        Fills LEDs proportionally across the ring for each step.
        Blue indicates success, red indicates failure.
        """
        if not self.enabled or not self._pixels:
            return
        if total <= 0:
            return

        # Map arbitrary startup step counts onto available LEDs.
        start_i = math.floor((step * self.led_count) / total)
        end_i = math.floor(((step + 1) * self.led_count) / total)
        if end_i <= start_i:
            end_i = min(self.led_count, start_i + 1)
        color = (0, 0, 255) if success else (255, 0, 0)
        with self._lock:
            for i in range(start_i, end_i):
                self._pixels[i] = color
            self._pixels.show()
        time.sleep(0.4)   # hold long enough for the user to see this step

    def startup_complete(self):
        """
        @brief Signal initialization complete (solid green).
        """
        if not self.enabled or not self._pixels:
            return
        self._cancel.set()
        if self._anim_thread and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=0.5)
        self._cancel.clear()
        with self._lock:
            self._pixels.fill((0, 255, 0))
            self._pixels.show()

    # ----------------------------------------- measurement cycle animations

    def _orange_blink_loop(self):
        """
        @brief Animation loop: blink orange at 2Hz until cancelled.
        """
        while not self._cancel.is_set():
            with self._lock:
                self._pixels.fill((255, 120, 0))
                self._pixels.show()
            if self._cancel.wait(timeout=0.25):
                break
            with self._lock:
                self._pixels.fill((0, 0, 0))
                self._pixels.show()
            if self._cancel.wait(timeout=0.25):
                break

    def measuring(self):
        """
        @brief Start orange blinking to indicate data collection in progress.
        """
        if not self.enabled or not self._pixels:
            return
        self._start_animation(self._orange_blink_loop)

    def _measuring_problem_anim(self):
        """
        @brief Animation loop: magenta double-pulse to indicate ADC read degradation.
        """
        warning = (255, 0, 180)
        while not self._cancel.is_set():
            for _ in range(2):
                with self._lock:
                    self._pixels.fill(warning)
                    self._pixels.show()
                if self._cancel.wait(timeout=0.12):
                    return
                with self._lock:
                    self._pixels.fill((0, 0, 0))
                    self._pixels.show()
                if self._cancel.wait(timeout=0.12):
                    return
            if self._cancel.wait(timeout=0.8):
                return

    def measuring_problem(self):
        """
        @brief Start magenta double-pulse animation to indicate measurement problems.
        """
        if not self.enabled or not self._pixels:
            return
        self._start_animation(self._measuring_problem_anim)

    def uploading(self):
        """
        @brief Start orange blinking to indicate cloud upload in progress.
        """
        if not self.enabled or not self._pixels:
            return
        self._start_animation(self._orange_blink_loop)

    def upload_success(self):
        """
        @brief Signal successful upload cycle (solid green).
        """
        if not self.enabled or not self._pixels:
            return
        self._cancel.set()
        if self._anim_thread and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=0.5)
        self._cancel.clear()
        with self._lock:
            self._pixels.fill((0, 255, 0))  # solid green
            self._pixels.show()

    def _error_anim(self):
        """
        @brief Animation loop: blink red at 2.5Hz until cancelled.
        """
        while not self._cancel.is_set():
            with self._lock:
                self._pixels.fill((255, 0, 0))  # red blink
                self._pixels.show()
            if self._cancel.wait(timeout=0.2):
                break
            with self._lock:
                self._pixels.fill((0, 0, 0))
                self._pixels.show()
            if self._cancel.wait(timeout=0.2):
                break
        if not self._cancel.is_set():
            with self._lock:
                self._pixels.fill((0, 0, 0))
                self._pixels.show()

    def upload_error(self):
        """
        @brief Signal upload error (blink red until next state).
        """
        if not self.enabled or not self._pixels:
            return
        self._start_animation(self._error_anim)

    # ---------------------------------------------------- legacy compat API

    def heartbeat(self):
        """
        @brief Legacy: show heartbeat by starting orange blink animation.
        """
        self.measuring()

    def error(self):
        """
        @brief Legacy: show error by starting red blink animation.
        """
        self.upload_error()

    def startup(self):
        """
        @brief Legacy no-op (startup handled via startup_step/startup_complete).
        """
        pass

    def stop(self):
        """
        @brief Stop animations and show solid green on shutdown.
        """
        if not self.enabled:
            return
        self._cancel.set()
        if self._anim_thread and self._anim_thread.is_alive():
            self._anim_thread.join(timeout=0.5)
        with self._lock:
            self._fill(0, 255, 0)


def init_led_ring(
    led_count: int = 3,
    brightness: float = 0.375,
    enabled: bool = True,
    pixel_order: str = "GRB",
    # Legacy kwargs from rpi-ws281x config accepted and ignored
    **_kwargs,
) -> "LedRing":
    """
    @brief Factory function to create and initialize a LedRing.
    @param led_count Number of LEDs in ring
    @param brightness LED brightness (0.0-1.0)
    @param enabled Whether ring control is enabled
    @param pixel_order Pixel colour order (GRB, RGB, GRBW, RGBW)
    @return LedRing instance (disabled if initialization fails)
    """
    _po = None
    if _neopixel_available:
        _order_map = {
            "GRB": neopixel_spi.GRB,
            "RGB": neopixel_spi.RGB,
            "GRBW": neopixel_spi.GRBW,
            "RGBW": neopixel_spi.RGBW,
        }
        _po = _order_map.get(str(pixel_order).upper(), neopixel_spi.GRB)
    try:
        return LedRing(led_count=led_count, brightness=brightness, enabled=enabled, pixel_order=_po)
    except Exception:
        logger.debug("init_led_ring: failed to create LedRing", exc_info=True)
        return LedRing(enabled=False)
