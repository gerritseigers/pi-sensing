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
        self.connection_string = connection_string
        self.device_id = device_id
        self.client = None

    def start(self):
        if not IoTHubDeviceClient or not Message:
            logger.error("azure-iot-device niet geïnstalleerd; IoT Hub uitgeschakeld")
            return
        try:
            self.client = IoTHubDeviceClient.create_from_connection_string(self.connection_string)
            self.client.connect()
            logger.info("IoT Hub verbonden voor device %s", self.device_id)
        except Exception as exc:
            logger.error("IoT Hub connectie faalde: %s", exc)
            self.client = None

    def stop(self):
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
            logger.info("IoT Hub sessie afgesloten")
            self.client = None

    def send(self, msg_type: str, payload):
        if not self.client:
            return
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
        except Exception as exc:
            logger.error("IoT Hub send faalde (%s): %s", msg_type, exc)
