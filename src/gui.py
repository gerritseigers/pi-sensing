from pathlib import Path
import logging
import sys
import socket
import subprocess
from functools import partial

from PyQt5 import QtWidgets, QtCore

from ads1115_reader import ADCManager
from utils import load_config
from version import __version__

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, adc_manager, logger=None, parent=None):
        super().__init__(parent)
        self.adc_manager = adc_manager

        # Resolve log file path from the logger's FileHandler if available
        self._logpath = None
        if logger:
            for handler in logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    self._logpath = Path(handler.baseFilename)
                    break
        if not self._logpath:
            self._logpath = Path(__file__).parent / "collector.log"
        self.setWindowTitle(f"Pi Sensing v{__version__} - Diagnostics")
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
        status_layout.addWidget(QtWidgets.QLabel("Network:"), 3, 0)
        status_layout.addWidget(self.lbl_wifi, 3, 1)

        layout.addWidget(status_box)

        # ADC table — fixed 16 rows, window auto-sizes to show all without scrollbars
        cfg = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else {}
        self.adc_manager = None
        try:
            self.adc_manager = ADCManager(cfg.get("i2c_adcs", []))
        except Exception as exc:
            print("ADC manager init failed:", exc)

        self.table = QtWidgets.QTableWidget(16, 3)
        self.table.setHorizontalHeaderLabels(["Channel", "Raw (HEX)", "Voltage (V)"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        # Disable scrollbars so the table fully expands to show all rows
        self.table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
        self.table.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        for r in range(16):
            item = QtWidgets.QTableWidgetItem("-")
            item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
            self.table.setItem(r, 0, item)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem("-"))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem("-"))

        layout.addWidget(self.table)

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

        # Show active connection: WiFi SSID or Ethernet interface name
        connection = "unknown"
        try:
            res = subprocess.run(
                ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,STATE", "connection", "show", "--active"],
                capture_output=True, text=True, timeout=2,
            )
            if res.returncode == 0:
                for line in res.stdout.strip().splitlines():
                    parts = line.split(":")
                    if len(parts) >= 4 and parts[3] == "activated" and parts[1] != "loopback":
                        conn_type = parts[1]
                        device = parts[2]
                        if "wireless" in conn_type or "wifi" in conn_type:
                            # Try to get the SSID name
                            ssid_res = subprocess.run(
                                ["iwgetid", device, "-r"],
                                capture_output=True, text=True, timeout=1,
                            )
                            ssid = ssid_res.stdout.strip()
                            connection = ssid if ssid else device
                        else:
                            connection = device  # e.g. "eth0"
                        break
        except Exception:
            pass
        self.lbl_wifi.setText(connection)

    def _update_azure_status(self):
        last_time = "-"
        status = "Unknown"
        if self._logpath and self._logpath.exists():
            try:
                for line in reversed(self._logpath.read_text(encoding="utf-8").splitlines()):
                    if "IoT data sent successfully" in line:
                        last_time = (line.split("Z", 1)[0] + "Z") if "Z" in line else line
                        status = "Connected"
                        break
                    if "IoT send failed" in line or "IoT Hub" in line:
                        last_time = (line.split("Z", 1)[0] + "Z") if "Z" in line else line
                        status = "Error"
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

        # Sort keys numerically (e.g. volt_2 before volt_10)
        # enable sorted function when needed, currently order is as per config which is fine
        keys = list(readings.keys())
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
