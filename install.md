# Installatiehandleiding Pi Sensing (Raspberry Pi)

Deze stappen zetten een nieuwe Raspberry Pi klaar voor pi-sensing. Alles is in het Nederlands en gebaseerd op de huidige repo-stand.

## 1. Basis voorbereiden
- Start met Raspberry Pi OS (Lite is prima) en netwerktoegang.
- Update packages:
```bash
sudo apt-get update
sudo apt-get upgrade -y
```
- Installeer basisbuild en Python tooling:
```bash
sudo apt-get install -y python3-venv python3-pip git build-essential python3-dev libffi-dev
```

## 2. I2C en (optioneel) SPI/GPIO permissies
- Schakel I2C in (voor ADS1115):
```bash
sudo raspi-config nonint do_i2c 0
```
- Herstart na het wijzigen van I2C:
```bash
sudo reboot
```
- Handig om i2c-tools te hebben voor diagnose:
```bash
sudo apt-get install -y i2c-tools
```

## 3. Repo ophalen
```bash
mkdir -p ~/Projects
cd ~/Projects
git clone <jouw-repo-url> pi-sensing
cd pi-sensing
```

## 4. Python virtualenv en dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt adafruit-blinka lgpio
```
- `adafruit-blinka` is nodig voor de ADS1115 driver.
- `lgpio` gebruikt de `/dev/gpiochip*` interface; pigpio is optioneel.

## 5. Hardware-aansluitingen
- ADS1115 (I2C):
  - VCC → 3V3 (pin 1 of 17)
  - GND → GND (bijv. pin 6)
  - SDA → GPIO2 (pin 3)
  - SCL → GPIO3 (pin 5)
  - Tweede ADS1115 op adres 0x49 (ADDR naar VCC) indien gebruikt.
- Pulsingangen:
  - GPIO17 → fysieke pin 11 (fan_rpm), interne pull-up staat aan; tik naar GND voor test.
  - GPIO27 → fysieke pin 13 (meter_pulses), idem.
- Optioneel USB-opslag: mount op `/mnt/usb-data` of gebruik de standaard map.

## 6. Data-directory
```bash
sudo mkdir -p /mnt/usb-data
sudo chown $USER:$USER /mnt/usb-data
sudo chmod u+w /mnt/usb-data
```
Plaats een USB-stick daar als je externe opslag wilt en zorg voor een fstab- of systemd-mount indien gewenst.

## 7. Configuratie invullen
Bewerk `config.yaml` voor je installatie:
- `device.id`, `device.site`, `device.location` voor de Azure-padopbouw.
- `upload_minutes` voor uploadinterval.
- Pas `pulses` en `i2c_adcs` aan als GPIO- of kanaalindeling wijzigt.
- `calibration` voor offsets en schaal.

## 8. Azure credentials (.env)
Maak `.env` in de projectroot:
```
AZURE_STORAGE_CONNECTION_STRING="<je-connection-string>"
AZURE_BLOB_CONTAINER=stable-sensing
# Optioneel overrides
# AZURE_BLOB_PREFIX=site/location
# DEVICE_ID=pi-node-01
# USB_MOUNT=/mnt/usb-data
```
Let op: gebruik quotes rond de volledige connection string om truncatie door shells te voorkomen.

## 9. Systemd services installeren
```bash
sudo cp systemd/data-collector.service /etc/systemd/system/
sudo cp systemd/azure-upload.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now data-collector.service
sudo systemctl enable --now azure-upload.service
```
- `data-collector.service` draait de sensorlezing; `azure-upload.service` uploadt continu.
- Units zetten standaard `GPIO_BACKENDS=lgpio,rpi` en `PULSE_SKIP_PIGPIO=1`. Pas paden/gebruikersnaam aan als je een andere locatie gebruikt.

## 10. Controleren
```bash
systemctl status data-collector.service
systemctl status azure-upload.service
journalctl -u data-collector.service -n 50 --no-pager
journalctl -u azure-upload.service -n 50 --no-pager
```

## 11. Handige tests
- I2C scan:
```bash
i2cdetect -y 1   # verwacht 0x48 en eventueel 0x49
```
- Pulse test (tik pin 11/13 naar GND):
```bash
PULSE_SKIP_PIGPIO=1 GPIO_BACKENDS=lgpio,rpi python - <<'PY'
import time
from src.pulse import PulseCounter
c = PulseCounter(gpio=17, pull_up=True, falling=True, debounce_us=5000)
c.start()
print("Tik pin 11 (GPIO17) naar GND; Ctrl+C stopt")
try:
    while True:
        time.sleep(1)
        print("count", c.snapshot_and_reset())
finally:
    c.stop()
PY
```

## 12. Optioneel: pigpio daemon
Niet nodig bij gebruik van lgpio. Als je pigpio wilt:
```bash
sudo apt-get install -y pigpio   # of build vanuit meegeleverde pigpio/ bron
sudo systemctl enable --now pigpiod.service
```
Zet dan desgewenst `GPIO_BACKENDS=pigpio,lgpio,rpi` en `PULSE_SKIP_PIGPIO=0`.

## 13. Updaten
```bash
cd ~/Projects/pi-sensing
git pull
source .venv/bin/activate
pip install -r requirements.txt adafruit-blinka lgpio
sudo systemctl restart data-collector.service azure-upload.service
```

## 14. Wat er gebeurt
- `data-collector` schrijft elke minuut CSV naar `/mnt/usb-data`, naam bevat device-id.
- `uploader` stuurt CSV-bestanden naar Azure Blob, met prefix `site/location/device_id` en timestamp in de bestandsnaam, en markeert uploads met `.ok`.

Troubleshooting: kijk in `collector.log` en `uploader.log` in de projectroot voor details.
