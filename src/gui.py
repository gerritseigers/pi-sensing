from pathlib import Path
import sys
import socket
import subprocess
from functools import partial

from PyQt5 import QtWidgets, QtCore

from ads1115_reader import ADCManager
from utils import load_config

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, adc_manager, parent=None):
        super().__init__(parent)
        self.adc_manager = adc_manager
        self.setWindowTitle("Pi Sensing - Diagnostics")
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        # Status group
        status_box = QtWidgets.QGroupBox("Connection & Network")
        status_layout = QtWidgets.QGridLayout()
        status_box.setLayout(status_layout)
        self.lbl_azure_time = QtWidgets.QLabel("-")
        self.lbl_azure_status = QtWidgets.QLabel("-")
        self.lbl_ip = QtWidgets.QLabel("-")
        self.lbl_wifi = QtWidgets.QLabel("-")
        status_layout.addWidget(QtWidgets.QLabel("Last Azure connect:"), 0, 0)
        status_layout.addWidget(self.lbl_azure_time, 0, 1)
        status_layout.addWidget(QtWidgets.QLabel("Azure status:"), 1, 0)
        status_layout.addWidget(self.lbl_azure_status, 1, 1)
        status_layout.addWidget(QtWidgets.QLabel("IP address:"), 2, 0)
        status_layout.addWidget(self.lbl_ip, 2, 1)
        status_layout.addWidget(QtWidgets.QLabel("WiFi SSID:"), 3, 0)
        status_layout.addWidget(self.lbl_wifi, 3, 1)

        layout.addWidget(status_box)

        # ADC table
        self.table = QtWidgets.QTableWidget(16, 3)
        self.table.setHorizontalHeaderLabels(["Channel", "Raw (HEX)", "Voltage (V)"])
        self.table.verticalHeader().setVisible(False)
        for r in range(16):
            item = QtWidgets.QTableWidgetItem(f"AIN{r}")
            item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
            self.table.setItem(r, 0, item)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem("-"))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem("-"))

        layout.addWidget(self.table)

        # Load config and ADC manager
        cfg = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else {}
        self.adc_manager = None
        try:
            self.adc_manager = ADCManager(cfg.get("i2c_adcs", []))
        except Exception as exc:
            print("ADC manager init failed:", exc)

        # Timer to refresh UI
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

    def refresh(self):
        self._update_network()
        self._update_azure_status()
        self._update_adc()

    def _update_network(self):
        # IP detection via UDP trick
        ip = "unknown"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
        self.lbl_ip.setText(ip)

        # Try iwgetid for SSID (may not be available)
        ssid = "unknown"
        try:
            res = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                ssid = res.stdout.strip() or "unknown"
        except Exception:
            pass
        self.lbl_wifi.setText(ssid)

    def _update_azure_status(self):
        # Parse collector.log for last IoT Hub connection messages
        logpath = Path(__file__).parent.parent / "collector.log"
        last_time = "-"
        status = "Unknown"
        if logpath.exists():
            try:
                for line in reversed(logpath.read_text(encoding="utf-8").splitlines()):
                    if "IoT Hub verbonden" in line:
                        last_time = (line.split("Z", 1)[0] + "Z") if "Z" in line else line
                        status = "Connected"
                        break
                    if "IoT Hub connectie faalde" in line or "IoT Hub connectie" in line:
                        last_time = (line.split("Z", 1)[0] + "Z") if "Z" in line else line
                        status = "Disconnected"
                        break
            except Exception:
                pass
        self.lbl_azure_time.setText(last_time)
        self.lbl_azure_status.setText(status)

    def _update_adc(self):
        if not self.adc_manager:
            return
        try:
            readings = self.adc_manager.read_all_raw()
        except Exception:
            readings = {}

        # Sort keys for stable ordering
        keys = sorted(readings.keys())
        # Fill table rows
        for r in range(16):
            if r < len(keys):
                name = keys[r]
                meta = readings[name]
                raw = meta.get("raw")
                v = meta.get("voltage")
                raw_hex = f"0x{raw & 0xFFFF:04X}" if raw is not None else "-"
                self.table.item(r, 0).setText(name)
                self.table.item(r, 1).setText(raw_hex)
                self.table.item(r, 2).setText(f"{v:.4f}" if v is not None else "-")
            else:
                # Empty row
                self.table.item(r, 1).setText("-")
                self.table.item(r, 2).setText("-")


# def main():
#     app = QtWidgets.QApplication(sys.argv)
#     w = MainWindow()
#     w.show()
#     sys.exit(app.exec_())


# if __name__ == "__main__":
#     main()
