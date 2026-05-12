"""
Heartbeat service for Pi Sensing.

Sends periodic "I'm alive" messages to Azure IoT Hub at configurable intervals.
Runs as a background thread alongside the collector.
"""

import threading
import time
import logging

logger = logging.getLogger("heartbeat")


class HeartbeatService:
    """
    Background service that sends periodic heartbeat messages to IoT Hub.
    
    Tracks uptime and sends lightweight heartbeat messages at configurable intervals
    to signal that the collector is running, even when not actively sending data.
    """

    def __init__(self, cfg: dict, iot=None, logger=None):
        """
        @brief Initialize heartbeat service.
        @param cfg Configuration dictionary (must contain 'iot' section with heartbeat_seconds)
        @param iot IoTHubSender instance or None if IoT disabled
        @param logger Logger instance or None for default
        """
        self.cfg = cfg
        self.iot = iot
        self.logger = logger or logging.getLogger("heartbeat")

        self._running = False
        self._thread = None
        self._start_time = time.time()

        # Extract heartbeat configuration
        iot_cfg = cfg.get("iot", {}) if isinstance(cfg, dict) else {}
        self.heartbeat_enabled = bool(iot_cfg.get("enabled", True))
        self.heartbeat_seconds = int(iot_cfg.get("heartbeat_seconds", 60))

        if self.heartbeat_seconds <= 0:
            self.heartbeat_seconds = 60
            self.logger.info("HeartbeatService: invalid heartbeat_seconds; using default 60")

        self.logger.info("HeartbeatService initialized (interval=%d seconds)", self.heartbeat_seconds)

    def _get_uptime(self) -> int:
        """
        @brief Get uptime in seconds since service start.
        @return Uptime in seconds
        """
        return int(time.time() - self._start_time)

    def start(self):
        """
        @brief Start background heartbeat thread.
        """
        if self._running:
            self.logger.debug("HeartbeatService start ignored: already running")
            return

        if not self.heartbeat_enabled:
            self.logger.debug("HeartbeatService: heartbeat disabled in config")
            return

        if not self.iot:
            self.logger.debug("HeartbeatService: no IoT Hub sender available")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.logger.info("HeartbeatService started")

    def stop(self):
        """
        @brief Stop background heartbeat thread and cleanup.
        """
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self.logger.info("HeartbeatService stopped")

    def _run(self):
        """
        @brief Background heartbeat loop.
        
        Sends heartbeat messages at configured intervals.
        """
        # Sleep a bit to avoid thundering herd on startup
        time.sleep(self.heartbeat_seconds / 2)

        while self._running:
            try:
                uptime = self._get_uptime()
                payload = {"uptime_s": uptime}

                if self.iot:
                    sent = self.iot.send("heartbeat", payload)
                    if sent:
                        self.logger.debug("Heartbeat sent (uptime=%d seconds)", uptime)
                    else:
                        self.logger.warning("Heartbeat send failed; cloud unavailable")

            except Exception:
                self.logger.exception("Heartbeat send error")

            # Sleep for configured interval
            time.sleep(self.heartbeat_seconds)
