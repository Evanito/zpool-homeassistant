from __future__ import annotations

from datetime import timedelta

DOMAIN = "zpool"

# Wallet address configuration key used by the config flow
CONF_WALLET_ADDRESS = "wallet_address"

# Update interval for polling the zpool API
UPDATE_INTERVAL = timedelta(minutes=5)

# Base API URL for wallet data
API_BASE_URL = "https://www.zpool.ca/api/walletEX"