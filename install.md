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
> 💡 **GUI requirement**: the project uses a small PyQt5 interface to display voltages and
> Wi‑Fi status. On a Pi the easiest way to satisfy that is to install the system package
> first (it contains prebuilt ARM wheels) or use [piwheels](https://www.piwheels.org) when
> installing inside the virtual environment.

You can either:
1. install the Qt bindings globally:
   ```bash
   sudo apt-get install -y python3-pyqt5
   ```
   then the `pip install` step below will skip building PyQt5, or
2. stay entirely in the venv and pull from piwheels:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -i https://www.piwheels.org/simple -r requirements.txt adafruit-blinka lgpio
   ```

Installing the package outside the venv **before** you create/activate it is fine;
Python will happily reuse the system installation when the same version is requested.
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
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
- Externe status‑LED:
  - Gebruik GPIO23 (fysieke pin 16) om conflicten met pulse‑inputs te vermijden. Stel `status_led.gpio_pin: 22` in de config in.
- Optioneel USB-opslag: mount op `/mnt/usb-data` of gebruik de standaard map.

## 6. Data-directory

De applicatie slaat data op in de volgende volgorde van voorkeur:

1. **Vaste mount** `/mnt/usb-data` (aanbevolen voor productie)
2. **Automatische detectie** van een USB-stick onder `/media/<user>/...`
3. **Interne SD-kaart** als fallback: `~/Projects/pi-sensing/usb-data`

Als de vaste mount beschikbaar is, wordt die altijd gebruikt. Raakt de USB los, dan schakelt de applicatie automatisch over naar de interne SD-kaart. Wordt de USB later teruggeplugd, dan schakelt de applicatie terug én kopieert de tussentijdse SD-data automatisch naar de USB-stick.

### Aanbevolen: vaste mount instellen (productie)

**Stap 1 — maak het mountpoint aan en stel rechten in:**
```bash
sudo mkdir -p /mnt/usb-data
sudo chown $USER:$USER /mnt/usb-data
sudo chmod u+w /mnt/usb-data
```

**Stap 2 — formatteer de USB-stick met label `PI-DATA`:**
```bash
# Vervang /dev/sda1 met het juiste device (controleer met lsblk)
sudo mkfs.vfat -n PI-DATA /dev/sda1
```
Door alle sticks hetzelfde label te geven werkt elke stick op alle 80 apparaten zonder verdere configuratie.

**Stap 3 — voeg een fstab-regel toe:**
```bash
sudo nano /etc/fstab
```
Voeg onderaan toe (vervang `1000` als je gebruiker een andere uid/gid heeft — controleer met `id`):
```
LABEL=PI-DATA  /mnt/usb-data  vfat  defaults,nofail,uid=1000,gid=1000,umask=0022  0  0
```
- `nofail` zorgt dat de Pi gewoon opstart als de USB niet aanwezig is.
- `uid`/`gid` geeft je gebruiker schrijfrechten.

**Stap 4 — test de mount:**
```bash
sudo mount -a
ls /mnt/usb-data
```

> 💡 **Geen vaste mount?** Geen probleem — de applicatie detecteert een USB-stick automatisch onder `/media/<user>/` en gebruikt die. Als er geen USB aanwezig is wordt data lokaal op de SD-kaart bewaard en later naar de USB gekopieerd zodra die beschikbaar is.

## 7. Configuratie invullen
Bewerk `config.yaml` voor je installatie:
- `device.id`, `device.site`, `device.location` voor de Azure-padopbouw.
- `upload_minutes` voor uploadinterval.
- Pas `pulses` en `i2c_adcs` aan als GPIO- of kanaalindeling wijzigt.
- `calibration` voor offsets en schaal.

## 8. Azure credentials (.env)
Gebruik de meegeleverde template en vul daarna je echte credentials in:

```bash
cp .env.example .env
nano .env
```

**Belangrijk:**
- **Gebruik GEEN quotes** rond connection strings of SAS tokens. Systemd `EnvironmentFile` neemt quotes letterlijk over, wat Azure authenticatie kan breken.
- Zonder `.env` start de uploader wel, maar upload mislukt met `No Azure credentials given`.
- `IOTHUB_DEVICE_CONNECTION_STRING` is vereist voor IoT Hub telemetrie (heartbeat, data, settings).
- Haal de IoT Hub connection string op via Azure Portal → IoT Hub → Devices → [device] → Primary Connection String.

## 9. Systemd services installeren

**Let op:** In de huidige eerste deploy-versie zijn de servicebestanden vastgezet op de doel-RP5:
- gebruiker: `staldemo`
- projectpad: `/home/staldemo/Projects/pi-sensing`
- python: `/home/staldemo/Projects/pi-sensing/.venv/bin/python`

Als je op een andere gebruiker of andere installatielocatie deployt, pas dan eerst de paden in de servicefiles aan.

```bash
# Installeer de services:
sudo cp systemd/data-collector.service /etc/systemd/system/
sudo cp systemd/azure-upload.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now data-collector.service
sudo systemctl enable --now azure-upload.service
```
- `data-collector.service` draait de sensorlezing en IoT Hub communicatie.
- `azure-upload.service` draait continu op de achtergrond en uploadt CSV-bestanden naar Azure Blob Storage volgens `upload_minutes` in `config.yaml`.
- Services laden automatisch de `.env` file via `EnvironmentFile`.
- **Opmerking:** Zorg dat je `.env` in `~/Projects/pi-sensing/` staat en de juiste Azure connection strings bevat.
- De meegeleverde `azure-upload.timer` wordt in deze opzet **niet** gebruikt; de uploader heeft al een interne interval-loop.

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
- `data-collector` schrijft elke minuut CSV naar het actieve datapad (zie §6). Prioriteit: `/mnt/usb-data` → automatisch gedetecteerde USB → interne SD-kaart (`usb-data/`).
- Als de USB terugkeert terwijl de applicatie draait, worden SD-kaartdata automatisch naar de USB gekopieerd (één richting: SD → USB).
- `data-collector.service` start automatisch bij boot.
- Bij boot start de GUI alleen als er een lokaal display en actieve GUI-sessie beschikbaar zijn; anders draait de applicatie headless door.
- `uploader` scant zowel de USB als de interne SD-kaart, dedupliceert op bestandsnaam en uploadt alles naar Azure Blob met prefix `site/location/device_id`; uploads worden gemarkeerd met `.ok`.
- `azure-upload.service` start automatisch bij boot en blijft actief; de uploadfrequentie wordt bepaald door `upload_minutes` in `config.yaml`.
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
Of controleer de fstab-regel (zie §6). Als de USB niet aanwezig is, schrijft de applicatie automatisch naar de interne SD-kaart — geen actie vereist.

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

