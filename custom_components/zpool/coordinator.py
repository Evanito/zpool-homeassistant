from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_BASE_URL, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

class ZpoolDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Zpool data."""

    def __init__(self, hass: HomeAssistant, wallet_address: str) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.wallet_address = wallet_address

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Zpool API."""
        url = f"{API_BASE_URL}?address={self.wallet_address}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    data = await response.json()
                    
                    # The API returns an empty string for error if successful,
                    # or an error message if something went wrong.
                    if "error" in data and data["error"]:
                        raise UpdateFailed(f"API Error: {data['error']}")
                        
                    return data
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err