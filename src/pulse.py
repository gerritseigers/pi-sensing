
import threading
import logging
import os

logger = logging.getLogger("pulse")

class PulseCounter:
    """
    PulseCounter counts pulses on a GPIO pin using either pigpio or RPi.GPIO.
    For testing on non-Pi systems, hardware-specific code is commented out.
    """
    def __init__(self, gpio, pull_up=True, falling=True, debounce_us=2000, backend_order=None):
        """
        Initialize the pulse counter.
        gpio: GPIO pin number
        pull_up: Use pull-up resistor
        falling: Count falling edge (else rising)
        debounce_us: Debounce time in microseconds
        """
        self.gpio = gpio
        self.pull_up = pull_up
        self.falling = falling
        self.debounce_us = debounce_us
        self.count = 0
        self._lock = threading.Lock()
        self._backend = None
        self._cb = None
        # Allow explicit backend order (list of strings) else defer to env var
        self._backend_order = backend_order

    def _cb_pigpio(self, gpio, level, tick):
        """
        Callback for pigpio backend.
        Increments count on correct edge.
        """
        if self.falling and level == 0 or (not self.falling and level == 1):
            with self._lock:
                self.count += 1

    def _cb_rpi(self, channel):
        """
        Callback for RPi.GPIO backend.
        Increments count.
        """
        with self._lock:
            self.count += 1

    def start(self):
        """Start pulse counting, trying backends in priority order.

        Backend order can be set via config passed externally (not yet) or
        environment variable GPIO_BACKENDS="pigpio,lgpio,rpi". An env var
        PULSE_SKIP_PIGPIO=1 forces skipping pigpio.
        """
        backend_order = self._backend_order or os.environ.get("GPIO_BACKENDS", "pigpio,lgpio,rpi").split(',')
        skip_pigpio = os.environ.get("PULSE_SKIP_PIGPIO") == "1"

        for backend in [b.strip() for b in backend_order]:
            if backend == "pigpio":
                if skip_pigpio:
                    logger.debug("Skipping pigpio due to PULSE_SKIP_PIGPIO=1")
                    continue
                try:
                    import pigpio, io, contextlib, sys
                    # fast test if daemon responsive
                    with contextlib.redirect_stdout(io.StringIO()):
                        pi = pigpio.pi()
                    if not pi.connected:
                        pi.stop()
                        logger.debug("pigpio daemon not connected; skipping pigpio backend")
                        continue
                    # Basic heuristic: if hardware revision unknown skip silently
                    try:
                        rev = pigpio.get_hardware_revision()
                        if rev == 0:  # pigpio returns 0 if not a Pi
                            pi.stop()
                            logger.debug("pigpio hardware revision 0 (non-Pi); skipping pigpio backend")
                            continue
                    except Exception:
                        pass
                    self._backend = ("pigpio", pi)
                    pud = pigpio.PUD_UP if self.pull_up else pigpio.PUD_DOWN
                    pi.set_mode(self.gpio, pigpio.INPUT)
                    pi.set_pull_up_down(self.gpio, pud)
                    edge = pigpio.FALLING_EDGE if self.falling else pigpio.RISING_EDGE
                    if self.debounce_us > 0:
                        pi.set_glitch_filter(self.gpio, self.debounce_us)
                    self._cb = pi.callback(self.gpio, edge, self._cb_pigpio)
                    logger.info(f"PulseCounter started on GPIO {self.gpio} using pigpio")
                    return
                except Exception as e:
                    logger.debug(f"pigpio backend failed: {e}")
                    continue
            elif backend == "lgpio":
                try:
                    import glob, lgpio
                    chips = sorted(glob.glob('/dev/gpiochip*'))
                    priority = os.environ.get('LGPIO_CHIP_PRIORITY')
                    if priority:
                        try:
                            ordered = []
                            desired = [int(x.strip()) for x in priority.split(',') if x.strip()]
                            # map desired to paths
                            path_map = {int(p.replace('/dev/gpiochip','')): p for p in chips}
                            for num in desired:
                                if num in path_map:
                                    ordered.append(path_map[num])
                            # append any remaining chips not listed
                            for p in chips:
                                if p not in ordered:
                                    ordered.append(p)
                            chips = ordered
                            logger.debug(f"lgpio: chip priority applied -> {[c.replace('/dev/gpiochip','') for c in chips]}")
                        except Exception as e_prio:
                            logger.debug(f"lgpio: priority parse failed: {e_prio}")
                    if not chips:
                        logger.debug("lgpio: no gpiochip devices present")
                        continue
                    claimed = False
                    for chip_path in chips:
                        chip_num = int(chip_path.replace('/dev/gpiochip',''))
                        try:
                            h = lgpio.gpiochip_open(chip_num)
                            flags = lgpio.SET_PULL_UP if self.pull_up else lgpio.SET_PULL_DOWN

                            def _lg_cb(chip, gpio, level, tick):
                                if level in (0, 1):
                                    if (self.falling and level == 0) or (not self.falling and level == 1):
                                        with self._lock:
                                            self.count += 1

                            # Attempt to claim this line number on this chip with pull set via flags
                            lgpio.gpio_claim_input(h, self.gpio, flags)
                            lgpio.gpio_set_debounce_micros(h, self.gpio, int(self.debounce_us))
                            edge = lgpio.FALLING_EDGE if self.falling else lgpio.RISING_EDGE
                            self._cb = lgpio.callback(h, self.gpio, edge, _lg_cb)
                            self._backend = ("lgpio", (h,))
                            logger.info(f"PulseCounter started on GPIO {self.gpio} using lgpio (chip {chip_num})")
                            claimed = True
                            break
                        except Exception as e_chip:
                            logger.debug(f"lgpio: chip {chip_num} claim failed for line {self.gpio}: {e_chip}")
                            try:
                                lgpio.gpiochip_close(h)
                            except Exception:
                                pass
                            continue
                    if claimed:
                        return
                    else:
                        logger.debug(f"lgpio backend: no chip accepted line {self.gpio}")
                        continue
                except Exception as e:
                    logger.debug(f"lgpio backend failed: {e}")
                    continue
            elif backend == "rpi":
                try:
                    import RPi.GPIO as GPIO
                    self._backend = ("rpi", GPIO)
                    GPIO.setmode(GPIO.BCM)
                    pud = GPIO.PUD_UP if self.pull_up else GPIO.PUD_DOWN
                    GPIO.setup(self.gpio, GPIO.IN, pull_up_down=pud)
                    btime = max(1, int(self.debounce_us / 1000))
                    edge = GPIO.FALLING if self.falling else GPIO.RISING
                    GPIO.add_event_detect(self.gpio, edge, callback=self._cb_rpi, bouncetime=btime)
                    logger.info(f"PulseCounter started on GPIO {self.gpio} using RPi.GPIO")
                    return
                except Exception as e:
                    logger.debug(f"RPi.GPIO backend failed: {e}")
                    continue

        logger.error(f"Failed to initialize any GPIO backend for GPIO {self.gpio}; pulse counting disabled")

    def snapshot_and_reset(self):
        """
        Return the current count and reset to zero.
        """
        with self._lock:
            c = self.count
            self.count = 0
            return c

    def stop(self):
        """
        Stop pulse counting and clean up resources.
        """
        if not self._backend:
            return
        name, b = self._backend
        if name == "pigpio":
            if self._cb:
                self._cb.cancel()
            b.stop()
            logger.info(f"PulseCounter on GPIO {self.gpio} stopped (pigpio)")
        elif name == "lgpio":
            try:
                import lgpio
                if self._cb:
                    try:
                        self._cb.cancel()
                    except Exception:
                        pass
                h = b[0]
                lgpio.gpiochip_close(h)
                logger.info(f"PulseCounter on GPIO {self.gpio} stopped (lgpio)")
            except Exception as e:
                logger.debug(f"lgpio cleanup failed: {e}")
        else:
            import RPi.GPIO as GPIO
            GPIO.cleanup(self.gpio)
            logger.info(f"PulseCounter on GPIO {self.gpio} stopped (RPi.GPIO)")