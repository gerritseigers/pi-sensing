# Pi Sensing Setup Guide

This guide will help you set up your Raspberry Pi for the Pi Edge Sensing project from scratch.

## 1. Update and install dependencies
```bash
sudo apt-get update
sudo apt-get upgrade
sudo apt-get install python3-pip python3-venv git build-essential swig python3-dev libffi-dev
```

If the `pigpio` package is not available via apt on your distribution (Debian Trixie), you'll build it from source later.

## 2. Clone your project (if not already present)
```bash
git clone <your-repo-url> ~/Projects/pi-sensing
cd ~/Projects/pi-sensing
```

## 3. Set up Python environment and install requirements
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install adafruit-circuitpython-dht adafruit-blinka
```

### (Optional) Install additional GPIO libraries
If you need pigpio Python bindings:
```bash
pip install pigpio
```
If you use lgpio backend:
```bash
pip install lgpio
```

## 4. Prepare USB data directory
```bash
sudo mkdir -p /mnt/usb-data
sudo chown $USER:$USER /mnt/usb-data
sudo chmod u+w /mnt/usb-data
```

## 5. Configure systemd services
Copy the service and timer files:
```bash
sudo cp systemd/data-collector.service /etc/systemd/system/
sudo cp systemd/azure-upload.service /etc/systemd/system/
sudo cp systemd/azure-upload.timer /etc/systemd/system/
```
Reload systemd:
```bash
sudo systemctl daemon-reload
```
Enable and start services:
```bash
sudo systemctl enable data-collector.service
sudo systemctl start data-collector.service
sudo systemctl enable azure-upload.timer
sudo systemctl start azure-upload.timer
```

### Enable pigpiod daemon (if using pigpio backend)
Pigpio may not have a packaged daemon. Build & install from source:
```bash
cd ~/Projects/pi-sensing
git clone https://github.com/joan2937/pigpio.git
cd pigpio
make
sudo make install
sudo ldconfig
```
Create and install systemd unit:
```bash
sudo cp ~/Projects/pi-sensing/systemd/pigpiod.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pigpiod
sudo systemctl start pigpiod
```
Check daemon:
```bash
systemctl status pigpiod || pgrep -a pigpiod
```

## 6. Check status and logs
```bash
sudo systemctl status data-collector.service
sudo systemctl status azure-upload.timer
sudo journalctl -u data-collector.service
sudo journalctl -u azure-upload.service
```

## 7. Azure setup
- Ensure your `.env` file or environment variables are set for Azure credentials.
- Check your Azure Blob container for uploaded files.

---
## 8. Configuration options
Edit `config.yaml` to adjust behavior. Example keys:
```yaml
sampling_seconds: 60
pulses_enabled: true            # set false to disable pulse counting if GPIO backends fail
dht_enabled: true               # set false to skip DHT22 sensor entirely
gpio_backends: [pigpio, lgpio, rpi]  # priority order for pulse counter backends
```

## 9. Troubleshooting GPIO & DHT

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Cannot determine SOC peripheral base address` | RPi.GPIO cannot detect hardware (/dev/gpiomem missing) | Use pigpio/lgpio backends; build pigpio; ensure running on Raspberry Pi OS; disable unsupported overlays |
| `Can't connect to pigpio` | pigpiod not running | Start daemon `sudo pigpiod` or enable systemd unit |
| `Unable to set line to input` (lgpio) | GPIO line already claimed or overlay conflict | Check overlays `grep -i w1-gpio /boot/config.txt`; free GPIO or move sensor |
| DHT always NaN | Wrong pin wiring / missing pull-up | Use physical pin 7 (GPIO4); add 10kΩ resistor VCC–DATA if bare sensor |

### Check device nodes
```bash
ls -l /dev/gpiochip* /dev/gpiomem || echo gpiomem missing
```
### Test pigpio
```bash
python - <<'EOF'
import pigpio
pi=pigpio.pi(); print('Connected?', pi.connected); pi.stop()
EOF
```
### Test lgpio
```bash
python - <<'EOF'
import lgpio
h=lgpio.gpiochip_open(0)
lgpio.gpio_claim_input(h,4)
print('GPIO4 claim OK')
lgpio.gpiochip_close(h)
EOF
```

### Force Blinka board detection
If board not detected set in `.env`:
```
BLINKA_FORCEBOARD=RaspberryPi
```

### Disable pulses if backend unavailable
Set `pulses_enabled: false` in `config.yaml` to skip pulse counter initialization while debugging DHT.

### Disable DHT sensor
Set `dht_enabled: false` if the sensor is not wired or is unstable. The collector will also auto-disable DHT (and pulses) if `/dev/gpiomem` is missing.

### GPIO backend detection
The collector now logs detected gpiochip devices (e.g. `/dev/gpiochip0,/dev/gpiochip4,...`). Pulse counting only auto-disables if no `gpiochip*` devices exist. Absence of `/dev/gpiomem` no longer blocks lgpio operation.

### Recovering missing /dev/gpiomem (optional)
On some non-standard distributions you may lack `/dev/gpiomem` but still have `gpiochip*` nodes. If you need libraries depending on gpiomem (like RPi.GPIO):
```bash
ls -l /dev/gpiomem || echo 'gpiomem absent'
sudo dmesg | grep -i gpiomem || true
lsmod | grep -i gpio || true
grep -E 'gpio|spi|i2c' /boot/config.txt || true
```
Ensure the kernel has Raspberry Pi GPIO memory driver enabled. If not, switch to pigpio or lgpio backends which use `/dev/gpiochip*`.

### Forcing backend order
Override order temporarily:
```bash
export GPIO_BACKENDS=pigpio,lgpio,rpi
export PULSE_SKIP_PIGPIO=1   # skip pigpio if daemon problematic
```

---
For additional help, inspect logs (`collector.log`, `uploader.log`) or run services in the foreground.
