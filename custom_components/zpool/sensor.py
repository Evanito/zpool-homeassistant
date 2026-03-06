from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import ZpoolDataUpdateCoordinator
from .const import CONF_WALLET_ADDRESS, DOMAIN

_LOGGER = logging.getLogger(__name__)

def _wallet_device_info(wallet_address: str) -> DeviceInfo:
    """Return DeviceInfo for the wallet-level device."""
    short_addr = f"{wallet_address[:6]}…{wallet_address[-4:]}" if len(wallet_address) > 12 else wallet_address
    return DeviceInfo(
        identifiers={(DOMAIN, wallet_address)},
        name=f"Wallet ({short_addr})",
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
        name=f"Miner {miner_name}",
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
        ZpoolWalletSensor(coordinator, wallet_address, "unpaid", "Pending", currency)
    )
    entities.append(
        ZpoolWalletSensor(coordinator, wallet_address, "paidtotal", "Earned Total", currency)
    )

    # ── Payout tracking sensors ─────────────────────────────────────────
    entities.append(
        ZpoolLastPayoutAmountSensor(coordinator, wallet_address, currency)
    )
    entities.append(
        ZpoolLastPayoutTimestampSensor(coordinator, wallet_address)
    )
    entities.append(
        ZpoolNextPayoutPredictionSensor(coordinator, wallet_address)
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
# Wallet-level sensor (balance / unpaid / paidtotal)
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
        self._attr_name = f"{name}"
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
        self._attr_name = f"{algo_name} Hashrate"
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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _get_latest_payout(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the most recent payout entry sorted by timestamp, or None."""
    payouts = data.get("payouts")
    if not payouts or not isinstance(payouts, list):
        return None
    # Sort descending by time to find the latest payout
    sorted_payouts = sorted(payouts, key=lambda p: p.get("time", 0), reverse=True)
    if sorted_payouts:
        return sorted_payouts[0]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Last Payout Amount sensor
# ─────────────────────────────────────────────────────────────────────────────
class ZpoolLastPayoutAmountSensor(
    CoordinatorEntity[ZpoolDataUpdateCoordinator], RestoreEntity, SensorEntity
):
    """Tracks the amount of the most recent payout.

    Only updates when a new payout transaction is detected. Survives HA
    restarts via RestoreEntity.
    """

    _attr_state_class = SensorStateClass.TOTAL
    _attr_has_entity_name = True
    _attr_icon = "mdi:cash-check"

    def __init__(
        self,
        coordinator: ZpoolDataUpdateCoordinator,
        wallet_address: str,
        currency: str,
    ) -> None:
        super().__init__(coordinator)
        self._wallet_address = wallet_address
        self._attr_name = "Last Payout Amount"
        self._attr_unique_id = f"zpool_{wallet_address}_last_payout_amount"
        self._attr_native_unit_of_measurement = currency
        self._last_tx: str | None = None
        self._last_amount: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._last_tx = last_state.attributes.get("tx_hash")
            if last_state.state not in (None, "unknown", "unavailable"):
                try:
                    self._last_amount = float(last_state.state)
                except (ValueError, TypeError):
                    pass

    @property
    def device_info(self) -> DeviceInfo:
        return _wallet_device_info(self._wallet_address)

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if isinstance(data, dict):
            payout = _get_latest_payout(data)
            if payout is not None:
                tx = payout.get("tx")
                if tx and tx != self._last_tx:
                    self._last_tx = tx
                    try:
                        self._last_amount = float(payout.get("amount", 0))
                    except (ValueError, TypeError):
                        pass
        return self._last_amount

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"tx_hash": self._last_tx}


# ─────────────────────────────────────────────────────────────────────────────
# Last Payout Timestamp sensor
# ─────────────────────────────────────────────────────────────────────────────
class ZpoolLastPayoutTimestampSensor(
    CoordinatorEntity[ZpoolDataUpdateCoordinator], RestoreEntity, SensorEntity
):
    """Tracks the timestamp of the most recent payout.

    Only updates when a new payout transaction is detected. Survives HA
    restarts via RestoreEntity.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-check-outline"

    def __init__(
        self,
        coordinator: ZpoolDataUpdateCoordinator,
        wallet_address: str,
    ) -> None:
        super().__init__(coordinator)
        self._wallet_address = wallet_address
        self._attr_name = "Last Payout"
        self._attr_unique_id = f"zpool_{wallet_address}_last_payout_timestamp"
        self._last_tx: str | None = None
        self._last_time: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._last_tx = last_state.attributes.get("tx_hash")
            if last_state.state not in (None, "unknown", "unavailable"):
                try:
                    self._last_time = dt_util.parse_datetime(last_state.state)
                except (ValueError, TypeError):
                    pass

    @property
    def device_info(self) -> DeviceInfo:
        return _wallet_device_info(self._wallet_address)

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        if isinstance(data, dict):
            payout = _get_latest_payout(data)
            if payout is not None:
                tx = payout.get("tx")
                if tx and tx != self._last_tx:
                    self._last_tx = tx
                    ts = payout.get("time")
                    if ts is not None:
                        self._last_time = datetime.fromtimestamp(
                            int(ts), tz=timezone.utc
                        )
        return self._last_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"tx_hash": self._last_tx}


# ─────────────────────────────────────────────────────────────────────────────
# Next Payout Prediction sensor
# ─────────────────────────────────────────────────────────────────────────────
class ZpoolNextPayoutPredictionSensor(
    CoordinatorEntity[ZpoolDataUpdateCoordinator], RestoreEntity, SensorEntity
):
    """Predicts when the next payout will occur.

    Uses the earning rate derived from balance accumulation since the last
    payout to estimate when the balance will reach the same amount as the
    previous payout.

    earning_rate = balance / (now - last_payout_time)
    remaining    = last_payout_amount - balance
    predicted    = now + remaining / earning_rate
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_icon = "mdi:crystal-ball"

    def __init__(
        self,
        coordinator: ZpoolDataUpdateCoordinator,
        wallet_address: str,
    ) -> None:
        super().__init__(coordinator)
        self._wallet_address = wallet_address
        self._attr_name = "Next Payout Prediction"
        self._attr_unique_id = f"zpool_{wallet_address}_next_payout_prediction"
        # Cached payout info (restored across restarts)
        self._last_payout_tx: str | None = None
        self._last_payout_amount: float | None = None
        self._last_payout_time: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Restore previous payout context on startup."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            attrs = last_state.attributes
            self._last_payout_tx = attrs.get("last_payout_tx")
            try:
                self._last_payout_amount = float(attrs.get("last_payout_amount", 0))
            except (ValueError, TypeError):
                self._last_payout_amount = None
            ts_str = attrs.get("last_payout_time")
            if ts_str:
                self._last_payout_time = dt_util.parse_datetime(ts_str)

    @property
    def device_info(self) -> DeviceInfo:
        return _wallet_device_info(self._wallet_address)

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        if not isinstance(data, dict):
            return None

        # Update cached payout info if a new payout is detected
        payout = _get_latest_payout(data)
        if payout is not None:
            tx = payout.get("tx")
            if tx and tx != self._last_payout_tx:
                self._last_payout_tx = tx
                try:
                    self._last_payout_amount = float(payout.get("amount", 0))
                except (ValueError, TypeError):
                    self._last_payout_amount = None
                ts = payout.get("time")
                if ts is not None:
                    self._last_payout_time = datetime.fromtimestamp(
                        int(ts), tz=timezone.utc
                    )

        # Need both a previous payout amount and time to predict
        if not self._last_payout_amount or not self._last_payout_time:
            return None

        balance = data.get("balance")
        if balance is None:
            return None
        balance = float(balance)

        now = dt_util.utcnow()
        elapsed = (now - self._last_payout_time).total_seconds()
        if elapsed <= 0:
            return None

        # Balance already meets or exceeds the target → payout imminent
        if balance >= self._last_payout_amount:
            return now

        earning_rate = balance / elapsed  # coins per second
        if earning_rate <= 0:
            return None

        remaining = self._last_payout_amount - balance
        seconds_to_payout = remaining / earning_rate
        predicted = now + timedelta(seconds=seconds_to_payout)
        return predicted

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "last_payout_tx": self._last_payout_tx,
            "last_payout_amount": self._last_payout_amount,
        }
        if self._last_payout_time:
            attrs["last_payout_time"] = self._last_payout_time.isoformat()
        else:
            attrs["last_payout_time"] = None
        return attrs
