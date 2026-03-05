# Zpool Monitor for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)

[![hacs](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz/docs/faq/custom_repositories)

_Home Assistant Integration for monitoring your [Zpool](https://www.zpool.ca) mining pool wallet._

Supported Features:
 * Monitor wallet balance, unpaid balance, 24h payouts, and total payouts
 * Per-miner hashrate tracking with automatic miner discovery
 * Per-miner firmware version detection (parsed from miner version strings)
 * Per-algorithm total hashrate sensors
 * Automatic polling every 5 minutes via the [Zpool walletEx API](https://www.zpool.ca)
 * Simple UI-based configuration — just enter your wallet address

## Sensors

### Wallet-Level Sensors
| Sensor | Description |
|--------|-------------|
| **Balance** | Current wallet balance |
| **Unpaid** | Unpaid (pending) balance |
| **Paid (24h)** | Amount paid out in the last 24 hours |
| **Earned Total** | Total amount earned to date (paid + confirmed + unconfirmed) |

### Per-Miner Sensors
For each miner detected on your wallet:
| Sensor | Description |
|--------|-------------|
| **Hashrate** | Accepted hashrate (H/s) |
| **Firmware Version** | Firmware version (when detectable from the miner version string) |

Each miner is represented as its own device in Home Assistant, linked to the parent wallet.

### Per-Algorithm Sensors
| Sensor | Description |
|--------|-------------|
| **Algorithm Hashrate** | Total hashrate across all miners for a given algorithm |

## Installation

### Recommended: [HACS](https://www.hacs.xyz)

1. Add this repository as a custom repository to HACS: [![Add Repository](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Evanito&repository=zpool-homeassistant&category=integration)
2. Use HACS to install the integration.
3. Restart Home Assistant.
4. Set up the integration using the UI: [![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=zpool)

### Alternatives
<details>
<summary>Manual Installation</summary>

1. Using the tool of choice, open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called `zpool`.
4. Download _all_ the files from the `custom_components/zpool/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Home Assistant.
7. In the HA UI go to **Configuration** → **Integrations**, click **+** and search for **"Zpool"**.
</details>

### Configuration

Configuration is done entirely in the UI. You will be prompted to enter your **wallet address** — this is the cryptocurrency wallet address you use to mine on Zpool.

## Contributions are welcome!

If you'd like to contribute, feel free to open an issue or submit a pull request.

***

[license-shield]: https://img.shields.io/github/license/Evanito/zpool-homeassistant.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/Evanito/zpool-homeassistant.svg?style=for-the-badge
[releases]: https://github.com/Evanito/zpool-homeassistant/releases
