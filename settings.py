from __future__ import annotations

from typing import Any, TypedDict, TYPE_CHECKING

from yarl import URL

from utils import json_load, json_save
from constants import SETTINGS_PATH, DEFAULT_LANG, PriorityMode

if TYPE_CHECKING:
    from main import ParsedArgs


PRIORITY_MODES = {
    "priority-only": PriorityMode.PRIORITY_ONLY,
    "ending-soonest": PriorityMode.ENDING_SOONEST,
    "low-availability-first": PriorityMode.LOW_AVBL_FIRST,
}


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items


class SettingsFile(TypedDict):
    proxy: URL
    language: str
    dark_mode: bool
    exclude: set[str]
    priority: list[str]
    autostart_tray: bool
    connection_quality: int
    tray_notifications: bool
    enable_badges_emotes: bool
    available_drops_check: bool
    priority_mode: PriorityMode


default_settings: SettingsFile = {
    "proxy": URL(),
    "priority": [],
    "exclude": set(),
    "dark_mode": False,
    "autostart_tray": False,
    "connection_quality": 1,
    "language": DEFAULT_LANG,
    "tray_notifications": True,
    "enable_badges_emotes": False,
    "available_drops_check": False,
    "priority_mode": PriorityMode.PRIORITY_ONLY,
}


class Settings:
    # from args
    log: bool
    tray: bool
    dump: bool
    cli: bool
    # args properties
    debug_ws: int
    debug_gql: int
    logging_level: int
    # from settings file
    proxy: URL
    language: str
    dark_mode: bool
    exclude: set[str]
    priority: list[str]
    autostart_tray: bool
    connection_quality: int
    tray_notifications: bool
    enable_badges_emotes: bool
    available_drops_check: bool
    priority_mode: PriorityMode

    PASSTHROUGH = ("_settings", "_args", "_altered")

    def __init__(self, args: ParsedArgs):
        self._settings: SettingsFile = json_load(SETTINGS_PATH, default_settings)
        self._args: ParsedArgs = args
        self._altered: bool = False
        priority = _split_csv(getattr(args, "priority", None))
        if priority is not None:
            self._settings["priority"] = priority
        exclude = _split_csv(getattr(args, "exclude", None))
        if exclude is not None:
            self._settings["exclude"] = set(exclude)
        priority_mode = getattr(args, "priority_mode", None)
        if priority_mode is not None:
            self._settings["priority_mode"] = PRIORITY_MODES[priority_mode]
        available_drops_check = getattr(args, "available_drops_check", None)
        if available_drops_check is not None:
            self._settings["available_drops_check"] = available_drops_check
        connection_quality = getattr(args, "connection_quality", None)
        if connection_quality is not None:
            self._settings["connection_quality"] = connection_quality

    # default logic of reading settings is to check args first, then the settings file
    def __getattr__(self, name: str, /) -> Any:
        if name in self.PASSTHROUGH:
            # passthrough
            return getattr(super(), name)
        elif name in self._settings:
            return self._settings[name]  # type: ignore[literal-required]
        elif hasattr(self._args, name):
            return getattr(self._args, name)
        return getattr(super(), name)

    def __setattr__(self, name: str, value: Any, /) -> None:
        if name in self.PASSTHROUGH:
            # passthrough
            return super().__setattr__(name, value)
        elif name in self._settings:
            self._settings[name] = value  # type: ignore[literal-required]
            self._altered = True
            return
        raise TypeError(f"{name} is missing a custom setter")

    def __delattr__(self, name: str, /) -> None:
        raise RuntimeError("settings can't be deleted")

    def alter(self) -> None:
        self._altered = True

    def save(self, *, force: bool = False) -> None:
        if self._altered or force:
            json_save(SETTINGS_PATH, self._settings, sort=True)
