import os
import sys
import logging
from pathlib import Path
from PyQt5 import QtWidgets

from utils import load_config, setup_logger
from ads1115_reader import ADCManager
from pulse import PulseCounter
from iot import IoTHubSender
import ext_led

from collector_service import CollectorService
from gui import MainWindow   # your GUI file

# -----------------------------
# Configuration path
# -----------------------------
CONFIG_PATH = os.environ.get("EDGE_CONFIG", str(Path(__file__).parent.parent / "config.yaml"))

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
    logger = setup_logger("app", logfile = "collector.log")
    cfg = load_config(CONFIG_PATH)

    logger.info("Starting Pi Sensing application")
    
    # -----------------------------
    # Create shared services (always active)
    # -----------------------------
    try:
        adc_manager = ADCManager(cfg.get("i2c_adcs", []))
        logger.info("ADCManager initialized with %d group(s)", len(adc_manager.groups))
    except Exception as e:
        logger.error("Failed to initialize ADCManager: %s", e)
        adc_manager = None
    
    counters = initialize_pulse_counters(cfg.get("pulses", []), backend_order=cfg.get("gpio_backends", []), logger=logger)

    ext_led_cfg = cfg.get("status_led", {})
    ext_led_enabled = bool(ext_led_cfg.get("enabled", False))
    ext_led_gpio = int(ext_led_cfg.get("gpio_pin", 22))  # Default to GPIO22 (pin 15) if not specified
    ext_led_backend = ext_led_cfg.get("backend")
    ext_status_led = ext_led.init_ext_led(ext_led_gpio, ext_led_enabled, ext_led_backend)
    ext_status_led.startup()
    ext_status_led.heartbeat()

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

    # -----------------------------
    # Collector Service (always active, even without pulses or ADC, to handle CSV and IoT)
    # -----------------------------
    try:
        collector = CollectorService(
            cfg = cfg,
            adc_manager = adc_manager,
            counters = counters,
            ext_status_led = ext_status_led,
            iot = iot,
            logger = logger
        )
        collector.start()
        
    except Exception as e:
        logger.error("Failed to initialize CollectorService: %s", e)
        collector = None

    # -----------------------------
    # GUI (MAIN THREAD) - only when display is available
    # -----------------------------
    has_display = bool(os.environ.get("DISPLAY"))
    running_ssh = bool(os.environ.get("SSH_CLIENT") or os.environ.get("SSH_TTY"))

    if not has_display:
        logger.info("No display detected")
        if running_ssh:
            logger.info("SSH session detected; forcing headless offscreen mode")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        gui_enabled = False
    else:
        gui_enabled = True
        logger.info("Display detected, GUI will start")

    # -----------------------------
    # GUI (MAIN THREAD) — only if display available
    # -----------------------------
    if gui_enabled:
        app = QtWidgets.QApplication(sys.argv)
        window = MainWindow(adc_manager=adc_manager)
        window.show()
        exit_code = app.exec_()
    else:
        logger.info("Running headless, main thread will keep services alive")
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
    if adc_manager:
        adc_manager.stop()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()