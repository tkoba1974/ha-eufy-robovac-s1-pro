# Eufy RoboVac S1 Pro - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

## Overview

This custom integration enables control of the Eufy RoboVac S1 Pro through Home Assistant.

## Features

- 🤖 Start/Pause/Resume cleaning
- 🏠 Return to dock
- 🔋 Battery level monitoring
- 🗺️ Cleaning mode selection
- 💧 Water level adjustment
- 🎯 Suction power control
- 📊 Cleaning statistics display

## Requirements

- Home Assistant 2024.1.0 or later
- Eufy RoboVac S1 Pro
- Local network connection

## Installation

### Via HACS (Recommended)

1. Open HACS
2. Click on "Integrations"
3. Click the three dots menu in the top right and select "Custom repositories"
4. Add repository URL `https://github.com/tkoba1974/ha-eufy-robovac-s1-pro`
5. Select "Integration" as the category
6. Click "Add"
7. Search for "Eufy RoboVac S1 Pro" in HACS and install it
8. Restart Home Assistant

### Manual Installation

1. Download this repository
2. Copy the `custom_components/eufy_robovac_s1_pro` folder to your Home Assistant's `config/custom_components/` directory
3. Restart Home Assistant

### Notes on running HA inside Docker container

You need to open 6666 and 6667 UDP ports to Homeassistant.
Please add these ports in the docker-compose.yaml as follows and rebuild the container.
```
ports:
      - '8123:8123'
      - '6666:6666/udp'
      - '6667:6667/udp'
``` 

## Configuration

1. Go to Home Assistant's Settings → Devices & Services
2. Click "Add Integration"
3. Search for "Eufy RoboVac S1 Pro"
4. Follow the on-screen instructions to complete the setup

### Required Information

You'll need the following information during setup:

- **username**: User ID of eufylife.com (Confirmed from eufy Clean app)
- **password**: Password for above User ID

## Supported Entities

### Vacuum
- Basic vacuum functions (start, pause, resume, return to dock)

### Sensors
- Battery level
- Running status
- Cleaning statistics (Total Cleaning Area, Total Cleaning Count)

### Select
- Cleaning mode and water level selection
- Suction power level

### Switch
- Auto-return toggle

## Troubleshooting

### Device Not Found

1. Verify the robot vacuum is on the same network
2. Check if the IP address is correct
3. Review firewall settings

### Connection Errors

1. Verify the username/password is correct
2. Check if the device is online in the Eufy app
3. Check Home Assistant logs for details

## Contributing

Please report bugs and feature requests via [Issues](https://github.com/tkoba1974/ha-eufy-robovac-s1-pro/issues).

Pull requests are welcome!

## Credits

This project is based on:
- [ha-eufy-robovac-g10-hybrid](https://github.com/Rjevski/ha-eufy-robovac-g10-hybrid)

## License

Released under the MIT License. See the [LICENSE](LICENSE) file for details.

## Disclaimer

This integration is unofficial and not supported by Anker/Eufy. Use at your own risk.
