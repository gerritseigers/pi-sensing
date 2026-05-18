import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger("iot")

try:
    from azure.iot.device import IoTHubDeviceClient, Message
except ImportError:  # handled gracefully when dependency missing
    IoTHubDeviceClient = None
    Message = None


class IoTHubSender:
    """Thin wrapper around IoT Hub device client with simple JSON envelope.

    Envelope shape: {"type": str, "deviceId": str, "ts": iso8601, "payload": any}
    """

    def __init__(self, connection_string: str, device_id: str):
        """
        @brief Initialize IoT Hub sender with connection credentials.
        @param connection_string Azure IoT Hub device connection string
        @param device_id Device identifier for message envelope
        """
        self.connection_string = connection_string
        self.device_id = device_id
        self.client = None
        self._last_connect_attempt = 0.0
        self._reconnect_interval = max(
            5,
            int(os.environ.get("IOTHUB_RECONNECT_SECONDS", "30")),
        )
        self._connect_failures = 0
        self._late_reconnect_logged = False

    def start(self, force: bool = False) -> bool:
        """
        @brief Establish connection to Azure IoT Hub.
        @return True if connection succeeded, False otherwise
        """
        if self.client:
            return True

        now = time.time()
        if not force and (now - self._last_connect_attempt) < self._reconnect_interval:
            return False

        self._last_connect_attempt = now

        if not IoTHubDeviceClient or not Message:
            logger.error("azure-iot-device niet geïnstalleerd; IoT Hub uitgeschakeld")
            return False
        try:
            self.client = IoTHubDeviceClient.create_from_connection_string(self.connection_string)
            self.client.connect()
            if self._connect_failures > 0 and not self._late_reconnect_logged:
                logger.info("IoT Hub reconnected successfully after network/cloud outage")
                self._late_reconnect_logged = True
            logger.info("IoT Hub verbonden voor device %s", self.device_id)
            return True
        except Exception as exc:
            logger.error("IoT Hub connectie faalde: %s", exc)
            self.client = None
            self._connect_failures += 1
            return False

    def _build_message(self, msg_type: str, payload):
        body = {
            "type": msg_type,
            "deviceId": self.device_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        msg = Message(json.dumps(body))
        msg.content_encoding = "utf-8"
        msg.content_type = "application/json"
        return msg

    def _disconnect_silent(self):
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None

    def stop(self):
        """
        @brief Disconnect from Azure IoT Hub and cleanup resources.
        """
        if self.client:
            self._disconnect_silent()
            logger.info("IoT Hub sessie afgesloten")

    def send(self, msg_type: str, payload) -> bool:
        """
        @brief Send a message to Azure IoT Hub.
        @param msg_type Message type (e.g., "data", "settings", "heartbeat")
        @param payload Message payload (will be JSON-serialized)
        @return True if send succeeded, False otherwise
        """
        if not self.client and not self.start():
            return False

        try:
            self.client.send_message(self._build_message(msg_type, payload))
            return True
        except Exception as exc:
            logger.error("IoT Hub send faalde (%s): %s", msg_type, exc)
            # Assume broken connection; reconnect once and retry send.
            self._disconnect_silent()
            if not self.start(force=True):
                return False
            try:
                self.client.send_message(self._build_message(msg_type, payload))
                logger.info("IoT Hub send hersteld na reconnect (%s)", msg_type)
                return True
            except Exception as retry_exc:
                logger.error("IoT Hub retry faalde (%s): %s", msg_type, retry_exc)
                self._disconnect_silent()
                return False
