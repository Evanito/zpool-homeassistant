from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ZpoolDataUpdateCoordinator
from .const import CONF_WALLET_ADDRESS, DOMAIN

_LOGGER = logging.getLogger(__name__)

def _wallet_device_info(wallet_address: str) -> DeviceInfo:
    """Return DeviceInfo for the wallet-level device."""
    short_addr = f"{wallet_address[:6]}…{wallet_address[-4:]}" if len(wallet_address) > 12 else wallet_address
    return DeviceInfo(
        identifiers={(DOMAIN, wallet_address)},
        name=f"Zpool Wallet ({short_addr})",
        manufacturer="Zpool",
        model="Wallet",
        entry_type=None,
    )


# Matches a semver-like version: optional leading 'v', then digits separated by dots
# e.g. "v2.13.0", "4.11.1", "1.2.0", "1.3.7"
_VERSION_RE = re.compile(r"^v?\d+(?:\.\d+)+$")


def _parse_version_string(version: str) -> tuple[str, str | None]:
    """Split a version string into (miner_name, firmware_version).

    The last '/'-separated segment is treated as a firmware version only if it
    matches a semver-like pattern (e.g. 'v2.13.0', '4.11.1').

    Examples:
        'cgminer/4.11.1'            → ('cgminer', '4.11.1')
        'bitaxe/BM1370/v2.13.0'     → ('bitaxe/BM1370', 'v2.13.0')
        'LuckyMiner/BM1366/1.2.0'   → ('LuckyMiner/BM1366', '1.2.0')
        'cpuminer-multi/1.3.7'      → ('cpuminer-multi', '1.3.7')
        'NerdQAxe'                   → ('NerdQAxe', None)
        'bitdsk/N8'                  → ('bitdsk/N8', None)
        'Miner/BM1366'              → ('Miner/BM1366', None)
    """
    parts = version.split("/")
    if len(parts) >= 2 and _VERSION_RE.match(parts[-1]):
        miner_name = "/".join(parts[:-1])
        firmware = parts[-1]
    else:
        miner_name = version
        firmware = None
    return miner_name, firmware


def _miner_device_info(wallet_address: str, safe_name: str, miner_name: str) -> DeviceInfo:
    """Return DeviceInfo for a per-miner device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{wallet_address}_miner_{safe_name}")},
        name=f"Zpool Miner {miner_name}",
        manufacturer="Zpool",
        model="Miner",
        via_device=(DOMAIN, wallet_address),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Zpool Monitor sensors from a config entry."""
    coordinator: ZpoolDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    wallet_address: str = entry.data[CONF_WALLET_ADDRESS]

    data: dict[str, Any] = coordinator.data or {}
    currency: str = data.get("currency", "CRYPTO")

    entities: list[SensorEntity] = []

    # ── Wallet-level sensors ────────────────────────────────────────────
    entities.append(
        ZpoolWalletSensor(coordinator, wallet_address, "balance", "Balance", currency)
    )
    entities.append(
        ZpoolWalletSensor(coordinator, wallet_address, "unpaid", "Unpaid", currency)
    )
    entities.append(
        ZpoolWalletSensor(coordinator, wallet_address, "paid24h", "Paid (24h)", currency)
    )
    entities.append(
        ZpoolWalletSensor(coordinator, wallet_address, "paidtotal", "Earned Total", currency)
    )

    # ── Per-miner hashrate + firmware sensors ───────────────────────────
    miners: list[dict[str, Any]] = data.get("miners", [])
    for idx, miner in enumerate(miners):
        raw_version = miner.get("version", f"miner_{idx}")
        miner_name, firmware = _parse_version_string(raw_version)
        miner_id = miner.get("ID", "")
        # Build a display name and safe identifier that includes the ID
        display_name = f"{miner_name} {miner_id}".strip() if miner_id else miner_name
        safe_name = display_name.replace("/", "_").replace(" ", "_")
        entities.append(
            ZpoolMinerHashrateSensor(
                coordinator, wallet_address, idx, display_name, safe_name
            )
        )
        if firmware:
            entities.append(
                ZpoolMinerFirmwareSensor(
                    coordinator, wallet_address, idx, display_name, safe_name, firmware
                )
            )

    # ── Per-algorithm total hashrate sensors ────────────────────────────
    total_hashrates: list[dict[str, Any]] = data.get("total_hashrates", [])
    for idx, algo_dict in enumerate(total_hashrates):
        if isinstance(algo_dict, dict):
            for algo_name in algo_dict:
                entities.append(
                    ZpoolAlgorithmHashrateSensor(
                        coordinator, wallet_address, idx, algo_name
                    )
                )

    async_add_entities(entities, update_before_add=True)


# ─────────────────────────────────────────────────────────────────────────────
# Wallet-level sensor (balance / unpaid / paid24h / paidtotal)
# ─────────────────────────────────────────────────────────────────────────────
class ZpoolWalletSensor(CoordinatorEntity[ZpoolDataUpdateCoordinator], SensorEntity):
    """Represents a wallet-level numeric value from the Zpool API."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZpoolDataUpdateCoordinator,
        wallet_address: str,
        key: str,
        name: str,
        currency: str,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._wallet_address = wallet_address
        self._attr_name = f"Zpool {name}"
        self._attr_unique_id = f"zpool_{wallet_address}_{key}"
        self._attr_native_unit_of_measurement = currency

    @property
    def device_info(self) -> DeviceInfo:
        """Associate this sensor with the wallet device."""
        return _wallet_device_info(self._wallet_address)

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if isinstance(data, dict):
            val = data.get(self._key)
            if val is not None:
                return float(val)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Miner hashrate sensor  (uses the "accepted" field as hashrate)
# ─────────────────────────────────────────────────────────────────────────────
class ZpoolMinerHashrateSensor(CoordinatorEntity[ZpoolDataUpdateCoordinator], SensorEntity):
    """Hashrate for an individual miner, identified by its name."""

    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "Hz"
    _attr_has_entity_name = True
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: ZpoolDataUpdateCoordinator,
        wallet_address: str,
        index: int,
        display_name: str,
        safe_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._index = index
        self._display_name = display_name
        self._safe_name = safe_name
        self._wallet_address = wallet_address
        self._attr_name = "Hashrate"
        self._attr_unique_id = f"zpool_{wallet_address}_miner_{safe_name}_hashrate"

    @property
    def device_info(self) -> DeviceInfo:
        """Associate this sensor with its own miner device."""
        return _miner_device_info(self._wallet_address, self._safe_name, self._display_name)

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if not isinstance(data, dict):
            return None
        miners = data.get("miners", [])
        if self._index < len(miners):
            val = miners[self._index].get("accepted")
            if val is not None:
                return float(val)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose additional miner details as attributes."""
        data = self.coordinator.data
        if not isinstance(data, dict):
            return {}
        miners = data.get("miners", [])
        if self._index < len(miners):
            m = miners[self._index]
            return {
                "algorithm": m.get("algo"),
                "difficulty": m.get("difficulty"),
                "rejected": m.get("rejected"),
                "password": m.get("password"),
                "asicboost": m.get("asicboost"),
            }
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Miner firmware version sensor
# ─────────────────────────────────────────────────────────────────────────────
class ZpoolMinerFirmwareSensor(CoordinatorEntity[ZpoolDataUpdateCoordinator], SensorEntity):
    """Tracks the firmware version reported by a miner."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZpoolDataUpdateCoordinator,
        wallet_address: str,
        index: int,
        display_name: str,
        safe_name: str,
        firmware: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._index = index
        self._display_name = display_name
        self._safe_name = safe_name
        self._wallet_address = wallet_address
        self._firmware = firmware
        self._attr_name = "Firmware Version"
        self._attr_unique_id = f"zpool_{wallet_address}_miner_{safe_name}_firmware"
        self._attr_icon = "mdi:chip"

    @property
    def device_info(self) -> DeviceInfo:
        """Associate this sensor with its own miner device."""
        return _miner_device_info(self._wallet_address, self._safe_name, self._display_name)

    @property
    def native_value(self) -> str | None:
        """Return the firmware version, re-parsed from live data if possible."""
        data = self.coordinator.data
        if not isinstance(data, dict):
            return self._firmware
        miners = data.get("miners", [])
        if self._index < len(miners):
            raw_version = miners[self._index].get("version", "")
            _, firmware = _parse_version_string(raw_version)
            return firmware if firmware else self._firmware
        return self._firmware


# ─────────────────────────────────────────────────────────────────────────────
# Algorithm total hashrate sensor
# ─────────────────────────────────────────────────────────────────────────────
class ZpoolAlgorithmHashrateSensor(CoordinatorEntity[ZpoolDataUpdateCoordinator], SensorEntity):
    """Total hashrate for a given algorithm across all miners."""

    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "Hz"
    _attr_has_entity_name = True
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: ZpoolDataUpdateCoordinator,
        wallet_address: str,
        index: int,
        algo_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._index = index
        self._algo_name = algo_name
        self._wallet_address = wallet_address
        self._attr_name = f"Zpool {algo_name} Hashrate"
        self._attr_unique_id = f"zpool_{wallet_address}_algo_{algo_name}_hashrate"

    @property
    def device_info(self) -> DeviceInfo:
        """Associate this sensor with the wallet device."""
        return _wallet_device_info(self._wallet_address)

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if not isinstance(data, dict):
            return None
        total_hashrates = data.get("total_hashrates", [])
        if self._index < len(total_hashrates):
            algo_dict = total_hashrates[self._index]
            if isinstance(algo_dict, dict):
                val = algo_dict.get(self._algo_name)
                if val is not None:
                    return float(val)
        return None
