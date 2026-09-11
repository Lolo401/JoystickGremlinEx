# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import copy
import json
import logging
import os
import uuid
from typing import Any

from PySide6 import QtCore
from psygnal import Signal

import gremlin.shared_state
import gremlin.util

syslog = logging.getLogger("system")

SCENE_VERSION = 1
OVERLAY_WINDOW_TITLE = "GEX Overlay"

WIDGET_TYPES = (
    "axis_bar",
    "axis_radio",
    "axis_fader",
    "axis_radial",
    "axis_encoder",
    "axis_stick_square",
    "axis_crosshair",
    "axis_stick_circle",
    "button",
    "hat",
    "label",
    "shape",
    "image",
    "panel",  # legacy alias of shape
    "axis_dial",  # legacy alias of axis_radial
)

PALETTE_TYPES = (
    "axis_bar",
    "axis_radio",
    "axis_fader",
    "axis_radial",
    "axis_encoder",
    "axis_stick_square",
    "axis_crosshair",
    "axis_stick_circle",
    "button",
    "hat",
    "label",
    "shape",
    "image",
)

PALETTE_GROUPS = (
    ("Single axis", ("axis_bar", "axis_radio", "axis_fader", "axis_radial", "axis_encoder")),
    ("Double axis", ("axis_stick_square", "axis_crosshair", "axis_stick_circle")),
    ("Other", ("button", "hat", "label", "shape", "image")),
)

DEFAULT_SIZES = {
    "axis_bar": (48, 180),
    "axis_radio": (220, 36),
    "axis_fader": (40, 180),
    "axis_radial": (150, 150),
    "axis_encoder": (150, 150),
    "axis_dial": (150, 150),
    "axis_stick_square": (168, 168),
    "axis_stick_circle": (180, 180),
    "axis_crosshair": (220, 220),
    "button": (88, 32),
    "hat": (108, 108),
    "label": (140, 28),
    "shape": (280, 160),
    "image": (200, 120),
    "panel": (280, 160),
}

DEFAULT_LABELS = {
    "axis_bar": "",
    "axis_radio": "",
    "axis_fader": "",
    "axis_radial": "",
    "axis_encoder": "",
    "axis_dial": "",
    "axis_stick_square": "",
    "axis_stick_circle": "",
    "axis_crosshair": "",
    "button": "BTN",
    "hat": "",
    "label": "Label",
    "shape": "",
    "image": "",
    "panel": "",
}


def _new_id() -> str:
    return str(uuid.uuid4())


def default_style(widget_type: str) -> dict[str, Any]:
    """Default visual style for a widget type."""
    style: dict[str, Any] = {
        "fill": "#121826",
        "fill_on": "#ff6b35",
        "border": "#2c3a52",
        "border_on": "#ffb347",
        "border_width": 2.0,
        "corner_radius": 6.0,
        "indicator": "#ff5a3c",
        "indicator_size": 12.0,
        "track": "#0b1220",
        "fill_bar": "#ff6b35",
        "grid": "#2a3a55",
        "grid_width": 1.0,
        "crosshair": "#5a6a84",
        "needle": "#ff5a3c",
        "needle_width": 3.0,
        "font_family": "Segoe UI",
        "font_size": 11,
        "font_bold": True,
        "font_color": "#f4efe4",
        "axis_label_font_family": "Segoe UI",
        "axis_label_font_size": 11,
        "axis_label_font_bold": True,
        "axis_label_font_color": "#f4efe4",
        "label_offset_x": 0,
        "label_offset_y": 0,
        "show_label": True,
        "show_axis_labels": True,
        "axis_label_n": "U",
        "axis_label_s": "D",
        "axis_label_e": "R",
        "axis_label_w": "L",
        "orientation": "vertical",
        "shape": "rounded",
        "ring_count": 3,
        "show_center_line": True,
        "show_dot_crosshair": False,
        "show_dot_shadow": True,
        "show_grid": True,
        "grid_fade": False,
        "indicator_shape": "circle",
        "angle_step": 0,
        "radio_steps": 5,
        "deadzone": 0.0,
        "invert_display": False,
        "opacity": 1.0,
        "auto_scale_font": False,
    }
    if widget_type == "axis_bar":
        style.update({"corner_radius": 6.0, "indicator_size": 14.0, "show_label": False, "show_dot_shadow": True})
    elif widget_type == "axis_radio":
        style.update({"orientation": "horizontal", "radio_steps": 5, "show_label": False})
    elif widget_type == "axis_fader":
        style.update(
            {
                "corner_radius": 4.0,
                "indicator_size": 0.0,
                "radio_steps": 8,
                "show_label": False,
                "fill_bar": "#b04a25",
            }
        )
    elif widget_type in ("axis_radial", "axis_dial"):
        style.update({"indicator_size": 10.0, "show_label": False, "needle_width": 14.0, "radio_steps": 11})
    elif widget_type == "axis_encoder":
        style.update({"show_label": False, "needle_width": 0.0, "radio_steps": 16})
    elif widget_type == "axis_stick_square":
        style.update(
            {
                "axis_label_n": "F",
                "axis_label_s": "A",
                "axis_label_e": "R",
                "axis_label_w": "L",
                "indicator_size": 14.0,
                "show_label": False,
            }
        )
    elif widget_type == "axis_stick_circle":
        style.update({"indicator_size": 14.0, "show_label": False, "ring_count": 2})
    elif widget_type == "axis_crosshair":
        style.update(
            {
                "fill": "#0a1220",
                "indicator_size": 14.0,
                "show_label": False,
                "ring_count": 3,
            }
        )
    elif widget_type == "button":
        style.update(
            {
                "fill": "#3a1518",
                "fill_on": "#ff6b35",
                "border": "#6a2a22",
                "border_on": "#ffcc66",
                "font_size": 10,
                "shape": "rounded",
                "corner_radius": 5.0,
            }
        )
    elif widget_type == "hat":
        style.update({"indicator_size": 12.0, "show_label": False, "show_axis_labels": True, "hat_positions": 4})
    elif widget_type == "label":
        style.update(
            {
                "fill": "#00000000",
                "border": "#ff2a2a",
                "border_width": 0.0,
                "corner_radius": 4.0,
                "font_size": 13,
                "show_label": True,
            }
        )
    elif widget_type in ("shape", "panel"):
        style.update(
            {
                "fill": "#101820",
                "border": "#1e2a3a",
                "border_width": 2.0,
                "corner_radius": 18.0,
                "opacity": 0.92,
                "show_label": False,
                "shape_kind": "rectangle",
                "shape_closed": True,
            }
        )
    elif widget_type == "image":
        style.update(
            {
                "fill": "#00000000",
                "border": "#1e2a3a",
                "border_width": 0.0,
                "opacity": 1.0,
                "show_label": False,
                "image_path": "",
                "image_keep_aspect": True,
            }
        )
    return style


def _refresh_font_scale_base(item: dict[str, Any], style_updates: dict[str, Any] | None = None):
    """Remember the widget size that the current font size was chosen at."""
    style = item.get("style") or {}
    if not style.get("auto_scale_font"):
        return
    updates = style_updates or {}
    if "font_scale_base" in updates:
        return
    if not (
        "auto_scale_font" in updates
        or "font_size" in updates
        or "axis_label_font_size" in updates
        or not style.get("font_scale_base")
    ):
        return
    style["font_scale_base"] = min(max(1, int(item.get("w") or 1)), max(1, int(item.get("h") or 1)))


OVERLAY_CONFIG_KEY = "obs_overlay"
XY_WIDGET_TYPES = ("axis_stick_square", "axis_stick_circle", "axis_crosshair")
NO_CORNER_RADIUS_TYPES = (
    "axis_radio",
    "axis_radial",
    "axis_dial",
    "axis_encoder",
    "axis_crosshair",
    "axis_stick_circle",
)
SINGLE_AXIS_TYPES = (
    "axis_bar",
    "axis_radio",
    "axis_fader",
    "axis_radial",
    "axis_encoder",
    "axis_dial",
)


def widget_binding_kind(widget_type: str) -> str:
    if widget_type in XY_WIDGET_TYPES:
        return "xy"
    if widget_type == "button":
        return "button"
    if widget_type == "hat":
        return "hat"
    if widget_type in ("label", "panel", "shape", "image"):
        return "none"
    if widget_type in SINGLE_AXIS_TYPES or str(widget_type).startswith("axis"):
        return "axis"
    return "none"


def default_binding(axis_id: int = 1) -> dict[str, Any]:
    return {
        "source": "physical",
        "device_guid": "",
        "device_name": "",
        "vjoy_id": 0,
        "input_type": "axis",
        "input_id": int(axis_id),
        "state_name": "",
        "invert": False,
    }


def default_toggle_binding() -> dict[str, Any]:
    binding = default_binding(1)
    binding["input_type"] = "button"
    binding["input_id"] = 0
    return binding


def normalize_toggle_binding(raw) -> dict[str, Any]:
    binding = default_toggle_binding()
    if isinstance(raw, dict):
        binding.update(raw)
    kind = str(binding.get("input_type") or "button").casefold()
    binding["input_type"] = kind if kind in ("axis", "button", "hat", "state") else "button"
    try:
        binding["input_id"] = int(binding.get("input_id") or 0)
    except (TypeError, ValueError):
        binding["input_id"] = 0
    binding["invert"] = bool(binding.get("invert"))
    return binding


def default_canvas() -> dict[str, Any]:
    return {
        "width": 1280,
        "height": 720,
        "background_mode": "chroma",
        "chroma_color": "#00FF00",
        "image_path": "",
        "grid_size": 8,
        "snap_to_grid": True,
        "always_on_top": False,
        "frameless": False,
        "show_drag_bar": True,
        "show_on_profile_start": False,
        "toggle_binding": default_toggle_binding(),
        "monitor_index": 0,
        "monitor_name": "",
        "capture_width": 1280,
        "capture_height": 720,
        "guides": [],
    }


DEFAULT_GUIDE_COLOR = "#c44cff"


def normalize_guides(canvas: dict[str, Any] | None) -> list[dict[str, Any]]:
    canvas = canvas if isinstance(canvas, dict) else {}
    guides = []
    for raw in canvas.get("guides") or []:
        if not isinstance(raw, dict):
            continue
        axis = str(raw.get("axis") or "v").casefold()
        axis = "h" if axis.startswith("h") else "v"
        try:
            pos = float(raw.get("position") if raw.get("position") is not None else 0.5)
        except (TypeError, ValueError):
            pos = 0.5
        if pos > 1.0:
            pos = pos / 100.0
        pos = max(0.0, min(1.0, pos))
        color = str(raw.get("color") or DEFAULT_GUIDE_COLOR)
        gid = str(raw.get("id") or "") or _new_id()
        guides.append({"id": gid, "axis": axis, "position": pos, "color": color})
    canvas["guides"] = guides
    return guides


def normalize_background_mode(value) -> str:
    mode = str(value or "chroma").casefold().replace("_", "-").replace(" ", "-")
    if mode in ("onscreen", "on-screen"):
        return "onscreen"
    if mode == "image":
        return "image"
    return "chroma"


def is_onscreen_mode(canvas: dict[str, Any] | None) -> bool:
    return normalize_background_mode((canvas or {}).get("background_mode")) == "onscreen"


def canonical_widget_type(widget_type: str) -> str:
    if widget_type == "panel":
        return "shape"
    if widget_type == "axis_dial":
        return "axis_radial"
    return widget_type or "button"


def new_widget(widget_type: str, x: int = 40, y: int = 40) -> dict[str, Any]:
    widget_type = canonical_widget_type(widget_type)
    if widget_type not in WIDGET_TYPES:
        widget_type = "button"
    w, h = DEFAULT_SIZES[widget_type]
    item = {
        "id": _new_id(),
        "type": widget_type,
        "x": int(x),
        "y": int(y),
        "w": int(w),
        "h": int(h),
        "z": 0,
        "rotation": 0,
        "label": DEFAULT_LABELS.get(widget_type, ""),
        "visible": True,
        "group": "",
        "style": default_style(widget_type),
        "binding": default_binding(1),
        "binding_y": default_binding(2),
        "points": [],
    }
    if widget_type == "shape":
        from .shapes import default_shape_points, normalize_shape_kind

        kind = normalize_shape_kind(item["style"].get("shape_kind"))
        item["points"] = default_shape_points(kind)
    return item


def profile_xml_path(profile=None) -> str | None:
    profile = profile or gremlin.shared_state.current_profile
    if profile is None:
        return None
    return getattr(profile, "profile_file", None) or getattr(profile, "_profile_fname", None)


def profile_display_name(profile=None) -> str:
    profile = profile or gremlin.shared_state.current_profile
    if profile is None:
        return "No profile"
    name = getattr(profile, "name", None) or getattr(profile, "_profile_name", None)
    if name:
        return str(name)
    path = profile_xml_path(profile)
    if path:
        return os.path.splitext(os.path.basename(path))[0]
    return "Unsaved profile"


def overlay_path_for_profile(profile=None) -> str | None:
    """Optional sidecar JSON next to the profile XML (fallback / export)."""
    fname = profile_xml_path(profile)
    if not fname:
        return None
    return gremlin.util.swap_ext(fname, "overlay.json")


def _same_profile_path(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    try:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
    except Exception:
        return str(left).casefold() == str(right).casefold()


class OverlayScene(QtCore.QObject):
    """Versioned overlay layout: canvas + widgets."""

    changed = Signal()
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.canvas = default_canvas()
        self.widgets: list[dict[str, Any]] = []
        self.selected_ids: list[str] = []
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._suspend = 0
        self._path: str | None = None
        self._profile_key: str | None = None
        self._dirty = False
        self._sorted_cache: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SCENE_VERSION,
            "canvas": copy.deepcopy(self.canvas),
            "widgets": copy.deepcopy(self.widgets),
        }

    def from_dict(self, data: dict[str, Any] | None):
        data = data or {}
        canvas = default_canvas()
        canvas.update(data.get("canvas") or {})
        canvas["background_mode"] = normalize_background_mode(canvas.get("background_mode"))
        canvas["toggle_binding"] = normalize_toggle_binding(canvas.get("toggle_binding"))
        normalize_guides(canvas)
        self.canvas = canvas
        widgets = []
        for raw in data.get("widgets") or []:
            widgets.append(self._normalize_widget(raw))
        self.widgets = widgets
        self.selected_ids = [wid for wid in self.selected_ids if self.widget_by_id(wid)]
        self._emit()

    def _normalize_widget(self, raw: dict[str, Any]) -> dict[str, Any]:
        from .shapes import default_shape_points, normalize_shape_kind, normalize_shape_points

        widget_type = canonical_widget_type(raw.get("type", "button"))
        item = new_widget(widget_type)
        item.update({k: raw[k] for k in item.keys() if k in raw and k not in ("style", "binding", "binding_y", "points")})
        style = default_style(widget_type)
        style.update(raw.get("style") or {})
        item["style"] = style
        item["binding"], item["binding_y"] = self._normalize_bindings(widget_type, raw)
        if widget_type == "shape":
            kind = normalize_shape_kind(style.get("shape_kind"))
            style["shape_kind"] = kind
            raw_points = raw.get("points")
            item["points"] = normalize_shape_points(raw_points, kind) if raw_points else default_shape_points(kind)
        if not item.get("id"):
            item["id"] = _new_id()
        return item

    def _normalize_bindings(self, widget_type: str, raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        raw_x = dict(raw.get("binding") or {})
        raw_y = raw.get("binding_y")
        x = default_binding(1)
        x.update(raw_x)
        legacy_y_id = x.pop("input_id_y", None)
        legacy_y_inv = x.pop("invert_y", None)
        y = default_binding(2)
        if isinstance(raw_y, dict) and raw_y:
            y.update(raw_y)
            y.pop("input_id_y", None)
            y.pop("invert_y", None)
        elif widget_type in XY_WIDGET_TYPES:
            for key in ("source", "device_guid", "device_name", "vjoy_id", "state_name"):
                if x.get(key) not in (None, ""):
                    y[key] = x.get(key)
            y["input_type"] = "axis"
            y["input_id"] = int(legacy_y_id or y.get("input_id") or 2)
            y["invert"] = bool(legacy_y_inv)
        return x, y

    def snapshot(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def restore_snapshot(self, blob: str):
        self.from_dict(json.loads(blob))
        self._dirty = True

    def push_undo(self):
        self._undo.append(self.snapshot())
        if len(self._undo) > 60:
            self._undo = self._undo[-60:]
        self._redo.clear()

    def undo(self):
        if not self._undo:
            return
        self._redo.append(self.snapshot())
        self.restore_snapshot(self._undo.pop())

    def redo(self):
        if not self._redo:
            return
        self._undo.append(self.snapshot())
        self.restore_snapshot(self._redo.pop())

    def _emit(self):
        self._sorted_cache = None
        if self._suspend <= 0:
            self.changed.emit()

    def begin_edit(self):
        self.push_undo()
        self._suspend += 1

    def end_edit(self):
        self._suspend = max(0, self._suspend - 1)
        self._dirty = True
        self._emit()

    def widget_by_id(self, widget_id: str) -> dict[str, Any] | None:
        for item in self.widgets:
            if item["id"] == widget_id:
                return item
        return None

    def sorted_widgets(self) -> list[dict[str, Any]]:
        if self._sorted_cache is None:
            order = {id(widget): index for index, widget in enumerate(self.widgets)}
            self._sorted_cache = sorted(self.widgets, key=lambda w: (w.get("z", 0), order.get(id(w), 0)))
        return self._sorted_cache

    def add_widget(self, widget_type: str, x: int = 40, y: int = 40, push_undo: bool = True) -> dict[str, Any]:
        if push_undo:
            self.push_undo()
        item = new_widget(widget_type, x, y)
        item["z"] = (max((w.get("z", 0) for w in self.widgets), default=-1) + 1)
        if self.canvas.get("snap_to_grid"):
            grid = max(1, int(self.canvas.get("grid_size", 8)))
            item["x"] = int(round(item["x"] / grid) * grid)
            item["y"] = int(round(item["y"] / grid) * grid)
        self.widgets.append(item)
        self.selected_ids = [item["id"]]
        self._dirty = True
        self._emit()
        self.selection_changed.emit()
        return item

    def convert_selected(self, widget_type: str) -> bool:
        """Change selected widgets to another type, keeping compatible settings.

        Returns False when nothing is selected so the caller can add a new widget.
        """
        widget_type = canonical_widget_type(widget_type)
        if widget_type not in WIDGET_TYPES:
            widget_type = "button"
        selected = self.selected_widgets()
        if not selected:
            return False
        if all(item.get("type") == widget_type for item in selected):
            return False
        self.push_undo()
        self._suspend += 1
        try:
            for item in selected:
                self._convert_widget(item, widget_type)
        finally:
            self._suspend = max(0, self._suspend - 1)
            self._dirty = True
            self._emit()
            self.selection_changed.emit()
        return True

    def _convert_widget(self, item: dict[str, Any], widget_type: str):
        old_type = item.get("type") or "button"
        if old_type == widget_type:
            return
        old_style = dict(item.get("style") or {})
        new_style = default_style(widget_type)
        new_style.update(old_style)
        old_size = DEFAULT_SIZES.get(old_type)
        new_size = DEFAULT_SIZES.get(widget_type)
        if old_size and new_size and (int(item.get("w") or 0), int(item.get("h") or 0)) == tuple(int(v) for v in old_size):
            item["w"], item["h"] = int(new_size[0]), int(new_size[1])
        item["type"] = widget_type
        item["style"] = new_style
        if widget_type == "shape":
            from .shapes import default_shape_points, normalize_shape_kind

            kind = normalize_shape_kind(new_style.get("shape_kind"))
            new_style["shape_kind"] = kind
            if not item.get("points"):
                item["points"] = default_shape_points(kind)
        old_kind = widget_binding_kind(old_type)
        new_kind = widget_binding_kind(widget_type)
        if new_kind == "none" or old_kind == new_kind:
            return
        if {old_kind, new_kind} <= {"axis", "xy"}:
            binding = item.get("binding") or default_binding(1)
            if binding.get("input_type") != "axis":
                item["binding"] = default_binding(1)
            if new_kind == "xy":
                y = item.get("binding_y")
                if not isinstance(y, dict) or not y:
                    item["binding_y"] = default_binding(2)
            return
        item["binding"] = default_binding(1)
        item["binding_y"] = default_binding(2)
        if new_kind == "button":
            item["binding"]["input_type"] = "button"
        elif new_kind == "hat":
            item["binding"]["input_type"] = "hat"

    def add_widgets(self, items: list[dict[str, Any]], push_undo: bool = True):
        if push_undo:
            self.push_undo()
        ids = []
        z = max((w.get("z", 0) for w in self.widgets), default=-1)
        for raw in items:
            item = self._normalize_widget(raw)
            item["id"] = _new_id()
            z += 1
            item["z"] = z
            self.widgets.append(item)
            ids.append(item["id"])
        self.selected_ids = ids
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def remove_selected(self):
        if not self.selected_ids:
            return
        self.push_undo()
        ids = set(self.selected_ids)
        self.widgets = [w for w in self.widgets if w["id"] not in ids]
        self.selected_ids = []
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def duplicate_selected(self):
        if not self.selected_ids:
            return
        self.push_undo()
        copies = []
        group_map: dict[str, str] = {}
        grid = max(1, int(self.canvas.get("grid_size", 8)))
        for widget_id in list(self.selected_ids):
            src = self.widget_by_id(widget_id)
            if not src:
                continue
            item = copy.deepcopy(src)
            item["id"] = _new_id()
            item["x"] = int(item["x"]) + grid * 2
            item["y"] = int(item["y"]) + grid * 2
            item["z"] = (max((w.get("z", 0) for w in self.widgets), default=0) + 1)
            old_group = str(item.get("group") or "").strip()
            if old_group:
                item["group"] = group_map.setdefault(old_group, _new_id())
            self.widgets.append(item)
            copies.append(item["id"])
        self.selected_ids = copies
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def expand_group_ids(self, ids: list[str]) -> list[str]:
        """Include every widget that shares a group with any of the given ids."""
        seen: list[str] = []
        idset: set[str] = set()
        groups: set[str] = set()
        for widget_id in ids:
            if widget_id in idset:
                continue
            item = self.widget_by_id(widget_id)
            if not item:
                continue
            seen.append(widget_id)
            idset.add(widget_id)
            group = str(item.get("group") or "").strip()
            if group:
                groups.add(group)
        if not groups:
            return seen
        for item in self.widgets:
            group = str(item.get("group") or "").strip()
            if group in groups and item["id"] not in idset:
                seen.append(item["id"])
                idset.add(item["id"])
        return seen

    def group_selected(self) -> bool:
        ids = list(self.selected_ids)
        if len(ids) < 2:
            return False
        self.push_undo()
        gid = _new_id()
        for widget_id in ids:
            item = self.widget_by_id(widget_id)
            if item:
                item["group"] = gid
        self._dirty = True
        self._emit()
        self.selection_changed.emit()
        return True

    def ungroup_selected(self):
        ids = self.expand_group_ids(list(self.selected_ids))
        if not ids:
            return
        self.push_undo()
        for widget_id in ids:
            item = self.widget_by_id(widget_id)
            if item:
                item["group"] = ""
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def set_selection(self, ids: list[str], additive: bool = False):
        ids = [i for i in ids if self.widget_by_id(i)]
        if additive:
            merged = list(self.selected_ids)
            for i in ids:
                if i in merged:
                    merged.remove(i)
                else:
                    merged.append(i)
            self.selected_ids = merged
        else:
            self.selected_ids = ids
        self.selection_changed.emit()

    def primary_selection(self) -> dict[str, Any] | None:
        if not self.selected_ids:
            return None
        return self.widget_by_id(self.selected_ids[-1])

    def bring_forward(self):
        self._shift_z_order(1)

    def send_backward(self):
        self._shift_z_order(-1)

    def _shift_z_order(self, delta: int):
        """Move selected widgets one paint-order step without hopping other selected items."""
        if not self.selected_ids:
            return
        selected = set(self.selected_ids)
        ordered = self.sorted_widgets()
        if len(ordered) < 2:
            return
        moved = False
        if delta > 0:
            for i in range(len(ordered) - 2, -1, -1):
                if ordered[i]["id"] in selected and ordered[i + 1]["id"] not in selected:
                    ordered[i], ordered[i + 1] = ordered[i + 1], ordered[i]
                    moved = True
        else:
            for i in range(1, len(ordered)):
                if ordered[i]["id"] in selected and ordered[i - 1]["id"] not in selected:
                    ordered[i], ordered[i - 1] = ordered[i - 1], ordered[i]
                    moved = True
        if not moved:
            return
        self.push_undo()
        for z, item in enumerate(ordered):
            item["z"] = z
        self.widgets = ordered
        self._dirty = True
        self._emit()
        self.selection_changed.emit()

    def hit_test(self, x: float, y: float) -> dict[str, Any] | None:
        for item in reversed(self.sorted_widgets()):
            if not item.get("visible", True):
                continue
            if item["x"] <= x <= item["x"] + item["w"] and item["y"] <= y <= item["y"] + item["h"]:
                return item
        return None

    def widgets_in_rect(self, x: float, y: float, w: float, h: float) -> list[str]:
        x2, y2 = x + w, y + h
        x, x2 = min(x, x2), max(x, x2)
        y, y2 = min(y, y2), max(y, y2)
        ids = []
        for item in self.widgets:
            ix, iy, iw, ih = item["x"], item["y"], item["w"], item["h"]
            if ix + iw >= x and ix <= x2 and iy + ih >= y and iy <= y2:
                ids.append(item["id"])
        return ids

    def snap_value(self, value: float) -> int:
        if not self.canvas.get("snap_to_grid"):
            return int(round(value))
        grid = max(1, int(self.canvas.get("grid_size", 8)))
        return int(round(value / grid) * grid)

    def guide_by_id(self, guide_id: str) -> dict[str, Any] | None:
        for guide in self.canvas.get("guides") or []:
            if guide.get("id") == guide_id:
                return guide
        return None

    def add_guide(self, axis: str, position: float = 0.5, color: str | None = None) -> dict[str, Any]:
        self.push_undo()
        axis = "h" if str(axis).casefold().startswith("h") else "v"
        pos = max(0.0, min(1.0, float(position)))
        existing = [float(g.get("position") or 0) for g in (self.canvas.get("guides") or []) if g.get("axis") == axis]
        if any(abs(pos - other) < 0.005 for other in existing):
            for candidate in (0.25, 0.75, 0.33, 0.67, 0.1, 0.9, 0.4, 0.6):
                if not any(abs(candidate - other) < 0.005 for other in existing):
                    pos = candidate
                    break
        guide = {
            "id": _new_id(),
            "axis": axis,
            "position": pos,
            "color": color or DEFAULT_GUIDE_COLOR,
        }
        self.canvas.setdefault("guides", []).append(guide)
        self._dirty = True
        self._emit()
        return guide

    def remove_guide(self, guide_id: str):
        guides = list(self.canvas.get("guides") or [])
        next_guides = [g for g in guides if g.get("id") != guide_id]
        if len(next_guides) == len(guides):
            return
        self.push_undo()
        self.canvas["guides"] = next_guides
        self._dirty = True
        self._emit()

    def update_guide(self, guide_id: str, **fields):
        guide = self.guide_by_id(guide_id)
        if not guide:
            return
        if "position" in fields:
            try:
                pos = float(fields["position"])
            except (TypeError, ValueError):
                pos = float(guide.get("position") or 0.5)
            if pos > 1.0:
                pos = pos / 100.0
            guide["position"] = max(0.0, min(1.0, pos))
        if "color" in fields and fields["color"]:
            guide["color"] = str(fields["color"])
        if "axis" in fields:
            axis = str(fields["axis"]).casefold()
            guide["axis"] = "h" if axis.startswith("h") else "v"
        self._dirty = True
        self._emit()

    def snap_geom_to_guides(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        x_edges: tuple[str, ...] | None = None,
        y_edges: tuple[str, ...] | None = None,
        mode: str = "move",
    ) -> tuple[float, float, float, float]:
        guides = self.canvas.get("guides") or []
        if not guides:
            return x, y, w, h
        cw = max(1.0, float(self.canvas.get("width") or 1280))
        ch = max(1.0, float(self.canvas.get("height") or 720))
        threshold = float(max(8, int(self.canvas.get("grid_size") or 8)))
        if x_edges is None:
            x_edges = ("left", "center", "right")
        if y_edges is None:
            y_edges = ("top", "center", "bottom")
        vertical = [float(g.get("position") or 0) * cw for g in guides if g.get("axis") == "v"]
        horizontal = [float(g.get("position") or 0) * ch for g in guides if g.get("axis") == "h"]

        def _best(current: dict[str, float], targets: list[float]):
            best_dist = threshold + 1.0
            best = None
            for name, value in current.items():
                for target in targets:
                    dist = abs(value - target)
                    if dist < best_dist:
                        best_dist = dist
                        best = (name, target)
            return best

        x_map = {}
        if "left" in x_edges:
            x_map["left"] = x
        if "center" in x_edges:
            x_map["center"] = x + w / 2.0
        if "right" in x_edges:
            x_map["right"] = x + w
        hit = _best(x_map, vertical) if vertical else None
        if hit:
            edge, target = hit
            if mode == "resize":
                if edge == "left":
                    right = x + w
                    x = target
                    w = max(8.0, right - x)
                elif edge == "right":
                    w = max(8.0, target - x)
                elif edge == "center":
                    x = target - w / 2.0
            else:
                if edge == "left":
                    x = target
                elif edge == "right":
                    x = target - w
                else:
                    x = target - w / 2.0

        y_map = {}
        if "top" in y_edges:
            y_map["top"] = y
        if "center" in y_edges:
            y_map["center"] = y + h / 2.0
        if "bottom" in y_edges:
            y_map["bottom"] = y + h
        hit = _best(y_map, horizontal) if horizontal else None
        if hit:
            edge, target = hit
            if mode == "resize":
                if edge == "top":
                    bottom = y + h
                    y = target
                    h = max(8.0, bottom - y)
                elif edge == "bottom":
                    h = max(8.0, target - y)
                elif edge == "center":
                    y = target - h / 2.0
            else:
                if edge == "top":
                    y = target
                elif edge == "bottom":
                    y = target - h
                else:
                    y = target - h / 2.0
        return x, y, w, h

    def snap_selection_to_guides(self):
        primary = self.primary_selection()
        if not primary:
            return
        nx, ny, nw, nh = self.snap_geom_to_guides(
            float(primary["x"]),
            float(primary["y"]),
            float(primary["w"]),
            float(primary["h"]),
            mode="move",
        )
        dx = int(round(nx - float(primary["x"])))
        dy = int(round(ny - float(primary["y"])))
        if dx == 0 and dy == 0:
            return
        for widget_id in self.selected_ids:
            item = self.widget_by_id(widget_id)
            if not item:
                continue
            item["x"] = int(item["x"]) + dx
            item["y"] = int(item["y"]) + dy

    def move_selected(self, dx: int, dy: int, snap: bool = True):
        if not self.selected_ids:
            return
        for widget_id in self.selected_ids:
            item = self.widget_by_id(widget_id)
            if not item:
                continue
            nx = item["x"] + dx
            ny = item["y"] + dy
            item["x"] = self.snap_value(nx) if snap else int(nx)
            item["y"] = self.snap_value(ny) if snap else int(ny)
        if snap:
            self.snap_selection_to_guides()
        self._dirty = True
        self._emit()

    def apply_widget_update(self, widget_id: str, **fields):
        item = self.widget_by_id(widget_id)
        if not item:
            return
        for key, value in fields.items():
            if key == "style":
                item["style"].update(value)
                _refresh_font_scale_base(item, value)
            elif key in ("binding", "binding_y"):
                item.setdefault(key, default_binding()).update(value)
            else:
                item[key] = value
        self._dirty = True
        self._emit()

    def apply_widget_updates(self, ids: list[str], **fields):
        ids = [i for i in ids if self.widget_by_id(i)]
        if not ids:
            return
        if len(ids) == 1:
            self.apply_widget_update(ids[0], **fields)
            return
        self._suspend += 1
        try:
            for widget_id in ids:
                self.apply_widget_update(widget_id, **fields)
        finally:
            self._suspend = max(0, self._suspend - 1)
            self._dirty = True
            self._emit()

    def selected_widgets(self) -> list[dict[str, Any]]:
        items = []
        seen = set()
        for widget_id in self.selected_ids:
            if widget_id in seen:
                continue
            item = self.widget_by_id(widget_id)
            if item:
                items.append(item)
                seen.add(widget_id)
        return items

    def default_path(self) -> str | None:
        return overlay_path_for_profile()

    def belongs_to_profile(self, profile=None) -> bool:
        path = profile_xml_path(profile)
        if not path:
            return self._profile_key is None
        if not self._profile_key:
            return False
        return _same_profile_path(self._profile_key, path)

    def load_for_profile(self, profile=None) -> bool:
        profile = profile or gremlin.shared_state.current_profile
        self._undo.clear()
        self._redo.clear()
        self.selected_ids = []
        path = profile_xml_path(profile)
        self._profile_key = path
        self._path = overlay_path_for_profile(profile)
        data = None
        if profile is not None:
            try:
                cfg = profile._readConfig() or {}
                candidate = cfg.get(OVERLAY_CONFIG_KEY)
                if isinstance(candidate, dict):
                    data = candidate
            except Exception as err:
                syslog.warning(f"OBS OVERLAY: profile overlay read failed: {err}")
        if data is None and self._path and os.path.isfile(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if profile is not None and isinstance(data, dict):
                    try:
                        profile._setConfig(OVERLAY_CONFIG_KEY, data)
                    except Exception:
                        pass
            except Exception as err:
                syslog.error(f"OBS OVERLAY: failed to load sidecar {self._path}: {err}")
                data = None
        if isinstance(data, dict) and (data.get("widgets") or data.get("canvas")):
            self.from_dict(data)
            self._dirty = False
            self._undo.clear()
            self._redo.clear()
            return True
        self.canvas = default_canvas()
        self.widgets = []
        self._dirty = False
        self._emit()
        self.selection_changed.emit()
        return False

    def load(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.from_dict(data)
            self._dirty = True
            self._undo.clear()
            self._redo.clear()
            return True
        except Exception as err:
            syslog.error(f"OBS OVERLAY: failed to load layout {path}: {err}")
            return False

    def save(self, path: str | None = None) -> bool:
        if path:
            return self._write_sidecar(path, self.to_dict())
        return self.save_to_profile()

    def save_owned(self) -> bool:
        """Persist this scene to the profile it was loaded from, even after a switch."""
        if not self._profile_key:
            return False
        current = profile_xml_path()
        if current and _same_profile_path(current, self._profile_key):
            return self.save_to_profile()
        return self._persist_files(self._profile_key, self.to_dict())

    def save_to_profile(self, profile=None) -> bool:
        profile = profile or gremlin.shared_state.current_profile
        path = profile_xml_path(profile)
        if not path:
            syslog.warning("OBS OVERLAY: save the GEX profile first so the overlay can be stored with it")
            return False
        data = self.to_dict()
        wrote_config = False
        if profile is not None:
            try:
                profile._setConfig(OVERLAY_CONFIG_KEY, data)
                wrote_config = True
            except Exception as err:
                syslog.error(f"OBS OVERLAY: failed to store overlay in profile config: {err}")
        sidecar_ok = self._write_sidecar(overlay_path_for_profile(profile) or gremlin.util.swap_ext(path, "overlay.json"), data)
        if wrote_config or sidecar_ok:
            self._profile_key = path
            self._path = overlay_path_for_profile(profile)
            self._dirty = False
            return True
        return False

    def _write_sidecar(self, path: str, data: dict[str, Any]) -> bool:
        try:
            folder = os.path.dirname(path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            return True
        except Exception as err:
            syslog.error(f"OBS OVERLAY: failed to save layout {path}: {err}")
            return False

    def _persist_files(self, profile_xml: str, data: dict[str, Any]) -> bool:
        config_path = gremlin.util.swap_ext(profile_xml, "json")
        merged: dict[str, Any] | None = {}
        if os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle) or {}
                if not isinstance(loaded, dict):
                    syslog.error(f"OBS OVERLAY: profile config is not an object: {config_path}")
                    merged = None
                else:
                    merged = loaded
            except Exception as err:
                syslog.error(f"OBS OVERLAY: could not merge overlay into {config_path}: {err}")
                merged = None
        wrote_config = False
        if merged is not None:
            merged[OVERLAY_CONFIG_KEY] = data
            try:
                folder = os.path.dirname(config_path)
                if folder and not os.path.isdir(folder):
                    os.makedirs(folder, exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as handle:
                    json.dump(merged, handle, indent=4, sort_keys=True)
                wrote_config = True
            except Exception as err:
                syslog.error(f"OBS OVERLAY: failed to write profile overlay config {config_path}: {err}")
        sidecar_ok = self._write_sidecar(gremlin.util.swap_ext(profile_xml, "overlay.json"), data)
        if wrote_config or sidecar_ok:
            self._dirty = False
            return True
        return False

    @property
    def dirty(self) -> bool:
        return self._dirty
