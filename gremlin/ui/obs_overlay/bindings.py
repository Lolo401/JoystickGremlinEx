# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging
from typing import Any

from PySide6 import QtCore

import gremlin.joystick_handling
import gremlin.util
from gremlin.singleton_decorator import SingletonDecorator

syslog = logging.getLogger("system")

_logged_bind_errors: set[str] = set()


def _warn_once(key: str, message: str):
    if key in _logged_bind_errors:
        return
    _logged_bind_errors.add(key)
    try:
        syslog.warning(message)
    except RecursionError:
        pass


def _guid_key(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return gremlin.util.normalize_guid(value) or ""
    except Exception:
        return str(value).casefold()


def _device_for_binding(binding: dict[str, Any]):
    source = (binding.get("source") or "physical").casefold()
    if source == "vjoy":
        vjoy_id = int(binding.get("vjoy_id") or 0)
        if vjoy_id:
            return gremlin.joystick_handling.getDeviceFromVjoyId(vjoy_id)
    guid = binding.get("device_guid")
    if not guid:
        return None
    try:
        return gremlin.joystick_handling.getDevice(guid, show_error=False)
    except Exception:
        return None


def _invert(value: float, enabled: bool) -> float:
    if not enabled:
        return value
    return -value


def read_axis(binding: dict[str, Any], axis_id: int | None, invert: bool = False) -> float:
    if not axis_id:
        return 0.0
    source = (binding.get("source") or "physical").casefold()
    try:
        if source == "vjoy":
            vjoy_id = int(binding.get("vjoy_id") or 0)
            if not vjoy_id:
                return 0.0
            value = gremlin.joystick_handling.get_axis(vjoy_id, int(axis_id))
        else:
            guid = binding.get("device_guid")
            if not guid:
                return 0.0
            value = gremlin.joystick_handling.get_axis(guid, int(axis_id))
        if value is None:
            return 0.0
        return _invert(float(value), invert)
    except RecursionError:
        return 0.0
    except Exception as err:
        _warn_once(f"axis:{source}:{binding.get('device_guid')}:{axis_id}", f"OBS OVERLAY: axis read failed: {err}")
        return 0.0


def read_button(binding: dict[str, Any]) -> bool:
    source = (binding.get("source") or "physical").casefold()
    if source == "state":
        try:
            from gremlin.ui import state_device

            name = binding.get("state_name") or ""
            value = state_device.StateData().getValue(name)
            return bool(value)
        except Exception as err:
            _warn_once(f"state:{binding.get('state_name')}", f"OBS OVERLAY: state read failed: {err}")
            return False
    input_id = int(binding.get("input_id") or 0)
    if not input_id:
        return False
    try:
        if source == "vjoy":
            vjoy_id = int(binding.get("vjoy_id") or 0)
            if not vjoy_id:
                return False
            return bool(gremlin.joystick_handling.get_button(vjoy_id, input_id))
        guid = binding.get("device_guid")
        if not guid:
            return False
        return bool(gremlin.joystick_handling.get_button(guid, input_id))
    except Exception as err:
        _warn_once(f"button:{source}:{binding.get('device_guid')}:{input_id}", f"OBS OVERLAY: button read failed: {err}")
        return False


def read_hat(binding: dict[str, Any]) -> tuple[int, int]:
    input_id = int(binding.get("input_id") or 0)
    if not input_id:
        return (0, 0)
    source = (binding.get("source") or "physical").casefold()
    try:
        if source == "vjoy":
            vjoy_id = int(binding.get("vjoy_id") or 0)
            if not vjoy_id:
                return (0, 0)
            return gremlin.joystick_handling.get_hat_position(vjoy_id, input_id)
        guid = binding.get("device_guid")
        if not guid:
            return (0, 0)
        return gremlin.joystick_handling.get_hat_position(guid, input_id)
    except Exception as err:
        _warn_once(f"hat:{source}:{binding.get('device_guid')}:{input_id}", f"OBS OVERLAY: hat read failed: {err}")
        return (0, 0)


def widget_needs_xy(widget_type: str) -> bool:
    return widget_type in ("axis_stick_square", "axis_stick_circle", "axis_crosshair")


def binding_for_axis(item: dict[str, Any], axis: str = "x") -> dict[str, Any]:
    """X uses `binding`; Y uses `binding_y`, with legacy input_id_y fallback."""
    x_bind = dict(item.get("binding") or {})
    if axis != "y":
        return x_bind
    y_bind = item.get("binding_y")
    if isinstance(y_bind, dict) and (
        y_bind.get("device_guid")
        or y_bind.get("vjoy_id")
        or y_bind.get("input_id")
        or y_bind.get("state_name")
    ):
        return dict(y_bind)
    if x_bind.get("input_id_y"):
        legacy = dict(x_bind)
        legacy["input_id"] = x_bind.get("input_id_y")
        legacy["invert"] = bool(x_bind.get("invert_y"))
        return legacy
    return dict(y_bind or x_bind)


def binding_is_configured(binding: dict[str, Any] | None) -> bool:
    if not isinstance(binding, dict):
        return False
    source = (binding.get("source") or "physical").casefold()
    if source == "state" or (binding.get("input_type") or "").casefold() == "state":
        return bool(str(binding.get("state_name") or "").strip())
    try:
        return int(binding.get("input_id") or 0) > 0
    except (TypeError, ValueError):
        return False


def read_toggle_active(binding: dict[str, Any] | None) -> bool:
    """True while the assigned toggle input is held / past threshold."""
    if not binding_is_configured(binding):
        return False
    binding = binding or {}
    kind = (binding.get("input_type") or "button").casefold()
    source = (binding.get("source") or "physical").casefold()
    invert = bool(binding.get("invert"))
    if source == "state" or kind == "state":
        value = read_button(binding)
    elif kind == "axis":
        value = read_axis(binding, binding.get("input_id"), invert) >= 0.5
        invert = False
    elif kind == "hat":
        x, y = read_hat(binding)
        value = x != 0 or y != 0
    else:
        value = read_button(binding)
    return (not value) if invert else bool(value)


def read_widget_value(item: dict[str, Any]):
    """Return the live value used by a widget: float, (x,y), bool, or hat tuple."""
    widget_type = item.get("type")
    binding = item.get("binding") or {}
    invert = bool(binding.get("invert"))
    if widget_type in ("label", "panel", "shape", "image"):
        return None
    if widget_type == "button":
        pressed = read_button(binding)
        return (not pressed) if invert else pressed
    if widget_type == "hat":
        x, y = read_hat(binding)
        if invert:
            x = -x
        if bool(binding.get("invert_y")):
            y = -y
        return (x, y)
    if widget_needs_xy(widget_type):
        x_bind = binding_for_axis(item, "x")
        y_bind = binding_for_axis(item, "y")
        x = read_axis(x_bind, x_bind.get("input_id"), bool(x_bind.get("invert")))
        y = read_axis(y_bind, y_bind.get("input_id"), bool(y_bind.get("invert")))
        return (x, y)
    return read_axis(binding, binding.get("input_id"), invert)


@SingletonDecorator
class OverlayValueBus(QtCore.QObject):
    """Live physical / vJoy / state values for overlay widgets.

    Steady 60 Hz DirectInput poll. Per-event UI callbacks are not used:
    HID packets from every device starve Qt's paint timer and look worse.
    """

    values_changed = QtCore.Signal(object)
    POLL_INTERVAL_MS = 16  # ~60 Hz

    def __init__(self):
        super().__init__()
        self._refcount = 0
        self._connected = False
        self._poll = QtCore.QTimer(self)
        self._poll.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self._poll.setInterval(self.POLL_INTERVAL_MS)
        self._poll.timeout.connect(self.refresh)
        self._cache: dict[str, Any] = {}
        self._scene_widgets: list[dict[str, Any]] = []

    def attach(self, widgets: list[dict[str, Any]] | None = None):
        if widgets is not None:
            self._scene_widgets = widgets
        self._refcount += 1
        if self._refcount == 1:
            self._connect()
        self.refresh()

    def detach(self):
        self._refcount = max(0, self._refcount - 1)
        if self._refcount == 0:
            self._disconnect()

    def set_widgets(self, widgets: list[dict[str, Any]]):
        self._scene_widgets = widgets

    def _connect(self):
        if self._connected:
            return
        try:
            from gremlin.ui import state_device

            state_device.StateData().changed.connect(self.refresh)
        except Exception:
            pass
        self._poll.start()
        self._connected = True

    def _disconnect(self):
        if not self._connected:
            return
        try:
            from gremlin.ui import state_device

            state_device.StateData().changed.disconnect(self.refresh)
        except Exception:
            pass
        self._poll.stop()
        self._connected = False

    def refresh(self, *args):
        changed_ids = []
        for item in self._scene_widgets:
            widget_id = item.get("id")
            value = read_widget_value(item)
            if self._cache.get(widget_id) != value:
                self._cache[widget_id] = value
                changed_ids.append(widget_id)
        if changed_ids:
            self.values_changed.emit(changed_ids)

    def value_for(self, item: dict[str, Any]):
        widget_id = item.get("id")
        if widget_id in self._cache:
            return self._cache[widget_id]
        value = read_widget_value(item)
        self._cache[widget_id] = value
        return value
