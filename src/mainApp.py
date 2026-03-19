import os
import sys
from pathlib import Path
from PyQt5 import QtWidgets

from utils import load_config, setup_logger
from version import __version__
from ads1115_reader import ADCManager
from pulse import PulseCounter
from iot import IoTHubSender
import ext_led
import led_ring
from status_led_ring import StatusLedRing

from collector_service import CollectorService
from gui import MainWindow   # your GUI file

# -----------------------------
# Configuration path
# -----------------------------
CONFIG_PATH = os.environ.get("EDGE_CONFIG", str(Path(__file__).parent.parent / "config.yaml"))


def _has_connected_display() -> bool:
    """Return True if a DSI or HDMI connector reports a connected display."""
    for status_path in Path("/sys/class/drm").glob("*/status"):
        try:
            connector = status_path.parent.name
            if "DSI" not in connector and "HDMI" not in connector:
                continue
            if status_path.read_text().strip().lower() == "connected":
                return True
        except Exception:
            continue
    return False


def _detect_gui_environment(logger) -> bool:
    """Prefer an existing GUI session; otherwise fall back to offscreen headless mode."""
    display = os.environ.get("DISPLAY")
    if display:
        logger.info("Display detected via DISPLAY=%s", display)
        return True

    if not _has_connected_display():
        logger.info("No DSI/HDMI display detected; running headless")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        return False

    x_socket = Path("/tmp/.X11-unix/X0")
    x_authority = Path.home() / ".Xauthority"

    if x_socket.exists() and x_authority.exists():
        os.environ["DISPLAY"] = ":0"
        os.environ.setdefault("XAUTHORITY", str(x_authority))
        logger.info("Connected local display detected; using DISPLAY=:0")
        return True

    logger.info("Display hardware connected but no active X session found; running headless")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return False

# -----------------------------
# Puls counters initialization
# -----------------------------
def initialize_pulse_counters(pulse_configs, backend_order=None, logger=None):
    counters = []
    for pulse_cfg in pulse_configs:
        counter = PulseCounter(
            gpio=int(pulse_cfg["gpio"]),
            backend_order=backend_order,
            pull_up=True,
            falling=True,
            logger = logger
        )
        counter.start()
        counters.append((pulse_cfg["name"], counter))
        
    return counters

# -----------------------------
# Main application entry
# -----------------------------
def main():
    logger = setup_logger("app", logfile=str(Path(__file__).parent / "collector.log"))
    cfg = load_config(CONFIG_PATH)

    logger.info("Starting Pi Sensing application v%s", __version__)
    
    # -----------------------------
    # Create shared services (always active)
    # -----------------------------
    _adc_ok = False
    try:
        adc_manager = ADCManager(cfg.get("i2c_adcs", []))
        logger.info("ADCManager initialized with %d group(s)", len(adc_manager.groups))
        _adc_ok = True
    except Exception as e:
        logger.error("Failed to initialize ADCManager: %s", e)
        adc_manager = None
    
    counters = initialize_pulse_counters(cfg.get("pulses", []), backend_order=cfg.get("gpio_backends", []), logger=logger)
    _pulses_ok = bool(counters) or not cfg.get("pulses")

    ext_led_cfg = cfg.get("status_led", {})
    ext_led_enabled = bool(ext_led_cfg.get("enabled", False))
    ext_led_gpio = int(ext_led_cfg.get("gpio_pin", 23))
    ext_led_backend = ext_led_cfg.get("backend")
    ext_status_led = ext_led.init_ext_led(ext_led_gpio, ext_led_enabled, ext_led_backend)

    ring_cfg = cfg.get("led_ring", {})
    ring_enabled = bool(ring_cfg.get("enabled", False))
    ring_count = int(ring_cfg.get("led_count", 12))
    ring_brightness = float(ring_cfg.get("brightness", 0.375))

    ring_status_led = led_ring.init_led_ring(
        led_count=ring_count,
        brightness=ring_brightness,
        enabled=ring_enabled,
    )

    status_led = StatusLedRing(ext_status_led, ring_status_led)

    # --- Startup ring progress (4 steps = 3 LEDs each on a 12-pixel ring) ---
    _STARTUP_STEPS = 4
    status_led.startup_step(0, _STARTUP_STEPS, _adc_ok)        # ADC Manager
    status_led.startup_step(1, _STARTUP_STEPS, _pulses_ok)     # Pulse Counters

    # extract IoT settings for later user from yaml config, with safe defaults
    device_id = cfg.get("device", {}).get("id") or os.environ.get("DEVICE_ID") or "pi-node-01"
    iot_cfg = cfg.get("iot", {}) if isinstance(cfg, dict) else {}

    iot_enabled = bool(iot_cfg.get("enabled", True))
    heartbeat_seconds = int(iot_cfg.get("heartbeat_seconds", 60))
    send_settings_on_start = bool(iot_cfg.get("send_settings_on_start", True))
    iot_conn = os.environ.get("IOTHUB_DEVICE_CONNECTION_STRING", "")

    # IoT Hub client
    iot = None
    if iot_enabled and iot_conn:
        iot = IoTHubSender(iot_conn, device_id)
        iot.start()
        if send_settings_on_start:
            try:
                iot.send("settings", cfg)
            except Exception:
                logger.warning("IoT settingsbericht kon niet worden verstuurd")
    else:
        if iot_enabled:
            logger.warning("IoT Hub geactiveerd maar geen IOTHUB_DEVICE_CONNECTION_STRING; IoT uit")
    status_led.startup_step(2, _STARTUP_STEPS, iot is not None or not iot_enabled)  # IoT Hub

    # -----------------------------
    # GUI — create window now so it appears in log before collector starts.
    # app.exec_() (blocking) is called later, after collector is running.
    # -----------------------------
    gui_enabled = _detect_gui_environment(logger)
    app = None
    window = None
    if gui_enabled:
        logger.info("Display available — creating GUI window")
        app = QtWidgets.QApplication(sys.argv)
        window = MainWindow(adc_manager=adc_manager, logger=logger)
        window.show()
        window.adjustSize()
    else:
        logger.info("No display — running headless")

    # -----------------------------
    # Collector Service (always active, even without pulses or ADC, to handle CSV and IoT)
    # -----------------------------
    try:
        collector = CollectorService(
            cfg = cfg,
            adc_manager = adc_manager,
            counters = counters,
            ext_status_led = status_led,
            iot = iot,
            logger = logger
        )
        collector.start()
        logger.info("CollectorService started")
        status_led.startup_step(3, _STARTUP_STEPS, True)   # Collector Service
    except Exception as e:
        logger.error("Failed to initialize CollectorService: %s", e)
        collector = None
        status_led.startup_step(3, _STARTUP_STEPS, False)

    status_led.startup_complete()

    # -----------------------------
    # Hand control to Qt event loop (GUI) or keep-alive loop (headless)
    # -----------------------------
    if gui_enabled and app:
        exit_code = app.exec_()
    else:
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Headless mode interrupted by user")
        exit_code = 0

    # -----------------------------
    # CLEAN SHUTDOWN
    # -----------------------------

    if collector:
        collector.stop()
    status_led.stop()
    if adc_manager:
        adc_manager.stop()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()