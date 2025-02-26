"""The Washer/Dryer Sensor for Whirlpool Appliances."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from whirlpool.washerdryer import MachineState, WasherDryer

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util.dt import utcnow

from . import WhirlpoolData
from .const import DOMAIN

TANK_FILL = {
    "0": "Unknown",
    "1": "Empty",
    "2": "25%",
    "3": "50%",
    "4": "100%",
    "5": "Active",
}

MACHINE_STATE = {
    MachineState.Standby: "Standby",
    MachineState.Setting: "Setting",
    MachineState.DelayCountdownMode: "Delay Countdown",
    MachineState.DelayPause: "Delay Paused",
    MachineState.SmartDelay: "Smart Delay",
    MachineState.SmartGridPause: "Smart Grid Pause",
    MachineState.Pause: "Pause",
    MachineState.RunningMainCycle: "Running Maincycle",
    MachineState.RunningPostCycle: "Running Postcycle",
    MachineState.Exceptions: "Exception",
    MachineState.Complete: "Complete",
    MachineState.PowerFailure: "Power Failure",
    MachineState.ServiceDiagnostic: "Service Diagnostic Mode",
    MachineState.FactoryDiagnostic: "Factory Diagnostic Mode",
    MachineState.LifeTest: "Life Test",
    MachineState.CustomerFocusMode: "Customer Focus Mode",
    MachineState.DemoMode: "Demo Mode",
    MachineState.HardStopOrError: "Hard Stop or Error",
    MachineState.SystemInit: "System Initialize",
}

CYCLE_FUNC = [
    (WasherDryer.get_cycle_status_filling, "Cycle Filling"),
    (WasherDryer.get_cycle_status_rinsing, "Cycle Rinsing"),
    (WasherDryer.get_cycle_status_sensing, "Cycle Sensing"),
    (WasherDryer.get_cycle_status_soaking, "Cycle Soaking"),
    (WasherDryer.get_cycle_status_spinning, "Cycle Spinning"),
    (WasherDryer.get_cycle_status_washing, "Cycle Washing"),
]


ICON_D = "mdi:tumble-dryer"
ICON_W = "mdi:washing-machine"

_LOGGER = logging.getLogger(__name__)


def washer_state(washer: WasherDryer) -> str | None:
    """Determine correct states for a washer."""

    if washer.get_attribute("Cavity_OpStatusDoorOpen") == "1":
        return "Door open"

    machine_state = washer.get_machine_state()

    if machine_state == MachineState.RunningMainCycle:
        for func, cycle_name in CYCLE_FUNC:
            if func(washer):
                return cycle_name

    return MACHINE_STATE.get(machine_state, STATE_UNKNOWN)


@dataclass
class WhirlpoolSensorEntityDescriptionMixin:
    """Mixin for required keys."""

    value_fn: Callable


@dataclass
class WhirlpoolSensorEntityDescription(
    SensorEntityDescription, WhirlpoolSensorEntityDescriptionMixin
):
    """Describes Whirlpool Washer sensor entity."""


SENSORS: tuple[WhirlpoolSensorEntityDescription, ...] = (
    WhirlpoolSensorEntityDescription(
        key="state",
        name="State",
        icon=ICON_W,
        has_entity_name=True,
        value_fn=washer_state,
    ),
    WhirlpoolSensorEntityDescription(
        key="DispenseLevel",
        name="Detergent Level",
        icon=ICON_W,
        has_entity_name=True,
        value_fn=lambda WasherDryer: TANK_FILL[
            WasherDryer.get_attribute("WashCavity_OpStatusBulkDispense1Level")
        ],
    ),
)

SENSOR_TIMER: tuple[SensorEntityDescription] = (
    SensorEntityDescription(
        key="timeremaining",
        name="End Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon=ICON_W,
        has_entity_name=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Config flow entry for Whrilpool Laundry."""
    entities: list = []
    whirlpool_data: WhirlpoolData = hass.data[DOMAIN][config_entry.entry_id]
    for appliance in whirlpool_data.appliances_manager.washer_dryers:
        _wd = WasherDryer(
            whirlpool_data.backend_selector,
            whirlpool_data.auth,
            appliance["SAID"],
        )
        await _wd.connect()

        entities.extend(
            [
                WasherDryerClass(
                    appliance["SAID"],
                    appliance["NAME"],
                    description,
                    _wd,
                )
                for description in SENSORS
            ]
        )
        entities.extend(
            [
                WasherDryerTimeClass(
                    appliance["SAID"],
                    appliance["NAME"],
                    description,
                    _wd,
                )
                for description in SENSOR_TIMER
            ]
        )
    async_add_entities(entities)


class WasherDryerClass(SensorEntity):
    """A class for the whirlpool/maytag washer account."""

    _attr_should_poll = False

    def __init__(
        self,
        said: str,
        name: str,
        description: WhirlpoolSensorEntityDescription,
        washdry: WasherDryer,
    ) -> None:
        """Initialize the washer sensor."""
        self._name = name.capitalize()
        self._wd: WasherDryer = washdry

        if self._name == "Dryer":
            self._attr_icon = ICON_D

        self.entity_description: WhirlpoolSensorEntityDescription = description
        self._attr_unique_id = f"{said}-{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, said)},
            name=self._name,
            manufacturer="Whirlpool",
        )

    async def async_added_to_hass(self) -> None:
        """Connect washer/dryer to the cloud."""
        self._wd.register_attr_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Close Whrilpool Appliance sockets before removing."""
        await self._wd.disconnect()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._wd.get_online()

    @property
    def native_value(self) -> StateType | str:
        """Return native value of sensor."""
        return self.entity_description.value_fn(self._wd)


class WasherDryerTimeClass(RestoreSensor):
    """A timestamp class for the whirlpool/maytag washer account."""

    _attr_should_poll = False

    def __init__(
        self,
        said: str,
        name: str,
        description: SensorEntityDescription,
        washdry: WasherDryer,
    ) -> None:
        """Initialize the washer sensor."""
        self._name = name.capitalize()
        self._wd: WasherDryer = washdry

        if self._name == "Dryer":
            self._attr_icon = ICON_D

        self.entity_description: SensorEntityDescription = description
        self._attr_unique_id = f"{said}-{description.key}"
        self._running: bool | None = None
        self._timestamp: datetime | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, said)},
            name=self._name,
            manufacturer="Whirlpool",
        )

    async def async_added_to_hass(self) -> None:
        """Connect washer/dryer to the cloud."""
        if restored_data := await self.async_get_last_sensor_data():
            self._attr_native_value = restored_data.native_value
        await super().async_added_to_hass()
        self._wd.register_attr_callback(self.update_from_latest_data)

    async def async_will_remove_from_hass(self) -> None:
        """Close Whrilpool Appliance sockets before removing."""
        await self._wd.disconnect()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._wd.get_online()

    @callback
    def update_from_latest_data(self) -> None:
        """Calculate the time stamp for completion."""
        machine_state = self._wd.get_machine_state()
        now = utcnow()
        if (
            machine_state.value
            in {MachineState.Complete.value, MachineState.Standby.value}
            and self._running
        ):
            self._running = False
            self._attr_native_value = now
            self._async_write_ha_state()

        if machine_state is MachineState.RunningMainCycle:
            self._running = True
            self._attr_native_value = now + timedelta(
                seconds=int(self._wd.get_attribute("Cavity_TimeStatusEstTimeRemaining"))
            )

            self._async_write_ha_state()
