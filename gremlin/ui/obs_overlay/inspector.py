# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

import gremlin.joystick_handling
import gremlin.types
import gremlin.ui.ui_common
import gremlin.util
from gremlin.input_types import InputType

from .bindings import widget_needs_xy
from .model import (
    DEFAULT_GUIDE_COLOR,
    NO_CORNER_RADIUS_TYPES,
    OverlayScene,
    canonical_widget_type,
    default_style,
    is_onscreen_mode,
    normalize_background_mode,
    normalize_toggle_binding,
)
from .shapes import SHAPE_KIND_LABELS, default_shape_points, normalize_shape_kind
from .overlay_window import apply_onscreen_geometry, list_overlay_screens, resolve_overlay_screen
from .palettes import (
    BUILTIN_IDS,
    COLOR_KEYS,
    add_palette,
    delete_palette,
    extract_colors,
    list_builtin_palettes,
    list_user_palettes,
    palette_type,
    update_palette,
)
from .widgets import effective_font_size, qcolor

CANVAS_TOGGLE_ID = "__canvas_toggle__"
syslog = logging.getLogger("system")


class ColorButton(QtWidgets.QPushButton):
    color_changed = QtCore.Signal(str)

    def __init__(self, value="#ffffff", parent=None, preserve_transparent: bool = False):
        super().__init__(parent)
        self.setObjectName("overlayColorSwatch")
        self._value = value or "#ffffff"
        self._preserve_transparent = bool(preserve_transparent)
        self.setFixedHeight(24)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._refresh()

    def set_value(self, value: str):
        self._value = value or "#ffffff"
        self._refresh()

    def value(self) -> str:
        return self._value

    def _refresh(self):
        color = qcolor(self._value)
        # Object-name selector so this does not leak onto QColorDialog buttons.
        self.setStyleSheet(
            f"#overlayColorSwatch {{ background:{color.name(QtGui.QColor.HexArgb)}; border:1px solid #444; border-radius:3px; }}"
        )
        self.setToolTip(self._value)

    def _pick(self):
        chosen = QtWidgets.QColorDialog.getColor(
            qcolor(self._value),
            self.window() or self.parentWidget() or self,
            "Select color",
            QtWidgets.QColorDialog.DontUseNativeDialog | QtWidgets.QColorDialog.ShowAlphaChannel,
        )
        if chosen.isValid():
            previous = qcolor(self._value)
            # Transparent defaults keep alpha at 0 in the picker; bump so fill/border actually show.
            if not self._preserve_transparent and previous.alpha() == 0 and chosen.alpha() == 0:
                chosen.setAlpha(255)
            self._value = chosen.name(QtGui.QColor.HexArgb)
            self._refresh()
            self.color_changed.emit(self._value)


class PaletteSwatch(QtWidgets.QPushButton):
    """One saved color set, shown as a fill square (cross if the fill is transparent)."""

    apply_requested = QtCore.Signal()
    update_requested = QtCore.Signal()
    delete_requested = QtCore.Signal()

    def __init__(self, colors: dict, label: str, editable: bool = False, parent=None):
        super().__init__(parent)
        self._colors = colors or {}
        self._editable = editable
        self.setFixedSize(28, 28)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setFlat(True)
        self.setStyleSheet("QPushButton { border: none; background: transparent; padding: 0; }")
        if editable:
            self.setToolTip(f"{label}. Click to apply. Right-click to update with the current colors or delete.")
            self.setContextMenuPolicy(QtCore.Qt.DefaultContextMenu)
        else:
            self.setToolTip(f"{label}. Click to apply.")
            self.setContextMenuPolicy(QtCore.Qt.NoContextMenu)
        self.clicked.connect(lambda _=False: self.apply_requested.emit())

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        rect = self.rect().adjusted(2, 2, -3, -3)
        fill = qcolor(self._colors.get("fill"), "#121826")
        accent = qcolor(
            self._colors.get("fill_on") or self._colors.get("indicator") or self._colors.get("fill_bar") or self._colors.get("border"),
            "#888888",
        )
        outline = qcolor(self._colors.get("border") or self._colors.get("indicator"), "#555555")
        if fill.alpha() <= 0:
            painter.fillRect(rect, QtGui.QColor("#2a2a2a"))
            painter.setPen(QtGui.QPen(accent if accent.alpha() > 0 else QtGui.QColor("#888888"), 2))
            painter.drawLine(rect.topLeft() + QtCore.QPoint(1, 1), rect.bottomRight() - QtCore.QPoint(1, 1))
            painter.drawLine(rect.topRight() + QtCore.QPoint(-1, 1), rect.bottomLeft() + QtCore.QPoint(1, -1))
        else:
            painter.fillRect(rect, fill)
            if accent.alpha() > 0 and accent != fill:
                corner = QtCore.QRect(rect.right() - 8, rect.bottom() - 8, 8, 8)
                painter.fillRect(corner, accent)
        painter.setPen(QtGui.QPen(outline if outline.alpha() > 0 else QtGui.QColor("#555555"), 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(rect)
        painter.end()

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        if not self._editable:
            return
        menu = QtWidgets.QMenu(self)
        update_action = menu.addAction("Update with current colors")
        update_action.triggered.connect(lambda _=False: self.update_requested.emit())
        delete_action = menu.addAction("Delete palette")
        delete_action.triggered.connect(lambda _=False: self.delete_requested.emit())
        menu.exec(event.globalPos())


class OverlayInspector(QtWidgets.QWidget):
    """Property panel for canvas + selected widget."""

    def __init__(self, scene: OverlayScene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._building = False
        self._edit_ids: list[str] = []
        self._multi = False
        self._live_fields: list = []
        self._rebuild_pending = False
        self._last_rebuild_ids: list[str] = []
        self._pending_scroll = (0, 0)
        self._scroll_restore_tries = 0
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        self._host = QtWidgets.QWidget()
        self._form = QtWidgets.QVBoxLayout(self._host)
        self._form.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._host)
        layout.addWidget(scroll)
        self._scroll = scroll
        self.scene.selection_changed.connect(self.rebuild)
        self.scene.changed.connect(self._maybe_rebuild)
        self.destroyed.connect(self._detach_scene)
        self._canvas_sig = None
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            StreamDeckBridge().devices_changed.connect(self._on_streamdeck_devices_changed)
        except Exception:
            pass
        self.rebuild()

    def _detach_scene(self, *_args):
        try:
            self.scene.selection_changed.disconnect(self.rebuild)
        except Exception:
            pass
        try:
            self.scene.changed.disconnect(self._maybe_rebuild)
        except Exception:
            pass
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            StreamDeckBridge().devices_changed.disconnect(self._on_streamdeck_devices_changed)
        except Exception:
            pass
        self._scroll = None
        self._form = None
        self._host = None

    def _is_alive(self) -> bool:
        try:
            return Shiboken.isValid(self)
        except Exception:
            return False

    def _scroll_area(self):
        if not self._is_alive():
            return None
        scroll = getattr(self, "_scroll", None)
        try:
            if scroll is None or not Shiboken.isValid(scroll):
                return None
        except Exception:
            return None
        return scroll

    def _on_streamdeck_devices_changed(self):
        if not self._is_alive():
            return
        items = self.scene.selected_widgets()
        if any(canonical_widget_type(item.get("type")) == "streamdeck" for item in items):
            self._schedule_rebuild()

    def _canvas_signature(self):
        canvas = self.scene.canvas
        page = self.scene.active_page() or {}
        return (
            self.scene.active_page_id,
            page.get("name"),
            page.get("visible"),
            page.get("window_x"),
            page.get("window_y"),
            canvas.get("width"),
            canvas.get("height"),
            canvas.get("background_mode"),
            canvas.get("monitor_index"),
            canvas.get("monitor_name"),
            canvas.get("interactive"),
        )

    def _maybe_rebuild(self):
        if not self._is_alive():
            return
        if self._building:
            self._rebuild_pending = True
            return
        if self._rebuild_pending:
            return
        sig = self._canvas_signature()
        if sig != self._canvas_sig:
            self._schedule_rebuild()
            return
        self._refresh_live_fields()

    def _schedule_rebuild(self):
        if self._rebuild_pending:
            return
        self._rebuild_pending = True
        QtCore.QTimer.singleShot(0, self._run_scheduled_rebuild)

    def _run_scheduled_rebuild(self):
        self._rebuild_pending = False
        if not self._is_alive():
            return
        try:
            self.rebuild()
        except RuntimeError:
            return

    def _refresh_live_fields(self):
        for fn in list(self._live_fields):
            try:
                fn()
            except RuntimeError:
                continue

    def _clear(self):
        layout = self._form
        if layout is None:
            return
        try:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    # Hide first. setParent(None) would make a visible top-level
                    # window (title = application name) for a frame on page switch.
                    widget.hide()
                    widget.deleteLater()
        except RuntimeError:
            return

    def _section(self, title: str) -> QtWidgets.QFormLayout:
        box = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        self._form.addWidget(box)
        return form

    def rebuild(self):
        if not self._is_alive():
            return
        app = QtWidgets.QApplication.instance()
        if app is not None and QtCore.QThread.currentThread() is not app.thread():
            # Scene signals are psygnal (same-thread); bounce off worker threads.
            gremlin.util.InvokeUiMethod(self.rebuild)
            return
        if self._building:
            self._rebuild_pending = True
            return
        self._building = True
        self._rebuild_pending = False
        self._live_fields = []
        built_ids = None
        previous_ids = list(self._last_rebuild_ids)
        saved_v = 0
        saved_h = 0
        scroll = self._scroll_area()
        if scroll is not None:
            try:
                saved_v = scroll.verticalScrollBar().value()
                saved_h = scroll.horizontalScrollBar().value()
            except RuntimeError:
                saved_v = 0
                saved_h = 0
        try:
            self._canvas_sig = self._canvas_signature()
            self._clear()
            items = self.scene.selected_widgets()
            self._edit_ids = [item["id"] for item in items]
            self._multi = len(items) > 1
            if not items:
                # Canvas / toggle overlay only when nothing is selected.
                self._build_canvas()
                hint = QtWidgets.QLabel("Select a widget on the canvas, or add one from the palette.")
                hint.setWordWrap(True)
                self._form.addWidget(hint)
                self._form.addStretch()
            else:
                types = {canonical_widget_type(item.get("type")) for item in items}
                if self._multi and len(types) > 1:
                    self._build_mixed(items)
                else:
                    self._build_widget(items[0])
                self._form.addStretch()
            built_ids = list(self._edit_ids)
            self._last_rebuild_ids = built_ids
            keep_scroll = bool(built_ids) and built_ids == previous_ids
            self._pending_scroll = (saved_h, saved_v) if keep_scroll else (0, 0)
            self._scroll_restore_tries = 0
            QtCore.QTimer.singleShot(0, self._restore_inspector_scroll)
        except RuntimeError:
            return
        except Exception:
            syslog.exception("OBS OVERLAY: inspector rebuild failed")
        finally:
            self._building = False
        if not self._is_alive():
            return
        current_ids = [item["id"] for item in self.scene.selected_widgets()]
        if self._rebuild_pending or (built_ids is not None and current_ids != built_ids):
            self._rebuild_pending = False
            QtCore.QTimer.singleShot(0, self.rebuild)

    def _restore_inspector_scroll(self):
        scroll = self._scroll_area()
        if scroll is None:
            return
        try:
            hx, vy = self._pending_scroll
            hbar = scroll.horizontalScrollBar()
            vbar = scroll.verticalScrollBar()
            if ((vy > vbar.maximum()) or (hx > hbar.maximum())) and self._scroll_restore_tries < 3:
                self._scroll_restore_tries += 1
                QtCore.QTimer.singleShot(0, self._restore_inspector_scroll)
                return
            hbar.setValue(min(max(0, int(hx)), hbar.maximum()))
            vbar.setValue(min(max(0, int(vy)), vbar.maximum()))
        except RuntimeError:
            return

    def _build_canvas(self):
        form = self._section("Canvas")
        canvas = self.scene.canvas
        page = self.scene.active_page() or {}
        onscreen = is_onscreen_mode(canvas)

        name = QtWidgets.QLineEdit(str(page.get("name") or ""))
        name.setToolTip("Name of this overlay page. Shown on the designer tab and in the live window title.")
        name.editingFinished.connect(lambda edit=name: self._on_page_name(edit.text()))
        form.addRow("Name", name)

        visible = QtWidgets.QCheckBox()
        visible.setChecked(bool(page.get("visible", True)))
        visible.setToolTip("When off, this page’s live window is closed. Show overlay still only opens the selected page.")
        visible.toggled.connect(lambda v: self.scene.set_page_visible(bool(v)))
        form.addRow("Visible", visible)

        start = QtWidgets.QCheckBox()
        start.setChecked(bool(canvas.get("show_on_profile_start")))
        start.toggled.connect(lambda v: self._set_canvas("show_on_profile_start", bool(v)))
        form.addRow("Show at profile start", start)

        interactive = QtWidgets.QCheckBox()
        interactive.setChecked(bool(canvas.get("interactive")))
        interactive.setToolTip(
            "On this page’s live overlay, touch or click widgets bound to vJoy or GEX states. "
            "Empty space stays click-through. Physical bindings stay display-only."
        )
        interactive.toggled.connect(lambda v: self._set_canvas("interactive", bool(v)))
        form.addRow("Interactive", interactive)
        touch_hint = QtWidgets.QLabel(
            "vJoy buttons are held while pressed. A state button tap inverts the state. Sticks and hats return to center on lift; faders keep their value."
        )
        touch_hint.setWordWrap(True)
        form.addRow(touch_hint)

        mode = QtWidgets.QComboBox()
        labels = [("chroma", "chroma"), ("image", "image"), ("onscreen", "on-screen")]
        for stored, label in labels:
            mode.addItem(label, stored)
        current = normalize_background_mode(canvas.get("background_mode"))
        mode.setCurrentIndex(next((i for i, (stored, _) in enumerate(labels) if stored == current), 0))
        mode.currentIndexChanged.connect(lambda _i, box=mode: self._on_background_mode(box.currentData()))
        form.addRow("Background", mode)

        if onscreen:
            screens = list_overlay_screens()
            monitor = QtWidgets.QComboBox()
            selected = resolve_overlay_screen(canvas)
            selected_index = selected["index"] if selected else 0
            for screen in screens:
                monitor.addItem(screen["label"], screen["index"])
            if screens:
                pos = monitor.findData(selected_index)
                if pos >= 0:
                    monitor.setCurrentIndex(pos)
            monitor.currentIndexChanged.connect(lambda _i, box=monitor: self._on_monitor(box.currentData()))
            form.addRow("Monitor", monitor)
            if bool(canvas.get("interactive")):
                hint = QtWidgets.QLabel("Canvas size follows this monitor. Interactive is on: widgets capture touch; empty space passes through to the screen behind.")
            else:
                hint = QtWidgets.QLabel("Canvas size follows this monitor. The overlay is a transparent, click-through HUD.")
            hint.setWordWrap(True)
            form.addRow(hint)
        else:
            chroma = ColorButton(canvas.get("chroma_color") or "#00FF00", preserve_transparent=True)
            chroma.color_changed.connect(lambda v: self._set_canvas("chroma_color", v))
            form.addRow("Chroma color", chroma)
            chroma_hint = QtWidgets.QLabel(
                "Alpha 0 makes the overlay see-through to the desktop. Windows needs a frameless window for that — use the drag bar to move it. OBS chroma key still needs an opaque color."
            )
            chroma_hint.setWordWrap(True)
            form.addRow(chroma_hint)

            path_row = QtWidgets.QWidget()
            path_layout = QtWidgets.QHBoxLayout(path_row)
            path_layout.setContentsMargins(0, 0, 0, 0)
            path_edit = QtWidgets.QLineEdit(canvas.get("image_path") or "")
            browse = QtWidgets.QPushButton("...")
            browse.setFixedWidth(28)

            def _browse():
                fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Background image", path_edit.text(), "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
                if fname:
                    path_edit.setText(fname)
                    self._set_canvas("image_path", fname)

            browse.clicked.connect(_browse)
            path_edit.editingFinished.connect(lambda: self._set_canvas("image_path", path_edit.text()))
            path_layout.addWidget(path_edit)
            path_layout.addWidget(browse)
            form.addRow("Image", path_row)

        width = QtWidgets.QSpinBox()
        width.setRange(160, 7680)
        width.setValue(int(canvas.get("width") or 1280))
        height = QtWidgets.QSpinBox()
        height.setRange(120, 4320)
        height.setValue(int(canvas.get("height") or 720))
        width.setEnabled(not onscreen)
        height.setEnabled(not onscreen)
        if not onscreen:
            width.valueChanged.connect(lambda v: self._set_canvas("width", int(v)))
            height.valueChanged.connect(lambda v: self._set_canvas("height", int(v)))
        form.addRow("Width", width)
        form.addRow("Height", height)

        grid = QtWidgets.QSpinBox()
        grid.setRange(1, 64)
        grid.setValue(int(canvas.get("grid_size") or 8))
        grid.valueChanged.connect(lambda v: self._set_canvas("grid_size", int(v)))
        form.addRow("Grid size", grid)

        snap = QtWidgets.QCheckBox()
        snap.setChecked(bool(canvas.get("snap_to_grid", True)))
        snap.toggled.connect(lambda v: self._set_canvas("snap_to_grid", v))
        form.addRow("Snap to grid", snap)
        self._build_guides(form, canvas)

        if not onscreen:
            top = QtWidgets.QCheckBox()
            top.setChecked(bool(canvas.get("always_on_top")))
            top.toggled.connect(lambda v: self._set_canvas("always_on_top", v))
            form.addRow("Always on top", top)

            frameless = QtWidgets.QCheckBox()
            frameless.setChecked(bool(canvas.get("frameless")))
            frameless.toggled.connect(lambda v: self._set_canvas("frameless", v))
            form.addRow("Frameless", frameless)

            drag = QtWidgets.QCheckBox()
            drag.setChecked(bool(canvas.get("show_drag_bar", True)))
            drag.toggled.connect(lambda v: self._set_canvas("show_drag_bar", v))
            form.addRow("Overlay drag bar", drag)

        reset = QtWidgets.QPushButton("Reset position")
        if onscreen:
            reset.setToolTip("Use the primary monitor if the saved display is gone.")
        else:
            reset.setToolTip("Clear the saved window position and center this overlay. Also used if the saved monitor is gone.")
        reset.clicked.connect(lambda _=False: self._reset_page_position())
        form.addRow(reset)
        self._build_toggle_binding()

    def _on_background_mode(self, stored: str):
        if self._building:
            return
        stored = normalize_background_mode(stored)
        previous = normalize_background_mode(self.scene.canvas.get("background_mode"))
        if stored == previous:
            return
        self._building = True
        try:
            if stored == "onscreen" and previous != "onscreen":
                self.scene.canvas["capture_width"] = int(self.scene.canvas.get("width") or 1280)
                self.scene.canvas["capture_height"] = int(self.scene.canvas.get("height") or 720)
                self.scene.canvas["background_mode"] = stored
                if not apply_onscreen_geometry(self.scene):
                    self.scene._dirty = True
                    self.scene.changed.emit()
            elif stored != "onscreen" and previous == "onscreen":
                self.scene.canvas["background_mode"] = stored
                restore_w = int(self.scene.canvas.get("capture_width") or 1280)
                restore_h = int(self.scene.canvas.get("capture_height") or 720)
                self.scene.canvas["width"] = restore_w
                self.scene.canvas["height"] = restore_h
                self.scene._dirty = True
                self.scene.changed.emit()
            else:
                self.scene.canvas["background_mode"] = stored
                self.scene._dirty = True
                self.scene.changed.emit()
        finally:
            self._building = False
        self._schedule_rebuild()

    def _on_monitor(self, index):
        if self._building or index is None:
            return
        self._building = True
        try:
            screens = list_overlay_screens()
            chosen = next((screen for screen in screens if screen["index"] == int(index)), None)
            self.scene.canvas["monitor_index"] = int(index)
            if chosen:
                self.scene.canvas["monitor_name"] = chosen["name"]
            apply_onscreen_geometry(self.scene, monitor_index=int(index))
        finally:
            self._building = False
        self._schedule_rebuild()

    def _set_canvas(self, key, value):
        if self.scene.canvas.get(key) == value:
            return
        self.scene.canvas[key] = value
        self.scene._dirty = True
        self.scene.changed.emit()

    def _on_page_name(self, name: str):
        if self._building:
            return
        self.scene.rename_page(name)

    def _reset_page_position(self):
        if self._building:
            return
        self.scene.reset_page_position()
        if is_onscreen_mode(self.scene.canvas):
            apply_onscreen_geometry(self.scene)

    def _bind_live(self, widget, getter):
        def _sync(w=widget, get=getter):
            try:
                value = get()
            except RuntimeError:
                return
            w.blockSignals(True)
            w.setValue(value)
            w.blockSignals(False)

        self._live_fields.append(_sync)

    def _build_guides(self, form, canvas: dict):
        buttons = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        add_v = QtWidgets.QPushButton("Add vertical")
        add_v.setToolTip("Add a vertical guide. Widgets snap left, center, or right to it.")
        add_v.clicked.connect(lambda _=False: self._add_guide("v"))
        add_h = QtWidgets.QPushButton("Add horizontal")
        add_h.setToolTip("Add a horizontal guide. Widgets snap top, center, or bottom to it.")
        add_h.clicked.connect(lambda _=False: self._add_guide("h"))
        row.addWidget(add_v)
        row.addWidget(add_h)
        row.addStretch()
        form.addRow("Guides", buttons)
        hint = QtWidgets.QLabel("Drag a guide on the canvas, or enter a percent of width (vertical) or height (horizontal).")
        hint.setWordWrap(True)
        form.addRow(hint)
        for guide in canvas.get("guides") or []:
            form.addRow("", self._guide_row(guide))

    def _guide_row(self, guide: dict) -> QtWidgets.QWidget:
        axis = "H" if guide.get("axis") == "h" else "V"
        gid = guide.get("id")
        percent = max(0.0, min(100.0, float(guide.get("position") or 0) * 100.0))
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        axis_label = QtWidgets.QLabel(axis)
        axis_label.setFixedWidth(14)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(0, 1000)
        slider.setValue(int(round(percent * 10)))
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(0.0, 100.0)
        spin.setDecimals(1)
        spin.setSuffix(" %")
        spin.setValue(percent)
        spin.setMaximumWidth(84)
        color = ColorButton(guide.get("color") or DEFAULT_GUIDE_COLOR)
        color.setFixedWidth(36)
        delete = QtWidgets.QPushButton("×")
        delete.setFixedWidth(24)
        delete.setToolTip("Remove this guide")

        def _from_slider(v, box=spin, ident=gid):
            pct = v / 10.0
            box.blockSignals(True)
            box.setValue(pct)
            box.blockSignals(False)
            self.scene.update_guide(ident, position=pct / 100.0)

        def _from_spin(v, bar=slider, ident=gid):
            bar.blockSignals(True)
            bar.setValue(int(round(float(v) * 10)))
            bar.blockSignals(False)
            self.scene.update_guide(ident, position=float(v) / 100.0)

        slider.valueChanged.connect(_from_slider)
        spin.valueChanged.connect(_from_spin)
        color.color_changed.connect(lambda v, ident=gid: self.scene.update_guide(ident, color=v))
        delete.clicked.connect(lambda _=False, ident=gid: self._remove_guide(ident))
        self._bind_live(spin, lambda ident=gid: self._guide_percent(ident))
        self._bind_live(slider, lambda ident=gid: int(round(self._guide_percent(ident) * 10)))
        layout.addWidget(axis_label)
        layout.addWidget(slider, 1)
        layout.addWidget(spin)
        layout.addWidget(color)
        layout.addWidget(delete)
        return row

    def _guide_percent(self, guide_id: str) -> float:
        guide = self.scene.guide_by_id(guide_id)
        if not guide:
            return 0.0
        return max(0.0, min(100.0, float(guide.get("position") or 0) * 100.0))

    def _add_guide(self, axis: str):
        if self._building:
            return
        self.scene.add_guide(axis)
        self.rebuild()

    def _remove_guide(self, guide_id: str):
        if self._building:
            return
        self.scene.remove_guide(guide_id)
        self.rebuild()

    def _build_widget(self, item: dict):
        form = self._section("Geometry")
        if self._multi:
            types = sorted({(w.get("type") or "").replace("_", " ") for w in self.scene.selected_widgets()})
            form.addRow("Selection", QtWidgets.QLabel(f"{len(self._edit_ids)} grouped widgets"))
            form.addRow("Types", QtWidgets.QLabel(", ".join(types)))
        else:
            type_label = QtWidgets.QLabel(item.get("type", "").replace("_", " "))
            form.addRow("Type", type_label)
            canvas_w = max(1, int(self.scene.canvas.get("width") or 1280))
            canvas_h = max(1, int(self.scene.canvas.get("height") or 720))
            self._slider_int(
                form,
                "X",
                int(item.get("x") or 0),
                0,
                canvas_w,
                lambda v, wid=item["id"]: self._update(wid, x=int(v)),
            )
            self._slider_int(
                form,
                "Y",
                int(item.get("y") or 0),
                0,
                canvas_h,
                lambda v, wid=item["id"]: self._update(wid, y=int(v)),
            )
        for key, lo, hi in (("w", 8, 4000), ("h", 8, 4000), ("z", -100, 100)):
            spin = QtWidgets.QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(int(self._common_field(lambda w: int(w.get(key) or 0), int(item.get(key) or 0))))
            spin.valueChanged.connect(lambda v, k=key, wid=item["id"]: self._update(wid, **{k: int(v)}))
            form.addRow(key.upper(), spin)

        vis = QtWidgets.QCheckBox()
        self._set_bool_widget(vis, [bool(w.get("visible", True)) for w in self.scene.selected_widgets()] or [bool(item.get("visible", True))])
        vis.stateChanged.connect(lambda _s, wid=item["id"], box=vis: self._on_bool(box, wid, field="visible"))
        form.addRow("Visible", vis)
        self._style_bool(
            form,
            item,
            "auto_scale_font",
            "Scale font with size",
            tooltip="Keep the same relative font size when this widget is resized.",
        )

        label_form = self._section("Label")
        if not self._multi:
            label = QtWidgets.QLineEdit(item.get("label") or "")
            label.editingFinished.connect(lambda wid=item["id"], w=label: self._update(wid, label=w.text()))
            label_form.addRow("Text", label)
        self._style_bool(label_form, item, "show_label", "Show label")
        self._style_font(label_form, item)
        self._style_color(label_form, item, "font_color", "Font color")
        self._slider_int(
            label_form,
            "Label offset X",
            int(item["style"].get("label_offset_x") or 0),
            -400,
            400,
            lambda v, wid=item["id"]: self._style(wid, label_offset_x=int(v)),
        )
        self._slider_int(
            label_form,
            "Label offset Y",
            int(item["style"].get("label_offset_y") or 0),
            -400,
            400,
            lambda v, wid=item["id"]: self._style(wid, label_offset_y=int(v)),
        )
        widget_type = canonical_widget_type(item.get("type"))
        if widget_type == "label":
            self._style_color(label_form, item, "fill", "Fill")
            self._style_color(label_form, item, "border", "Border")
            self._style_float(label_form, item, "border_width", "Border width", 0, 20)
            self._style_float(label_form, item, "corner_radius", "Corner radius", 0, 200)

        look = self._section("Appearance")
        self._build_palettes(look, item)
        self._opacity_slider(look, item)
        if widget_type == "button":
            shape = QtWidgets.QComboBox()
            shape.addItems(["rounded", "rect", "circle", "pill"])
            shape.setCurrentText(item["style"].get("shape") or "rounded")
            shape.currentTextChanged.connect(lambda v, wid=item["id"]: self._style(wid, shape=v))
            look.addRow("Shape", shape)
            self._style_color(look, item, "fill", "Off fill")
            self._style_color(look, item, "fill_on", "On fill")
        elif widget_type == "axis_bar":
            self._orientation_combo(look, item)
            self._style_color(look, item, "fill", "Fill")
            self._style_color(look, item, "indicator", "Dot")
            self._style_float(look, item, "indicator_size", "Dot size", 2, 80)
            self._indicator_shape(look, item)
            self._style_bool(look, item, "show_dot_shadow", "Dot shadow")
            self._style_bool(look, item, "show_dot_crosshair", "Lines through dot")
            self._grid_appearance(look, item)
            self._crosshair_appearance(look, item)
        elif widget_type == "axis_radio":
            self._orientation_combo(look, item, default="horizontal")
            steps = QtWidgets.QSpinBox()
            steps.setRange(2, 32)
            steps.setValue(int(item["style"].get("radio_steps") or 5))
            steps.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Steps", steps)
            self._style_color(look, item, "fill", "Off fill")
            self._style_color(look, item, "fill_on", "On fill")
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type == "axis_fader":
            self._orientation_combo(look, item)
            self._style_color(look, item, "fill", "Track")
            self._style_color(look, item, "fill_bar", "Fill")
            self._style_color(look, item, "fill_on", "Thumb")
            self._style_color(look, item, "grid", "Rungs")
            steps = QtWidgets.QSpinBox()
            steps.setRange(3, 32)
            steps.setValue(int(item["style"].get("radio_steps") or 8))
            steps.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Rungs", steps)
            thumb = QtWidgets.QDoubleSpinBox()
            thumb.setRange(0, 80)
            thumb.setSingleStep(1)
            thumb.setSpecialValueText("One rung")
            thumb.setValue(float(item["style"].get("indicator_size") or 0))
            thumb.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, indicator_size=float(v)))
            look.addRow("Thumb size", thumb)
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type in ("axis_radial", "axis_dial"):
            self._style_color(look, item, "track", "Track")
            self._style_color(look, item, "fill_bar", "Arc")
            self._style_color(look, item, "grid", "Ticks")
            self._style_float(look, item, "needle_width", "Arc width", 4, 40)
            ticks = QtWidgets.QSpinBox()
            ticks.setRange(2, 48)
            ticks.setValue(int(item["style"].get("radio_steps") or 11))
            ticks.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Ticks", ticks)
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type == "axis_encoder":
            self._style_color(look, item, "fill", "Off fill")
            self._style_color(look, item, "fill_on", "On fill")
            self._style_color(look, item, "grid", "Ticks")
            ring = QtWidgets.QDoubleSpinBox()
            ring.setRange(0, 80)
            ring.setSingleStep(1)
            ring.setSpecialValueText("Auto")
            ring.setValue(float(item["style"].get("needle_width") or 0))
            ring.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, needle_width=float(v)))
            look.addRow("Ring thickness", ring)
            ticks = QtWidgets.QSpinBox()
            ticks.setRange(4, 48)
            ticks.setValue(int(item["style"].get("radio_steps") or 16))
            ticks.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Steps", ticks)
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type in ("axis_stick_square", "axis_stick_circle", "axis_crosshair", "hat"):
            self._style_color(look, item, "fill", "Fill")
            self._style_color(look, item, "indicator", "Dot")
            self._style_float(look, item, "indicator_size", "Dot size", 2, 80)
            if widget_type == "hat":
                positions = QtWidgets.QComboBox()
                positions.addItem("4-position", 4)
                positions.addItem("8-position", 8)
                current = 8 if int(item["style"].get("hat_positions") or 4) >= 8 else 4
                positions.setCurrentIndex(1 if current == 8 else 0)
                positions.currentIndexChanged.connect(
                    lambda _i, box=positions, wid=item["id"]: self._style(wid, hat_positions=int(box.currentData() or 4))
                )
                look.addRow("Positions", positions)
                self._crosshair_appearance(look, item, show_toggle=False)
            else:
                self._indicator_shape(look, item)
                self._style_bool(look, item, "show_dot_shadow", "Dot shadow")
                self._style_bool(look, item, "show_dot_crosshair", "Lines through dot")
                if widget_type in ("axis_stick_circle", "axis_crosshair"):
                    self._angle_step_combo(look, item)
                    rings = QtWidgets.QSpinBox()
                    rings.setRange(1, 8)
                    rings.setValue(int(item["style"].get("ring_count") or 3))
                    rings.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, ring_count=int(v)))
                    look.addRow("Rings", rings)
                self._grid_appearance(look, item)
                self._crosshair_appearance(look, item)
        elif widget_type in ("shape", "panel"):
            self._shape_appearance(look, item)
        elif widget_type == "image":
            self._image_appearance(look, item)
        elif widget_type == "streamdeck":
            self._streamdeck_appearance(look, item)
        elif widget_type != "label":
            self._style_color(look, item, "fill", "Fill")

        self._append_shared_appearance(look, item, widget_type)

    def _build_mixed(self, items: list[dict]):
        types = {item.get("type") for item in items}
        item = items[0]
        form = self._section("Geometry")
        form.addRow("Selection", QtWidgets.QLabel(f"{len(items)} grouped widgets"))
        form.addRow("Types", QtWidgets.QLabel(", ".join(sorted((t or "").replace("_", " ") for t in types))))
        for key, lo, hi in (("w", 8, 4000), ("h", 8, 4000), ("z", -100, 100)):
            spin = QtWidgets.QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(int(self._common_field(lambda w, k=key: int(w.get(k) or 0), int(item.get(key) or 0))))
            spin.valueChanged.connect(lambda v, k=key, wid=item["id"]: self._update(wid, **{k: int(v)}))
            form.addRow(key.upper(), spin)
        vis = QtWidgets.QCheckBox()
        self._set_bool_widget(vis, [bool(w.get("visible", True)) for w in items])
        vis.stateChanged.connect(lambda _s, wid=item["id"], box=vis: self._on_bool(box, wid, field="visible"))
        form.addRow("Visible", vis)
        self._style_bool(
            form,
            item,
            "auto_scale_font",
            "Scale font with size",
            tooltip="Keep the same relative font size when this widget is resized.",
        )

        label_form = self._section("Label")
        self._style_bool(label_form, item, "show_label", "Show label")
        self._style_font(label_form, item)
        self._style_color(label_form, item, "font_color", "Font color")
        self._slider_int(
            label_form,
            "Label offset X",
            int(item["style"].get("label_offset_x") or 0),
            -400,
            400,
            lambda v, wid=item["id"]: self._style(wid, label_offset_x=int(v)),
        )
        self._slider_int(
            label_form,
            "Label offset Y",
            int(item["style"].get("label_offset_y") or 0),
            -400,
            400,
            lambda v, wid=item["id"]: self._style(wid, label_offset_y=int(v)),
        )

        look = self._section("Appearance")
        if len(types) == 1:
            self._build_palettes(look, item)
        self._opacity_slider(look, item)
        self._style_color(look, item, "fill", "Fill")
        if types <= {"button"}:
            self._style_color(look, item, "fill_on", "On fill")
        if types <= {"axis_bar", "axis_radio", "axis_fader"}:
            self._orientation_combo(look, item)
        if types <= {"axis_stick_circle", "axis_crosshair"}:
            self._angle_step_combo(look, item)
        if types <= {"axis_bar", "axis_stick_square", "axis_stick_circle", "axis_crosshair"}:
            self._style_color(look, item, "indicator", "Dot")
            self._indicator_shape(look, item)
            self._style_bool(look, item, "show_dot_shadow", "Dot shadow")
            self._style_bool(look, item, "show_dot_crosshair", "Lines through dot")
            self._grid_appearance(look, item)
            self._crosshair_appearance(look, item)
        invert_types = {
            "axis_bar",
            "axis_radio",
            "axis_fader",
            "axis_radial",
            "axis_encoder",
            "axis_dial",
        }
        if types <= invert_types:
            self._style_bool(look, item, "invert_display", "Invert")
        if types <= {"axis_bar"}:
            self._axis_appearance(look, item, self._bar_label_ends(item), invert=False)
        elif types <= {"axis_stick_square", "axis_stick_circle", "axis_crosshair", "hat"}:
            self._axis_appearance(look, item)
        if not types.intersection({"label", "panel", "shape", "image", "streamdeck"}):
            self._deadzone_field(look, item)
        if types <= {"button"}:
            self._border_appearance(look, item, colors=(("border", "Off border"), ("border_on", "On border")))
        elif types <= {"axis_radio"}:
            self._border_appearance(look, item, colors=(("border", "Off border"), ("border_on", "Active border")), include_radius=False)
        else:
            include_radius = not types <= set(NO_CORNER_RADIUS_TYPES)
            self._border_appearance(look, item, include_radius=include_radius)

    def _common_field(self, getter, fallback=None):
        items = self.scene.selected_widgets()
        if not items:
            return fallback
        values = [getter(w) for w in items]
        if all(v == values[0] for v in values):
            return values[0]
        return fallback

    def _set_bool_widget(self, box: QtWidgets.QCheckBox, values: list[bool]):
        if len(values) > 1 and not all(v == values[0] for v in values):
            box.setTristate(True)
            box.setCheckState(QtCore.Qt.PartiallyChecked)
        else:
            box.setChecked(bool(values[0]) if values else False)

    def _on_bool(self, box: QtWidgets.QCheckBox, widget_id: str, field: str | None = None, style_key: str | None = None):
        if self._building:
            return
        if box.isTristate() and box.checkState() == QtCore.Qt.PartiallyChecked:
            return
        box.setTristate(False)
        value = box.isChecked()
        if field:
            self._update(widget_id, **{field: value})
        elif style_key:
            self._style(widget_id, **{style_key: value})

    def _bar_label_ends(self, item: dict) -> str | None:
        items = self.scene.selected_widgets() if self._multi else [item]
        vertical = []
        for widget in items:
            orient = ((widget.get("style") or {}).get("orientation") or "vertical").casefold()
            vertical.append(orient != "horizontal")
        if vertical and all(vertical):
            return "ns"
        if vertical and not any(vertical):
            return "ew"
        return "all"

    def _axis_label_fields(self, form, item, ends: str | None = "all"):
        self._style_bool(form, item, "show_axis_labels", "Axis labels")
        pairs = (
            ("axis_label_n", "North"),
            ("axis_label_s", "South"),
            ("axis_label_e", "East"),
            ("axis_label_w", "West"),
        )
        if ends == "ns":
            pairs = pairs[:2]
        elif ends == "ew":
            pairs = pairs[2:]
        for key, title in pairs:
            edit = QtWidgets.QLineEdit(item["style"].get(key) or "")
            edit.editingFinished.connect(lambda wid=item["id"], k=key, w=edit: self._style(wid, **{k: w.text()}))
            form.addRow(title, edit)
        spread = item["style"].get("axis_label_spread")
        self._slider_int(
            form,
            "Distance from center",
            100 if spread is None else int(spread),
            0,
            100,
            lambda v, wid=item["id"]: self._style(wid, axis_label_spread=int(v)),
            tooltip="How far N/S/E/W labels sit from the center. 100 places them near the border with even padding.",
        )
        self._style_font(form, item, prefix="axis_label_")
        self._style_color(form, item, "axis_label_font_color", "Axis label color")

    def _orientation_combo(self, form, item, default="vertical"):
        orient = QtWidgets.QComboBox()
        orient.addItems(["vertical", "horizontal"])
        orient.setCurrentText(item["style"].get("orientation") or default)
        orient.currentTextChanged.connect(lambda v, wid=item["id"]: self._set_orientation(wid, v))
        form.addRow("Orientation", orient)

    def _set_orientation(self, widget_id: str, orientation: str):
        if self._building:
            return
        ids = list(self._edit_ids or [widget_id])
        self.scene._suspend += 1
        try:
            for wid in ids:
                item = self.scene.widget_by_id(wid)
                if not item:
                    continue
                previous = (item["style"].get("orientation") or "vertical")
                fields = {"style": {"orientation": orientation}}
                if previous != orientation:
                    width, height = int(item["w"]), int(item["h"])
                    vertical = orientation != "horizontal"
                    if vertical and width > height:
                        fields["w"], fields["h"] = height, width
                    elif not vertical and height > width:
                        fields["w"], fields["h"] = height, width
                self.scene.apply_widget_update(wid, **fields)
        finally:
            self.scene._suspend = max(0, self.scene._suspend - 1)
            self.scene._dirty = True
            self.scene._emit()
        self.rebuild()

    def _indicator_shape(self, form, item):
        shape = QtWidgets.QComboBox()
        shape.addItems(["circle", "square"])
        shape.setCurrentText(item["style"].get("indicator_shape") or "circle")
        shape.currentTextChanged.connect(lambda v, wid=item["id"]: self._style(wid, indicator_shape=v))
        form.addRow("Dot shape", shape)

    def _angle_step_combo(self, form, item):
        combo = QtWidgets.QComboBox()
        for label, value in (("Off", 0), ("15°", 15), ("30°", 30), ("45°", 45)):
            combo.addItem(label, value)
        current = int(item["style"].get("angle_step") or 0)
        index = {0: 0, 15: 1, 30: 2, 45: 3}.get(current, 0)
        combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(
            lambda _i, wid=item["id"], box=combo: self._style(wid, angle_step=int(box.currentData()))
        )
        form.addRow("Angle lines", combo)

    def _slider_int(self, form, title: str, value: int, lo: int, hi: int, on_change, tooltip=None):
        value = int(value)
        lo, hi = int(lo), int(hi)
        if hi < lo:
            lo, hi = hi, lo
        if value < lo:
            lo = value
        if value > hi:
            hi = value
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        spin = QtWidgets.QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(value)
        spin.setMaximumWidth(80)
        if tooltip:
            row.setToolTip(tooltip)
            slider.setToolTip(tooltip)
            spin.setToolTip(tooltip)

        def _from_slider(v, box=spin, cb=on_change):
            box.blockSignals(True)
            box.setValue(v)
            box.blockSignals(False)
            cb(v)

        def _from_spin(v, bar=slider, cb=on_change):
            bar.blockSignals(True)
            bar.setValue(v)
            bar.blockSignals(False)
            cb(v)

        slider.valueChanged.connect(_from_slider)
        spin.valueChanged.connect(_from_spin)
        layout.addWidget(slider, 1)
        layout.addWidget(spin, 0)
        form.addRow(title, row)

    def _build_palettes(self, form, item: dict):
        widget_type = palette_type(item.get("type"))
        form.addRow("Default palettes", self._palette_swatch_row(widget_type, list_builtin_palettes(widget_type), editable=False))
        form.addRow("User palettes", self._palette_swatch_row(widget_type, list_user_palettes(widget_type), editable=True, add_new=True))

    def _palette_swatch_row(self, widget_type: str, palettes: list, editable: bool, add_new: bool = False) -> QtWidgets.QWidget:
        host = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for pal in palettes:
            swatch = PaletteSwatch(pal.get("colors") or {}, pal.get("label") or "Saved palette", editable=editable)
            swatch.apply_requested.connect(lambda p=pal: self._apply_palette(p))
            if editable:
                swatch.update_requested.connect(lambda pid=pal.get("id"): self._update_saved_palette(widget_type, pid))
                swatch.delete_requested.connect(lambda pid=pal.get("id"): self._delete_saved_palette(widget_type, pid))
            layout.addWidget(swatch)
        if add_new:
            add_btn = QtWidgets.QPushButton("+")
            add_btn.setFixedSize(28, 28)
            add_btn.setToolTip("Save the current colors as a new user palette for this widget type.")
            add_btn.clicked.connect(lambda _=False: self._add_saved_palette(widget_type))
            layout.addWidget(add_btn)
        layout.addStretch()
        return host

    def _current_palette_colors(self) -> dict[str, str]:
        items = self.scene.selected_widgets()
        if not items:
            return extract_colors({}, "button")
        item = items[0]
        return extract_colors(item.get("style") or {}, item.get("type"))

    def _apply_palette(self, palette: dict):
        colors = palette.get("colors") or {}
        payload = {key: colors[key] for key in COLOR_KEYS if key in colors}
        if not payload or not self._edit_ids:
            return
        self._style(self._edit_ids[0], **payload)
        self.rebuild()

    def _add_saved_palette(self, widget_type: str):
        add_palette(widget_type, self._current_palette_colors())
        self.rebuild()

    def _update_saved_palette(self, widget_type: str, palette_id: str):
        if not palette_id or palette_id in BUILTIN_IDS:
            return
        update_palette(widget_type, palette_id, self._current_palette_colors())
        self.rebuild()

    def _delete_saved_palette(self, widget_type: str, palette_id: str):
        if not palette_id or palette_id in BUILTIN_IDS:
            return
        delete_palette(widget_type, palette_id)
        self.rebuild()

    def _look_heading(self, form: QtWidgets.QFormLayout, title: str):
        label = QtWidgets.QLabel(title)
        label.setStyleSheet("font-weight: bold; padding-top: 8px;")
        form.addRow(label)

    def _opacity_slider(self, form, item: dict):
        raw = (item.get("style") or {}).get("opacity")
        try:
            value = 100 if raw is None else int(round(float(raw) * 100.0))
        except (TypeError, ValueError):
            value = 100
        value = max(0, min(100, value))
        self._slider_int(
            form,
            "Opacity",
            value,
            0,
            100,
            lambda v, wid=item["id"]: self._style(wid, opacity=max(0.0, min(1.0, float(v) / 100.0))),
            tooltip="Widget opacity (percent).",
        )

    def _deadzone_field(self, form, item: dict):
        dead = QtWidgets.QDoubleSpinBox()
        dead.setRange(0.0, 0.9)
        dead.setSingleStep(0.01)
        dead.setValue(float(item["style"].get("deadzone") or 0))
        dead.setToolTip("Overlay only: axis values inside this range around center are drawn as zero. Does not change GEX mappings.")
        dead.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, deadzone=float(v)))
        form.addRow("Deadzone display", dead)

    def _axis_appearance(self, form, item: dict, ends: str | None = "all", invert: bool = False):
        self._look_heading(form, "Axis")
        if invert:
            self._style_bool(form, item, "invert_display", "Invert display")
        self._axis_label_fields(form, item, ends)

    def _border_appearance(self, form, item: dict, colors=None, include_radius: bool = True):
        self._look_heading(form, "Border")
        if colors:
            for key, title in colors:
                self._style_color(form, item, key, title)
        else:
            self._style_color(form, item, "border", "Border")
        self._style_float(form, item, "border_width", "Border width", 0, 20)
        if include_radius:
            self._style_float(form, item, "corner_radius", "Corner radius", 0, 200)

    def _append_shared_appearance(self, look, item: dict, widget_type: str):
        axis_label_types = {"axis_bar", "axis_stick_square", "axis_stick_circle", "axis_crosshair", "hat"}
        if widget_type in axis_label_types:
            ends = self._bar_label_ends(item) if widget_type == "axis_bar" else "all"
            self._axis_appearance(look, item, ends, invert=widget_type == "axis_bar")
        if widget_type not in ("label", "panel", "shape", "image", "streamdeck"):
            self._deadzone_field(look, item)
        if widget_type == "button":
            self._border_appearance(look, item, colors=(("border", "Off border"), ("border_on", "On border")))
        elif widget_type == "axis_radio":
            self._border_appearance(
                look,
                item,
                colors=(("border", "Off border"), ("border_on", "Active border")),
                include_radius=False,
            )
        elif widget_type not in ("label", "shape", "panel", "image", "streamdeck"):
            self._border_appearance(look, item, include_radius=widget_type not in NO_CORNER_RADIUS_TYPES)
        if widget_type not in ("label", "panel", "shape", "image", "streamdeck") and not self._multi:
            self._build_binding(item)

    def _grid_appearance(self, form, item: dict):
        self._look_heading(form, "Grid")
        self._style_bool(form, item, "show_grid", "Show grid")
        self._style_color(form, item, "grid", "Grid")
        self._style_float(form, item, "grid_width", "Line width", 0.5, 12)
        self._style_bool(
            form,
            item,
            "grid_fade",
            "Fade at border",
            tooltip="Keep the grid full strength in the center and fade it toward the widget border.",
        )

    def _crosshair_appearance(self, form, item: dict, show_toggle: bool = True):
        self._look_heading(form, "Crosshairs")
        if show_toggle:
            self._style_bool(form, item, "show_center_line", "Show crosshairs")
        self._style_color(form, item, "crosshair", "Crosshair")

    def _shape_appearance(self, form, item: dict):
        kind = QtWidgets.QComboBox()
        current = normalize_shape_kind(item["style"].get("shape_kind"))
        for stored, label in SHAPE_KIND_LABELS:
            kind.addItem(label, stored)
        index = kind.findData(current)
        if index >= 0:
            kind.setCurrentIndex(index)
        kind.currentIndexChanged.connect(lambda _i, box=kind, wid=item["id"]: self._set_shape_kind(wid, box.currentData()))
        form.addRow("Shape", kind)
        self._style_bool(
            form,
            item,
            "shape_closed",
            "Closed",
            tooltip="Connect the last point back to the first. Off for an open line or path.",
        )
        hint = QtWidgets.QLabel("Freeform: double-click the outline to add a point. Drag points, then drag the yellow handles to curve a corner. Delete removes the selected point.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self._style_color(form, item, "fill", "Fill")
        self._look_heading(form, "Border")
        self._style_color(form, item, "border", "Border")
        self._style_float(form, item, "border_width", "Border width", 0, 20)
        if current == "rectangle":
            self._style_float(form, item, "corner_radius", "Corner radius", 0, 200)

    def _image_appearance(self, form, item: dict):
        path_row = QtWidgets.QWidget()
        path_layout = QtWidgets.QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_edit = QtWidgets.QLineEdit(item["style"].get("image_path") or "")
        browse = QtWidgets.QPushButton("...")
        browse.setFixedWidth(28)
        browse.clicked.connect(lambda _=False, wid=item["id"]: self._browse_image(wid))
        path_edit.editingFinished.connect(lambda wid=item["id"], w=path_edit: self._style(wid, image_path=w.text()))
        path_layout.addWidget(path_edit)
        path_layout.addWidget(browse)
        form.addRow("Image", path_row)
        self._style_bool(
            form,
            item,
            "image_keep_aspect",
            "Keep aspect ratio",
            tooltip="Fit the picture inside the widget. Off stretches it to the widget size.",
        )
        hint = QtWidgets.QLabel("PNG, WebP, and GIF keep their transparency. Fill is only a backdrop behind those pixels. JPEG has no alpha.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self._style_color(form, item, "fill", "Fill")
        self._look_heading(form, "Border")
        self._style_color(form, item, "border", "Border")
        self._style_float(form, item, "border_width", "Border width", 0, 20)

    def _streamdeck_appearance(self, form, item: dict):
        try:
            from gremlin.ui.streamdeck_device import (
                StreamDeckBridge,
                friendly_streamdeck_name,
            )

            bridge = StreamDeckBridge()
        except Exception:
            form.addRow(QtWidgets.QLabel("Stream Deck bridge is unavailable."))
            return

        style = item.get("style") or {}
        wanted = str(style.get("streamdeck_device_id") or "")
        combo = QtWidgets.QComboBox()
        combo.addItem("First connected", "")
        seen = set()
        for device_id, info in (bridge.devices or {}).items():
            info = info or {}
            label = friendly_streamdeck_name(info.get("name"), info.get("type"), device_id)
            combo.addItem(label, device_id)
            seen.add(device_id)
        if wanted and wanted not in seen:
            combo.addItem(f"Disconnected ({wanted[:8]})", wanted)
        idx = combo.findData(wanted)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _i, w=combo, wid=item["id"]: self._on_streamdeck_device(wid, w.currentData() or "")
        )
        form.addRow("Device", combo)

        follow = bool(style.get("streamdeck_follow_page", True))
        page_combo = QtWidgets.QComboBox()
        device_id = bridge.resolve_overlay_device_id(wanted)
        pages = bridge.list_pages(device_id) if device_id else [1]
        current_page = int(style.get("streamdeck_page") or 1)
        for page in pages:
            name = bridge.page_name(device_id, page) if device_id else f"Page {page}"
            if name and name != f"Page {page}" and not str(name).startswith(f"{page}."):
                label = f"{page}. {name}"
            else:
                label = name or f"Page {page}"
            page_combo.addItem(label, page)
        pidx = page_combo.findData(current_page)
        if pidx < 0:
            page_combo.addItem(f"Page {current_page}", current_page)
            pidx = page_combo.findData(current_page)
        page_combo.setCurrentIndex(pidx if pidx >= 0 else 0)
        page_combo.setEnabled(not follow)
        page_combo.currentIndexChanged.connect(
            lambda _i, w=page_combo, wid=item["id"]: self._style(wid, streamdeck_page=int(w.currentData() or 1))
        )

        follow_box = QtWidgets.QCheckBox()
        follow_box.setChecked(follow)
        follow_box.setToolTip("Show the GEX virtual page currently painted on the hardware.")
        follow_box.stateChanged.connect(
            lambda _s, wid=item["id"], box=follow_box, combo=page_combo: self._on_streamdeck_follow(wid, box, combo)
        )
        form.addRow("Follow hardware page", follow_box)
        form.addRow("Page", page_combo)
        self._style_bool(
            form,
            item,
            "show_bezel",
            "Show bezel",
            tooltip="Draw the Stream Deck body around the keys.",
        )
        fit = QtWidgets.QPushButton("Fit to device")
        fit.setToolTip("Resize this widget to the key layout of the selected Stream Deck.")
        fit.clicked.connect(lambda _=False, wid=item["id"]: self._fit_streamdeck_item(wid, force=True))
        form.addRow(fit)
        hint = QtWidgets.QLabel("Mirrors the selected deck’s keys (and Stream Deck + dials) using the current GEX page art.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self._style_color(form, item, "fill", "Bezel")
        self._look_heading(form, "Border")
        self._style_color(form, item, "border", "Border")
        self._style_float(form, item, "border_width", "Border width", 0, 20)
        self._style_float(form, item, "corner_radius", "Corner radius", 0, 200)

    def _on_streamdeck_follow(self, widget_id: str, box: QtWidgets.QCheckBox, page_combo: QtWidgets.QComboBox):
        if self._building:
            return
        follow = box.isChecked()
        self._style(widget_id, streamdeck_follow_page=bool(follow))
        page_combo.setEnabled(not follow)

    def _on_streamdeck_device(self, widget_id: str, device_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        self.scene.push_undo()
        item["style"]["streamdeck_device_id"] = device_id or ""
        self._fit_streamdeck_geometry(item)
        self.scene._dirty = True
        self.scene._emit()
        self.rebuild()

    def _fit_streamdeck_item(self, widget_id: str, force: bool = False):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        self.scene.push_undo()
        self._fit_streamdeck_geometry(item, force=force)
        self.scene._dirty = True
        self.scene._emit()
        self.rebuild()

    def _fit_streamdeck_geometry(self, item: dict, force: bool = True):
        from .model import DEFAULT_SIZES
        from .widgets import streamdeck_preferred_size

        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            bridge = StreamDeckBridge()
            device_id = bridge.resolve_overlay_device_id(str((item.get("style") or {}).get("streamdeck_device_id") or ""))
            info = bridge.devices.get(device_id, {}) if device_id else {}
            width, height = streamdeck_preferred_size((info or {}).get("type"))
        except Exception:
            width, height = DEFAULT_SIZES.get("streamdeck", (320, 208))
        current = (int(item.get("w") or 0), int(item.get("h") or 0))
        default = tuple(int(v) for v in DEFAULT_SIZES.get("streamdeck", (320, 208)))
        if not force and current not in (default, (0, 0)):
            return
        canvas_w = max(32, int(self.scene.canvas.get("width") or 1280))
        canvas_h = max(32, int(self.scene.canvas.get("height") or 720))
        scale = min(1.0, canvas_w / max(1, width), canvas_h / max(1, height))
        width = max(48, int(round(width * scale)))
        height = max(48, int(round(height * scale)))
        cx = int(item.get("x") or 0) + int(item.get("w") or 0) / 2.0
        cy = int(item.get("y") or 0) + int(item.get("h") or 0) / 2.0
        item["w"] = width
        item["h"] = height
        item["x"] = max(0, min(canvas_w - width, int(round(cx - width / 2.0))))
        item["y"] = max(0, min(canvas_h - height, int(round(cy - height / 2.0))))

    def _browse_image(self, widget_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        start = (item.get("style") or {}).get("image_path") or ""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Overlay image",
            start,
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif)",
        )
        if not fname:
            return
        self.scene.push_undo()
        item["style"]["image_path"] = fname
        self._fit_item_to_image(item, fname)
        self.scene._dirty = True
        self.scene._emit()
        self.rebuild()

    def _fit_item_to_image(self, item: dict, path: str):
        image = QtGui.QImage(path)
        if image.isNull():
            return
        canvas_w = max(32, int(self.scene.canvas.get("width") or 1280))
        canvas_h = max(32, int(self.scene.canvas.get("height") or 720))
        scale = min(1.0, canvas_w / max(1, image.width()), canvas_h / max(1, image.height()))
        width = max(16, int(round(image.width() * scale)))
        height = max(16, int(round(image.height() * scale)))
        cx = int(item.get("x") or 0) + int(item.get("w") or 0) / 2.0
        cy = int(item.get("y") or 0) + int(item.get("h") or 0) / 2.0
        item["w"] = width
        item["h"] = height
        item["x"] = max(0, min(canvas_w - width, int(round(cx - width / 2.0))))
        item["y"] = max(0, min(canvas_h - height, int(round(cy - height / 2.0))))

    def _set_shape_kind(self, widget_id: str, kind):
        if self._building:
            return
        kind = normalize_shape_kind(kind)
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        self.scene.push_undo()
        item["style"]["shape_kind"] = kind
        item["style"]["shape_closed"] = kind != "line"
        item["points"] = default_shape_points(kind)
        self.scene._dirty = True
        self.scene._emit()
        self.rebuild()

    def _style_color(self, form, item, key, title):
        values = [(w.get("style") or {}).get(key) for w in self.scene.selected_widgets()] or [item["style"].get(key)]
        same = all(v == values[0] for v in values)
        btn = ColorButton(values[0] or "#ffffff")
        if not same:
            btn.setToolTip("Multiple values — pick a color to apply to all")
        btn.color_changed.connect(lambda v, wid=item["id"], k=key: self._style(wid, **{k: v}))
        form.addRow(title, btn)

    def _style_float(self, form, item, key, title, lo, hi, step=0.5):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(float(item["style"].get(key) or lo))
        spin.valueChanged.connect(lambda v, wid=item["id"], k=key: self._style(wid, **{k: float(v)}))
        form.addRow(title, spin)

    def _style_bool(self, form, item, key, title, tooltip=None):
        fallback = bool(default_style(item.get("type") or "button").get(key, False))
        values = [bool((w.get("style") or {}).get(key, fallback)) for w in self.scene.selected_widgets()]
        if not values:
            values = [bool(item["style"].get(key, fallback))]
        box = QtWidgets.QCheckBox()
        self._set_bool_widget(box, values)
        if tooltip:
            box.setToolTip(tooltip)
        box.stateChanged.connect(lambda _s, wid=item["id"], k=key, b=box: self._on_bool(b, wid, style_key=k))
        form.addRow(title, box)

    def _style_font(self, form, item, prefix=""):
        family_key = f"{prefix}font_family"
        size_key = f"{prefix}font_size"
        bold_key = f"{prefix}font_bold"
        combo = QtWidgets.QFontComboBox()
        family = item["style"].get(family_key) or item["style"].get("font_family") or "Segoe UI"
        combo.setCurrentFont(QtGui.QFont(family))
        idx = combo.findText(family)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.currentTextChanged.connect(lambda v, wid=item["id"], k=family_key: self._style(wid, **{k: v}))
        size = QtWidgets.QSpinBox()
        size.setRange(6, 192)
        size.setValue(effective_font_size(item, size_key))
        size.setToolTip("Drawn font size. Updates while the widget is resized when Scale font with size is on.")
        size.valueChanged.connect(lambda v, wid=item["id"], k=size_key: self._style(wid, **{k: int(v)}))
        self._bind_live(size, lambda it=item, k=size_key: effective_font_size(it, k))
        bold = QtWidgets.QCheckBox()
        bold.setChecked(bool(item["style"].get(bold_key, item["style"].get("font_bold", True))))
        bold.toggled.connect(lambda v, wid=item["id"], k=bold_key: self._style(wid, **{k: v}))
        label = "Axis font" if prefix else "Font"
        form.addRow(label, combo)
        form.addRow(f"{label} size", size)
        form.addRow(f"{label} bold", bold)

    def _build_toggle_binding(self):
        binding = normalize_toggle_binding(self.scene.canvas.get("toggle_binding"))
        # Canvas show/hide is a button (or state) assignment — not a free-form
        # axis/hat binding editor. Force button so Input type / Invert stay hidden.
        binding["input_type"] = "button"
        self.scene.canvas["toggle_binding"] = binding
        item = {"id": CANVAS_TOGGLE_ID, "type": "button", "binding": binding}
        self._build_channel(
            item,
            "binding",
            "Toggle overlay",
            force_type="button",
            allow_none=True,
            show_clear=True,
            show_invert=False,
            extra_hint="While the profile is running, press this button to show or hide this page’s overlay window.",
        )

    def _build_binding(self, item: dict):
        if widget_needs_xy(item.get("type")):
            self._build_channel(item, "binding", "Axis X", force_type="axis")
            self._build_channel(item, "binding_y", "Axis Y", force_type="axis")
            return
        widget_type = item.get("type")
        force = None
        if widget_type == "button":
            force = "button"
        elif widget_type == "hat":
            force = "hat"
        elif widget_type and str(widget_type).startswith("axis"):
            force = "axis"
        self._build_channel(item, "binding", "Binding", force_type=force)

    def _channel_binding(self, item: dict, channel: str) -> dict:
        binding = item.get(channel)
        if not isinstance(binding, dict):
            binding = {}
            item[channel] = binding
        return binding

    def _build_channel(
        self,
        item: dict,
        channel: str,
        title: str,
        force_type: str | None = None,
        allow_none: bool = False,
        extra_hint: str | None = None,
        show_clear: bool = False,
        show_invert: bool = True,
    ):
        form = self._section(title)
        binding = self._channel_binding(item, channel)
        sources = ["physical", "vjoy"]
        if force_type != "axis" or not widget_needs_xy(item.get("type")):
            sources.append("state")
        source = QtWidgets.QComboBox()
        source.addItems(sources)
        current_source = binding.get("source") or "physical"
        if current_source not in sources:
            current_source = "physical"
        source.setCurrentText(current_source)
        source.currentTextChanged.connect(lambda v, wid=item["id"], ch=channel: self._bind(wid, ch, rebuild=True, source=v))
        form.addRow("Source", source)

        if source.currentText() == "state":
            names = [""]
            try:
                from gremlin.ui import state_device

                names.extend(state_device.StateData().getStateNames())
            except Exception:
                pass
            combo = QtWidgets.QComboBox()
            combo.setEditable(True)
            combo.addItems(names)
            combo.setCurrentText(binding.get("state_name") or "")
            combo.currentTextChanged.connect(lambda v, wid=item["id"], ch=channel: self._bind(wid, ch, state_name=v, input_type="state"))
            form.addRow("State", combo)
            self._finish_channel(form, item, channel, extra_hint, show_clear)
            return

        device_box = QtWidgets.QComboBox()
        if source.currentText() == "vjoy":
            for dev in gremlin.joystick_handling.vjoy_devices(connected_only=False) or []:
                device_box.addItem(f"vJoy {dev.vjoy_id} ({dev.name})", dev)
            current = int(binding.get("vjoy_id") or 0)
            for i in range(device_box.count()):
                if getattr(device_box.itemData(i), "vjoy_id", None) == current:
                    device_box.setCurrentIndex(i)
                    break
            shown = device_box.currentData()
            if shown is not None and current <= 0:
                binding["vjoy_id"] = int(shown.vjoy_id)
                binding["device_guid"] = str(shown.device_guid)
                binding["device_name"] = shown.name
                item.setdefault(channel, {}).update(
                    {
                        "vjoy_id": binding["vjoy_id"],
                        "device_guid": binding["device_guid"],
                        "device_name": binding["device_name"],
                    }
                )
                self.scene._dirty = True
        else:
            devices = gremlin.joystick_handling.physical_devices() or gremlin.joystick_handling.joystick_devices()
            for dev in devices or []:
                if getattr(dev, "is_virtual", False):
                    continue
                device_box.addItem(dev.name, dev)
            current = str(binding.get("device_guid") or "")
            for i in range(device_box.count()):
                dev = device_box.itemData(i)
                if dev and str(dev.device_guid).casefold() == current.casefold():
                    device_box.setCurrentIndex(i)
                    break

        def _device_changed():
            dev = device_box.currentData()
            if not dev:
                return
            payload = {"device_name": dev.name, "device_guid": str(dev.device_guid)}
            if source.currentText() == "vjoy":
                payload["vjoy_id"] = int(dev.vjoy_id)
            self._bind(item["id"], channel, rebuild=True, **payload)

        device_box.currentIndexChanged.connect(_device_changed)
        form.addRow("Device", device_box)

        listen = QtWidgets.QPushButton("Listen...")
        listen.setToolTip("Assign from the next matching physical or vJoy input")
        listen.clicked.connect(lambda _=False, it=item, ch=channel, kind=force_type: self._listen(it, ch, kind))
        form.addRow("", listen)

        input_kind = force_type or binding.get("input_type") or "axis"
        if not force_type:
            input_type = QtWidgets.QComboBox()
            types = ["axis", "button", "hat"]
            input_type.addItems(types)
            if input_kind not in types:
                input_kind = "axis"
            input_type.setCurrentText(input_kind)
            input_type.currentTextChanged.connect(lambda v, wid=item["id"], ch=channel: self._bind(wid, ch, rebuild=True, input_type=v))
            form.addRow("Input type", input_type)
        else:
            if binding.get("input_type") != force_type:
                binding["input_type"] = force_type
            input_kind = force_type

        device = device_box.currentData()
        id_box = QtWidgets.QComboBox()
        if allow_none:
            id_box.addItem("(none)", 0)
        choices = self._input_choices(device, input_kind)
        try:
            current_id = int(binding.get("input_id") or 0)
        except (TypeError, ValueError):
            current_id = 0
        if not allow_none and current_id <= 0:
            current_id = int(choices[0][0]) if choices else 1
        found = False
        for axis_id, label in choices:
            id_box.addItem(label, axis_id)
            if int(axis_id) == current_id:
                id_box.setCurrentIndex(id_box.count() - 1)
                found = True
        if not found:
            if allow_none and current_id <= 0:
                id_box.setCurrentIndex(0)
                found = True
            else:
                id_box.addItem(f"{input_kind.capitalize()} {current_id}", current_id)
                id_box.setCurrentIndex(id_box.count() - 1)
        id_box.currentIndexChanged.connect(
            lambda _i, wid=item["id"], ch=channel, box=id_box, kind=input_kind: self._bind(
                wid, ch, input_type=kind, input_id=int(box.currentData() if box.currentData() is not None else 0)
            )
        )
        form.addRow("Axis" if input_kind == "axis" else input_kind.capitalize(), id_box)

        if show_invert:
            inv = QtWidgets.QCheckBox()
            inv.setChecked(bool(binding.get("invert")))
            inv.toggled.connect(lambda v, wid=item["id"], ch=channel: self._bind(wid, ch, invert=v))
            form.addRow("Invert", inv)

        hint = QtWidgets.QLabel(self._channel_summary(binding, input_kind))
        hint.setWordWrap(True)
        form.addRow("Assigned", hint)
        self._finish_channel(form, item, channel, extra_hint, show_clear)

    def _finish_channel(self, form, item: dict, channel: str, extra_hint: str | None, show_clear: bool):
        if extra_hint:
            note = QtWidgets.QLabel(extra_hint)
            note.setWordWrap(True)
            form.addRow(note)
        if show_clear:
            clear = QtWidgets.QPushButton("Clear")
            clear.clicked.connect(
                lambda _=False, wid=item["id"], ch=channel: self._bind(
                    wid,
                    ch,
                    rebuild=True,
                    device_guid="",
                    device_name="",
                    vjoy_id=0,
                    input_id=0,
                    state_name="",
                )
            )
            form.addRow("", clear)

    def _input_choices(self, device, input_kind: str) -> list[tuple[int, str]]:
        if input_kind == "axis":
            choices = []
            maps = getattr(device, "axismap_list", None) or [] if device else []
            for am in maps:
                axis_id = getattr(am, "axis_index", 0)
                if not axis_id:
                    continue
                try:
                    axis_name = gremlin.joystick_handling.get_axis_name(axis_id)
                except Exception:
                    axis_name = str(axis_id)
                try:
                    device_name = device.get_axis_name(axis_id) if device else None
                except Exception:
                    device_name = None
                label = f"Axis {axis_id} ({axis_name})"
                if device_name and str(device_name) not in label:
                    label = f"{label} — {device_name}"
                choices.append((int(axis_id), label))
            if choices:
                return choices
            count = int(getattr(device, "axis_count", 0) or 0) if device else 8
            for i in range(1, max(1, count) + 1):
                try:
                    axis_name = gremlin.joystick_handling.get_axis_name(i)
                except Exception:
                    axis_name = str(i)
                choices.append((i, f"Axis {i} ({axis_name})"))
            return choices or [(1, "Axis 1 (X)"), (2, "Axis 2 (Y)")]
        if input_kind == "button":
            count = int(getattr(device, "button_count", 0) or 0) if device else 16
            return [(i, f"Button {i}") for i in range(1, max(1, count) + 1)]
        count = int(getattr(device, "hat_count", 0) or 0) if device else 4
        return [(i, f"Hat {i}") for i in range(1, max(1, count) + 1)]

    def _channel_summary(self, binding: dict, input_kind: str) -> str:
        source = binding.get("source") or "physical"
        if source == "state":
            return binding.get("state_name") or "(none)"
        try:
            input_id = int(binding.get("input_id") or 0)
        except (TypeError, ValueError):
            input_id = 0
        if input_id <= 0:
            return "(none)"
        name = binding.get("device_name") or "—"
        return f"{name}  {input_kind.capitalize()} {input_id}"

    def _listen(self, item: dict, channel: str = "binding", force_type: str | None = None):
        types = [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat]
        widget_type = item.get("type")
        if force_type == "axis" or (widget_type and str(widget_type).startswith("axis")):
            types = [InputType.JoystickAxis]
        elif force_type == "button" or widget_type == "button":
            types = [InputType.JoystickButton]
        elif force_type == "hat" or widget_type == "hat":
            types = [InputType.JoystickHat]

        def _captured(event):
            input_type = "axis"
            if event.event_type == InputType.JoystickButton:
                input_type = "button"
            elif event.event_type == InputType.JoystickHat:
                input_type = "hat"
            device = gremlin.joystick_handling.getDevice(event.device_guid, show_error=False)
            payload = {
                "source": "vjoy" if getattr(device, "is_virtual", False) else "physical",
                "device_guid": str(event.device_guid),
                "device_name": device.name if device else str(event.device_guid),
                "vjoy_id": int(getattr(device, "vjoy_id", 0) or 0),
                "input_type": input_type,
                "input_id": int(event.identifier),
            }
            self._bind(item["id"], channel, rebuild=True, **payload)

        listener = gremlin.ui.ui_common.InputListenerWidget(types, callback=_captured)
        listener.show()

    def _update(self, widget_id: str, **fields):
        if self._building:
            return
        ids = list(self._edit_ids or [widget_id])
        self.scene.apply_widget_updates(ids, **fields)

    def _style(self, widget_id: str, **fields):
        if self._building:
            return
        ids = list(self._edit_ids or [widget_id])
        self.scene.apply_widget_updates(ids, style=fields)

    def _bind(self, widget_id: str, channel: str = "binding", rebuild: bool = False, **fields):
        if self._building:
            return
        if (fields.get("source") or "").casefold() == "vjoy" and not int(fields.get("vjoy_id") or 0):
            devices = gremlin.joystick_handling.vjoy_devices(connected_only=False) or []
            if devices:
                fields["vjoy_id"] = int(devices[0].vjoy_id)
                fields.setdefault("device_guid", str(devices[0].device_guid))
                fields.setdefault("device_name", devices[0].name)
        if widget_id == CANVAS_TOGGLE_ID:
            binding = normalize_toggle_binding(self.scene.canvas.get("toggle_binding"))
            binding.update(fields)
            self.scene.canvas["toggle_binding"] = normalize_toggle_binding(binding)
            self.scene._dirty = True
            self.scene.changed.emit()
            if rebuild:
                self.rebuild()
            return
        self.scene.apply_widget_update(widget_id, **{channel: fields})
        if rebuild:
            self.rebuild()
