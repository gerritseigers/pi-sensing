import json
import logging
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

    def start(self) -> bool:
        """
        @brief Establish connection to Azure IoT Hub.
        @return True if connection succeeded, False otherwise
        """
        if not IoTHubDeviceClient or not Message:
            logger.error("azure-iot-device niet geïnstalleerd; IoT Hub uitgeschakeld")
            return False
        try:
            self.client = IoTHubDeviceClient.create_from_connection_string(self.connection_string)
            self.client.connect()
            logger.info("IoT Hub verbonden voor device %s", self.device_id)
            return True
        except Exception as exc:
            logger.error("IoT Hub connectie faalde: %s", exc)
            self.client = None
            return False

    def stop(self):
        """
        @brief Disconnect from Azure IoT Hub and cleanup resources.
        """
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
            logger.info("IoT Hub sessie afgesloten")
            self.client = None

    def send(self, msg_type: str, payload) -> bool:
        """
        @brief Send a message to Azure IoT Hub.
        @param msg_type Message type (e.g., "data", "settings", "heartbeat")
        @param payload Message payload (will be JSON-serialized)
        @return True if send succeeded, False otherwise
        """
        if not self.client:
            return False
        body = {
            "type": msg_type,
            "deviceId": self.device_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        try:
            msg = Message(json.dumps(body))
            msg.content_encoding = "utf-8"
            msg.content_type = "application/json"
            self.client.send_message(msg)
            return True
        except Exception as exc:
            logger.error("IoT Hub send faalde (%s): %s", msg_type, exc)
            return False
