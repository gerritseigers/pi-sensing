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
sudo apt-get install -y python3-venv python3-pip git build-essential python3-dev libffi-dev swig liblgpio-dev
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
python3 -m venv venv
source venv/bin/activate
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
```bash
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net
AZURE_BLOB_CONTAINER=stable-sensing
IOTHUB_DEVICE_CONNECTION_STRING=HostName=...;DeviceId=...;SharedAccessKey=...

# Optioneel overrides
# AZURE_BLOB_PREFIX=site/location
# USB_MOUNT=/mnt/usb-data
```
**Belangrijk:**
- **Gebruik GEEN quotes** rond de connection strings! Systemd's `EnvironmentFile` neemt quotes letterlijk over, waardoor de Azure SDK foutmeldingen geeft zoals "Connection string missing required connection details".
- `IOTHUB_DEVICE_CONNECTION_STRING` is vereist voor IoT Hub telemetrie (heartbeat, data, settings).
- Haal de IoT Hub connection string op via Azure Portal → IoT Hub → Devices → [device] → Primary Connection String.

## 9. Systemd services installeren

**Let op:** De service bestanden bevatten hardcoded paden. Controleer en pas aan indien nodig:
- `User=gerrit` → jouw gebruikersnaam
- `/home/gerrit/Projects/pi-sensing` → jouw installatiemap
- `venv/bin/python` → pad naar Python in je virtualenv

```bash
# Bekijk en pas eventueel aan:
nano systemd/data-collector.service
nano systemd/azure-upload.service

# Installeer de services:
sudo cp systemd/data-collector.service /etc/systemd/system/
sudo cp systemd/azure-upload.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now data-collector.service
sudo systemctl enable --now azure-upload.service
```
- `data-collector.service` draait de sensorlezing en IoT Hub communicatie.
- `azure-upload.service` uploadt CSV-bestanden naar Azure Blob Storage.
- Services laden automatisch de `.env` file via `EnvironmentFile`.

## 10. Controleren
```bash
systemctl status data-collector.service
systemctl status azure-upload.service
journalctl -u data-collector.service -n 50 --no-pager
journalctl -u azure-upload.service -n 50 --no-pager
```

## 11. Handige tests

### ADS1115 test:
```bash
source venv/bin/activate
python3 -c "
import yaml
from src.ads1115_reader import ADCManager
with open('config.yaml') as f:
    cfg = yaml.safe_load(f)
adc = ADCManager(cfg.get('i2c_adcs', []))
for name, voltage in adc.read_all().items():
    print(f'{name}: {voltage:.4f} V')
"
```

### I2C scan:
```bash
i2cdetect -y 1   # verwacht 0x48 en eventueel 0x49
```

### Pulse test (tik pin 11/13 naar GND):
```bash
source venv/bin/activate
PULSE_SKIP_PIGPIO=1 GPIO_BACKENDS=lgpio,rpi python3 - <<'PY'
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

### IoT Hub test:
```bash
source venv/bin/activate
set -a && source .env && set +a
python3 -c "
import os
from src.iot import IoTHubSender
conn = os.environ.get('IOTHUB_DEVICE_CONNECTION_STRING', '')
if conn:
    iot = IoTHubSender(conn, 'test-device')
    iot.start()
    if iot.client:
        iot.send('test', {'msg': 'Hello'})
        print('IoT Hub: OK')
        iot.stop()
else:
    print('Geen IOTHUB_DEVICE_CONNECTION_STRING in .env')
"
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
source venv/bin/activate
pip install -r requirements.txt adafruit-blinka lgpio
sudo systemctl restart data-collector.service azure-upload.service
```

## 14. Wat er gebeurt
- `data-collector` schrijft elke minuut CSV naar `/mnt/usb-data`, naam bevat device-id.
- `uploader` stuurt CSV-bestanden naar Azure Blob, met prefix `site/location/device_id` en timestamp in de bestandsnaam, en markeert uploads met `.ok`.
- Indien `iot.enabled: true` en `IOTHUB_DEVICE_CONNECTION_STRING` gezet, stuurt de collector IoT Hub-berichten:
  - `settings` bij start (config dump)
  - `heartbeat` elke `heartbeat_seconds`
  - `data` bij elke sample (puls- en ADC-waarden)

## 15. Troubleshooting

### Service start niet / ModuleNotFoundError
```bash
journalctl -u data-collector.service -n 50 --no-pager
```
**Oorzaak:** Verkeerd Python pad in service file.  
**Oplossing:** Controleer dat `ExecStart` verwijst naar `venv/bin/python` (niet `.venv`).

### PermissionError: '/mnt/usb-data'
```bash
sudo mkdir -p /mnt/usb-data
sudo chown $USER:$USER /mnt/usb-data
```

### IoT Hub berichten worden niet verstuurd
- Controleer of `IOTHUB_DEVICE_CONNECTION_STRING` in `.env` staat
- Service moet `.env` laden via `EnvironmentFile` in de service file
- Test handmatig met de IoT Hub test hierboven

### ADS1115 niet gevonden
```bash
i2cdetect -y 1
```
- Verwacht `48` (en `49` bij tweede module)
- Controleer bedrading: SDA=GPIO2 (pin 3), SCL=GPIO3 (pin 5)
- I2C ingeschakeld? `sudo raspi-config nonint do_i2c 0`

### Logbestanden bekijken
```bash
# Systemd logs:
journalctl -u data-collector.service -f
journalctl -u azure-upload.service -f

# Applicatie logs:
tail -f collector.log
tail -f uploader.log
```

