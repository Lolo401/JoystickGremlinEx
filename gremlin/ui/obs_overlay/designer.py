# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

import gremlin.event_handler
import gremlin.ui.ui_common
from gremlin.ui.ui_common import Color

from .inspector import OverlayInspector
from .model import DEFAULT_SIZES, PALETTE_GROUPS, OverlayScene, profile_display_name
from .overlay_window import OverlayView
from .shapes import (
    _abs_point,
    _handle_point,
    closest_segment,
    ensure_shape_points,
    insert_shape_point,
    normalize_shape_kind,
    remove_shape_point,
    scene_to_normalized,
    uses_editable_points,
)
from .templates import (
    TEMPLATES,
    delete_user_template,
    list_user_templates,
    save_user_template,
    update_user_template,
)


WIDGET_TITLES = {
    "axis_bar": "Bar",
    "axis_radio": "Radio",
    "axis_fader": "Fader",
    "axis_radial": "Radial",
    "axis_encoder": "Encoder",
    "axis_stick_square": "X/Y",
    "axis_crosshair": "Radar",
    "axis_stick_circle": "Circular",
    "button": "Button",
    "hat": "Hat",
    "label": "Label",
    "shape": "Shape",
    "image": "Image",
}


class TemplateButton(QtWidgets.QPushButton):
    """Built-in or saved template. Saved templates can be updated or deleted from a right-click menu."""

    apply_requested = QtCore.Signal()
    update_requested = QtCore.Signal()
    delete_requested = QtCore.Signal()

    def __init__(self, label: str, editable: bool = False, parent=None):
        super().__init__(label, parent)
        self._editable = editable
        self.clicked.connect(lambda _=False: self.apply_requested.emit())
        if editable:
            self.setToolTip("Click to apply. Right-click to update with the current widgets or delete.")
            self.setContextMenuPolicy(QtCore.Qt.DefaultContextMenu)
        else:
            self.setToolTip("Click to add this template to the canvas.")
            self.setContextMenuPolicy(QtCore.Qt.NoContextMenu)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        if not self._editable:
            return
        menu = QtWidgets.QMenu(self)
        update_action = menu.addAction("Update with current widgets")
        update_action.triggered.connect(lambda _=False: self.update_requested.emit())
        delete_action = menu.addAction("Delete template")
        delete_action.triggered.connect(lambda _=False: self.delete_requested.emit())
        menu.exec(event.globalPos())


class DesignerCanvas(OverlayView):
    """Interactive canvas: select, move, resize, rubber-band."""

    def __init__(self, scene: OverlayScene, parent=None):
        super().__init__(scene, interactive=True, parent=parent)
        self._mode = None
        self._handle = -1
        self._guide_id = None
        self._last = QtCore.QPointF()
        self._origin = QtCore.QPointF()
        self._start_geom = {}
        self._shape_vertex = None
        self._shape_handle = None
        self.setAcceptDrops(False)
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.setContextMenuPolicy(QtCore.Qt.DefaultContextMenu)
        self.scene.selection_changed.connect(self._clear_shape_vertex)

    def _clear_shape_vertex(self):
        if self._mode == "shape":
            return
        self._shape_vertex = None
        self._shape_handle = None

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() != QtCore.Qt.LeftButton:
            return
        self.setFocus()
        pos = self.map_to_scene(event.position())
        vertex = self.shape_handle_at(pos)
        if vertex is not None:
            self.scene.push_undo()
            self._mode = "shape"
            self._shape_vertex, self._shape_handle = vertex
            self.update()
            return
        widget_id, handle = self.handle_at(pos)
        if handle >= 0:
            self.scene.push_undo()
            self._mode = "resize"
            self._handle = handle
            self._last = pos
            item = self.scene.widget_by_id(widget_id)
            self._start_geom = dict(item) if item else {}
            return
        hit = self.scene.hit_test(pos.x(), pos.y())
        if hit:
            additive = bool(event.modifiers() & QtCore.Qt.ShiftModifier)
            group_ids = self.scene.expand_group_ids([hit["id"]])
            if additive:
                self.scene.set_selection(group_ids, additive=True)
                self.scene.set_selection(self.scene.expand_group_ids(self.scene.selected_ids))
            elif hit["id"] not in self.scene.selected_ids:
                self.scene.set_selection(group_ids)
            self.scene.push_undo()
            self._mode = "move"
            self._last = pos
            self.setCursor(QtCore.Qt.SizeAllCursor)
            return
        guide = self.guide_at(pos)
        if guide:
            self.scene.push_undo()
            self._mode = "guide"
            self._guide_id = guide.get("id")
            self.setCursor(QtCore.Qt.SizeVerCursor if guide.get("axis") == "h" else QtCore.Qt.SizeHorCursor)
            return
        if not (event.modifiers() & QtCore.Qt.ShiftModifier):
            self.scene.set_selection([])
        self._mode = "rubber"
        self._origin = pos
        self._rubber = QtCore.QRectF(pos, pos)
        self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        pos = self.map_to_scene(event.position())
        if self._mode == "move":
            dx = pos.x() - self._last.x()
            dy = pos.y() - self._last.y()
            self.scene.move_selected(int(dx), int(dy), snap=True)
            self._last = pos
        elif self._mode == "shape":
            self._drag_shape_handle(pos, event.modifiers())
        elif self._mode == "resize":
            self._resize_to(pos)
        elif self._mode == "guide":
            self._drag_guide(pos)
        elif self._mode == "rubber":
            self._rubber = QtCore.QRectF(self._origin, pos)
            self.update()
        else:
            _, handle = self.handle_at(pos)
            if handle >= 0:
                self.setCursor(self._resize_cursor(handle))
                return
            guide = self.guide_at(pos)
            if guide:
                self.setCursor(QtCore.Qt.SizeVerCursor if guide.get("axis") == "h" else QtCore.Qt.SizeHorCursor)
            else:
                self.setCursor(QtCore.Qt.ArrowCursor)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if self._mode == "rubber":
            ids = self.scene.widgets_in_rect(
                self._rubber.x(), self._rubber.y(), self._rubber.width(), self._rubber.height()
            )
            ids = self.scene.expand_group_ids(ids)
            self.scene.set_selection(ids, additive=bool(event.modifiers() & QtCore.Qt.ShiftModifier))
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                self.scene.set_selection(self.scene.expand_group_ids(self.scene.selected_ids))
            self._rubber = QtCore.QRectF()
        self._mode = None
        self._handle = -1
        self._guide_id = None
        self._shape_handle = None
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.update()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        key = event.key()
        mods = event.modifiers()
        step = 8 if self.scene.canvas.get("snap_to_grid") else 1
        if mods & QtCore.Qt.ShiftModifier:
            step *= 4
        if key == QtCore.Qt.Key_Delete:
            if self._delete_shape_vertex():
                return
            self.scene.remove_selected()
        elif key == QtCore.Qt.Key_D and mods & QtCore.Qt.ControlModifier:
            self.scene.duplicate_selected()
        elif key == QtCore.Qt.Key_G and mods & QtCore.Qt.ControlModifier:
            if mods & QtCore.Qt.ShiftModifier:
                self.scene.ungroup_selected()
            else:
                self.scene.group_selected()
        elif key == QtCore.Qt.Key_A and mods & QtCore.Qt.ControlModifier:
            self.scene.set_selection([w["id"] for w in self.scene.widgets])
        elif key == QtCore.Qt.Key_Z and mods & QtCore.Qt.ControlModifier:
            if mods & QtCore.Qt.ShiftModifier:
                self.scene.redo()
            else:
                self.scene.undo()
        elif key == QtCore.Qt.Key_Y and mods & QtCore.Qt.ControlModifier:
            self.scene.redo()
        elif key == QtCore.Qt.Key_Left:
            self.scene.push_undo()
            self.scene.move_selected(-step, 0)
        elif key == QtCore.Qt.Key_Right:
            self.scene.push_undo()
            self.scene.move_selected(step, 0)
        elif key == QtCore.Qt.Key_Up:
            self.scene.push_undo()
            self.scene.move_selected(0, -step)
        elif key == QtCore.Qt.Key_Down:
            self.scene.push_undo()
            self.scene.move_selected(0, step)
        elif key == QtCore.Qt.Key_0 and mods & QtCore.Qt.ControlModifier:
            self._zoom_at(1.0)
        elif (key in (QtCore.Qt.Key_Plus, QtCore.Qt.Key_Equal)) and mods & QtCore.Qt.ControlModifier:
            self._zoom_at(self.zoom * 1.1)
        elif key == QtCore.Qt.Key_Minus and mods & QtCore.Qt.ControlModifier:
            self._zoom_at(self.zoom / 1.1)
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        pos = self.map_to_scene(event.pos())
        hit = self.scene.hit_test(pos.x(), pos.y())
        if hit and hit["id"] not in self.scene.selected_ids:
            self.scene.set_selection(self.scene.expand_group_ids([hit["id"]]))
        if not self.scene.selected_ids:
            return
        grouped = any(str(item.get("group") or "").strip() for item in self.scene.selected_widgets())
        menu = QtWidgets.QMenu(self)
        duplicate = menu.addAction("Duplicate")
        delete = menu.addAction("Delete")
        menu.addSeparator()
        forward = menu.addAction("Bring forward")
        backward = menu.addAction("Send backward")
        menu.addSeparator()
        group = menu.addAction("Group")
        group.setEnabled(len(self.scene.selected_ids) >= 2)
        ungroup = menu.addAction("Ungroup")
        ungroup.setEnabled(grouped)
        add_point = None
        delete_point = None
        item = self.scene.primary_selection()
        if uses_editable_points(item):
            menu.addSeparator()
            add_point = menu.addAction("Add point")
            delete_point = menu.addAction("Delete point")
            delete_point.setEnabled(self._shape_vertex is not None)
        chosen = menu.exec(event.globalPos())
        if chosen is duplicate:
            self.scene.duplicate_selected()
        elif chosen is delete:
            self.scene.remove_selected()
        elif chosen is forward:
            self.scene.bring_forward()
        elif chosen is backward:
            self.scene.send_backward()
        elif chosen is group:
            self.scene.group_selected()
        elif chosen is ungroup:
            self.scene.ungroup_selected()
        elif chosen is add_point:
            pos = self.map_to_scene(event.pos())
            self.scene.push_undo()
            index, _dist = closest_segment(item, pos)
            self._shape_vertex = insert_shape_point(item, index, pos)
            self.scene._dirty = True
            self.scene.changed.emit()
        elif chosen is delete_point:
            self._delete_shape_vertex()

    def wheelEvent(self, event: QtGui.QWheelEvent):
        if event.modifiers() & QtCore.Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                factor = 1.1 if delta > 0 else 1.0 / 1.1
                self._zoom_at(self.zoom * factor, event.position())
                event.accept()
                return
        event.ignore()

    def _zoom_at(self, zoom: float, widget_pos: QtCore.QPointF | None = None):
        scroll = self.parent()
        while scroll is not None and not isinstance(scroll, QtWidgets.QScrollArea):
            scroll = scroll.parent()
        old_zoom = self.zoom
        if widget_pos is None:
            self.set_zoom(zoom)
            return
        scene_pos = QtCore.QPointF(widget_pos.x() / max(old_zoom, 0.01), widget_pos.y() / max(old_zoom, 0.01))
        viewport_pos = None
        if scroll is not None:
            viewport_pos = self.mapTo(scroll.viewport(), widget_pos.toPoint())
        self.set_zoom(zoom)
        if scroll is None or viewport_pos is None:
            return
        new_widget = QtCore.QPoint(int(scene_pos.x() * self.zoom), int(scene_pos.y() * self.zoom))
        scroll.horizontalScrollBar().setValue(new_widget.x() - viewport_pos.x())
        scroll.verticalScrollBar().setValue(new_widget.y() - viewport_pos.y())

    def _resize_cursor(self, handle: int):
        mapping = {
            0: QtCore.Qt.SizeFDiagCursor,
            1: QtCore.Qt.SizeVerCursor,
            2: QtCore.Qt.SizeBDiagCursor,
            3: QtCore.Qt.SizeHorCursor,
            4: QtCore.Qt.SizeFDiagCursor,
            5: QtCore.Qt.SizeVerCursor,
            6: QtCore.Qt.SizeBDiagCursor,
            7: QtCore.Qt.SizeHorCursor,
        }
        return mapping.get(handle, QtCore.Qt.ArrowCursor)

    def _resize_to(self, pos: QtCore.QPointF):
        item = self.scene.primary_selection()
        if not item or not self._start_geom:
            return
        x0 = float(self._start_geom["x"])
        y0 = float(self._start_geom["y"])
        w0 = float(self._start_geom["w"])
        h0 = float(self._start_geom["h"])
        x1, y1 = x0 + w0, y0 + h0
        px, py = pos.x(), pos.y()
        handle = self._handle
        if handle in (0, 6, 7):
            x0 = px
        if handle in (2, 3, 4):
            x1 = px
        if handle in (0, 1, 2):
            y0 = py
        if handle in (4, 5, 6):
            y1 = py
        x, y = min(x0, x1), min(y0, y1)
        w, h = max(8, abs(x1 - x0)), max(8, abs(y1 - y0))
        item["x"] = self.scene.snap_value(x)
        item["y"] = self.scene.snap_value(y)
        item["w"] = max(8, self.scene.snap_value(w))
        item["h"] = max(8, self.scene.snap_value(h))
        handle = self._handle
        x_edges = ()
        y_edges = ()
        if handle in (0, 6, 7):
            x_edges = ("left",)
        elif handle in (2, 3, 4):
            x_edges = ("right",)
        if handle in (0, 1, 2):
            y_edges = ("top",)
        elif handle in (4, 5, 6):
            y_edges = ("bottom",)
        gx, gy, gw, gh = self.scene.snap_geom_to_guides(
            float(item["x"]),
            float(item["y"]),
            float(item["w"]),
            float(item["h"]),
            x_edges=x_edges,
            y_edges=y_edges,
            mode="resize",
        )
        item["x"] = int(round(gx))
        item["y"] = int(round(gy))
        item["w"] = max(8, int(round(gw)))
        item["h"] = max(8, int(round(gh)))
        self.scene._dirty = True
        self.scene.changed.emit()

    def _drag_guide(self, pos: QtCore.QPointF):
        guide = self.scene.guide_by_id(self._guide_id) if self._guide_id else None
        if not guide:
            return
        cw, ch = self.canvas_size()
        if guide.get("axis") == "h":
            value = 0.0 if ch <= 0 else pos.y() / ch
        else:
            value = 0.0 if cw <= 0 else pos.x() / cw
        self.scene.update_guide(guide["id"], position=max(0.0, min(1.0, value)))

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):
        if event.button() != QtCore.Qt.LeftButton:
            return
        pos = self.map_to_scene(event.position())
        item = self.scene.primary_selection()
        if not uses_editable_points(item):
            hit = self.scene.hit_test(pos.x(), pos.y())
            if hit:
                self.scene.set_selection(self.scene.expand_group_ids([hit["id"]]))
                item = hit
        if not uses_editable_points(item):
            return
        self.scene.push_undo()
        index, _dist = closest_segment(item, pos)
        self._shape_vertex = insert_shape_point(item, index, pos)
        self._shape_handle = "point"
        self.scene._dirty = True
        self.scene.changed.emit()

    def _bezier_handle_indices(self, item: dict, points: list) -> list[int]:
        kind = normalize_shape_kind((item.get("style") or {}).get("shape_kind"))
        if kind == "freeform":
            return list(range(len(points)))
        if self._shape_vertex is not None and 0 <= self._shape_vertex < len(points):
            return [self._shape_vertex]
        return []

    def shape_handle_at(self, pos: QtCore.QPointF):
        item = self.scene.primary_selection()
        if not uses_editable_points(item):
            return None
        points = ensure_shape_points(item)
        tol = 7.0 / max(self._zoom, 0.25)
        for index in self._bezier_handle_indices(item, points):
            point = points[index]
            for kind in ("in", "out"):
                handle = _handle_point(item, point, kind)
                if abs(pos.x() - handle.x()) <= tol and abs(pos.y() - handle.y()) <= tol:
                    return index, kind
        for index, point in enumerate(points):
            origin = _abs_point(item, point)
            if abs(pos.x() - origin.x()) <= tol and abs(pos.y() - origin.y()) <= tol:
                return index, "point"
        return None

    def _drag_shape_handle(self, pos: QtCore.QPointF, modifiers):
        item = self.scene.primary_selection()
        if not uses_editable_points(item) or self._shape_vertex is None:
            return
        points = ensure_shape_points(item)
        if self._shape_vertex < 0 or self._shape_vertex >= len(points):
            return
        point = points[self._shape_vertex]
        if self._shape_handle == "point":
            nx, ny = scene_to_normalized(item, pos)
            point["x"] = nx
            point["y"] = ny
        else:
            origin = _abs_point(item, point)
            width = max(1.0, float(item["w"]))
            height = max(1.0, float(item["h"]))
            dx = (pos.x() - origin.x()) / width
            dy = (pos.y() - origin.y()) / height
            kind = self._shape_handle or "out"
            point[f"{kind}_x"] = dx
            point[f"{kind}_y"] = dy
            if not (modifiers & QtCore.Qt.AltModifier):
                other = "in" if kind == "out" else "out"
                point[f"{other}_x"] = -dx
                point[f"{other}_y"] = -dy
        item["points"] = points
        self.scene._dirty = True
        self.scene.changed.emit()

    def _delete_shape_vertex(self) -> bool:
        item = self.scene.primary_selection()
        if not uses_editable_points(item) or self._shape_vertex is None:
            return False
        self.scene.push_undo()
        if not remove_shape_point(item, self._shape_vertex):
            return False
        self._shape_vertex = None
        self._shape_handle = None
        self.scene._dirty = True
        self.scene.changed.emit()
        return True

    def _paint_selection(self, painter: QtGui.QPainter):
        super()._paint_selection(painter)
        item = self.scene.primary_selection()
        if not uses_editable_points(item):
            return
        points = ensure_shape_points(item)
        hs = 4.0 / max(self._zoom, 0.25)
        painter.save()
        for index, point in enumerate(points):
            origin = _abs_point(item, point)
            selected = index == self._shape_vertex
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffe27a" if selected else "#7ec8ff"), 1.2))
            painter.setBrush(QtGui.QColor("#ffe27a" if selected else "#7ec8ff"))
            painter.drawEllipse(origin, hs, hs)
        for index in self._bezier_handle_indices(item, points):
            point = points[index]
            origin = _abs_point(item, point)
            selected = index == self._shape_vertex
            color = QtGui.QColor("#ffe27a" if selected else "#d4b84a")
            painter.setPen(QtGui.QPen(color, 1.0, QtCore.Qt.DashLine))
            for kind in ("in", "out"):
                handle = _handle_point(item, point, kind)
                painter.drawLine(origin, handle)
                painter.setBrush(color)
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(handle, hs * 0.85, hs * 0.85)
                painter.setPen(QtGui.QPen(color, 1.0, QtCore.Qt.DashLine))
        painter.restore()


class OverlayDesignerWidget(QtWidgets.QWidget):
    """Overlay layout editor hosted on the Overlay device tab."""

    def __init__(self, scene: OverlayScene, overlay_manager=None, overlay_callback=None, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._overlay_manager = overlay_manager
        self._overlay_callback = overlay_callback
        self.setMinimumSize(640, 480)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self._title = QtWidgets.QLabel()
        self._title.setStyleSheet("font-weight: bold;")
        root.addWidget(self._title)
        self.refresh_profile_title()
        root.addWidget(self._toolbar())

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self._palette())
        self.canvas = DesignerCanvas(scene)
        scroll = QtWidgets.QScrollArea()
        self._canvas_scroll = scroll
        scroll.setWidgetResizable(False)
        scroll.setAlignment(QtCore.Qt.AlignCenter)
        scroll.setWidget(self.canvas)
        bg = Color.actionBackgroundColor()
        scroll.setStyleSheet(f"QScrollArea {{ background: {bg}; border: none; }}")
        scroll.viewport().setAutoFillBackground(True)
        scroll.viewport().setStyleSheet(f"background: {bg};")
        splitter.addWidget(scroll)
        inspector = OverlayInspector(scene)
        inspector.setMinimumWidth(300)
        inspector.setMaximumWidth(420)
        splitter.addWidget(inspector)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([220, 760, 320])
        root.addWidget(splitter, 1)
        self.canvas.zoom_changed.connect(self._on_canvas_zoom)

        hint = QtWidgets.QLabel(
            "Drag widgets on the canvas. Shift+click multi-select. Right-click for duplicate, delete, layer, and group. "
            "Delete removes. Ctrl+D duplicates. Ctrl+G groups / Ctrl+Shift+G ungroups. Arrow keys nudge. Ctrl+wheel zooms. "
            "With a widget selected, a palette click changes its type and keeps compatible settings. "
            "Shape widgets can be rectangles, circles, triangles, diamonds, lines, or a freeform path. "
            "Chroma/image: capture the GEX Overlay window in OBS. On-screen: the HUD covers the chosen monitor."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{Color.normalColor()};")
        root.addWidget(hint)

        try:
            el = gremlin.event_handler.EventListener()
            el.profile_loaded.connect(self.refresh_profile_title)
            el.profile_unloaded.connect(self.refresh_profile_title)
        except Exception:
            pass

    @property
    def inputCount(self) -> int:
        return 0

    @property
    def inputWidgetCount(self) -> int:
        return 0

    def isLoaded(self) -> bool:
        return True

    def ensureLoaded(self):
        if self._overlay_manager is not None:
            self._overlay_manager._ensure_current_profile_scene()
        self.refresh_profile_title()

    def refresh(self, emit=True, force=False, **kwargs):
        self.refresh_profile_title()

    def refresh_ui(self):
        self.refresh_profile_title()

    def _on_zoom_slider(self, value: int):
        if hasattr(self, "canvas"):
            self.canvas.set_zoom(value / 100.0)
        if hasattr(self, "_zoom_value"):
            self._zoom_value.setText(f"{int(value)}%")

    def _set_zoom_percent(self, percent: int):
        if hasattr(self, "_zoom_slider"):
            self._zoom_slider.setValue(int(percent))
        else:
            self._on_zoom_slider(int(percent))

    def _on_canvas_zoom(self, zoom: float):
        percent = int(round(float(zoom) * 100))
        if hasattr(self, "_zoom_slider"):
            with QtCore.QSignalBlocker(self._zoom_slider):
                self._zoom_slider.setValue(percent)
        if hasattr(self, "_zoom_value"):
            self._zoom_value.setText(f"{percent}%")

    def _toolbar(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        self._overlay_button = QtWidgets.QPushButton("Show overlay")
        self._overlay_button.setToolTip("Show or hide the overlay window (OBS capture or on-screen HUD)")
        self._overlay_button.clicked.connect(lambda _=False: self._toggle_overlay())
        save = QtWidgets.QPushButton("Save layout")
        save.setToolTip("Store this overlay with the current GEX profile")
        save.clicked.connect(self._save)
        load = QtWidgets.QPushButton("Load layout...")
        load.clicked.connect(self._load)
        undo = QtWidgets.QPushButton("Undo")
        undo.clicked.connect(self.scene.undo)
        redo = QtWidgets.QPushButton("Redo")
        redo.clicked.connect(self.scene.redo)
        save_template = QtWidgets.QPushButton("Save template")
        save_template.setToolTip("Save the current widgets as a global template (not profile-specific)")
        save_template.clicked.connect(lambda _=False: self._save_template())
        for widget in (self._overlay_button, save, load, undo, redo, save_template):
            layout.addWidget(widget)
        layout.addStretch()
        zoom_label = QtWidgets.QLabel("Zoom")
        self._zoom_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._zoom_slider.setRange(25, 400)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(140)
        self._zoom_slider.setToolTip("Scale the designer canvas. Does not change the overlay resolution. Ctrl+wheel, Ctrl+0 reset.")
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        self._zoom_value = QtWidgets.QLabel("100%")
        self._zoom_value.setMinimumWidth(44)
        reset_zoom = QtWidgets.QPushButton("100%")
        reset_zoom.setFixedWidth(48)
        reset_zoom.setToolTip("Reset designer zoom to 100%")
        reset_zoom.clicked.connect(lambda _=False: self._set_zoom_percent(100))
        layout.addWidget(zoom_label)
        layout.addWidget(self._zoom_slider)
        layout.addWidget(self._zoom_value)
        layout.addWidget(reset_zoom)
        self._refresh_overlay_button()
        return bar

    def _palette(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setMinimumWidth(220)
        panel.setMaximumWidth(280)
        layout = QtWidgets.QVBoxLayout(panel)
        for title, types in PALETTE_GROUPS:
            layout.addWidget(QtWidgets.QLabel(title))
            for widget_type in types:
                btn = QtWidgets.QPushButton(WIDGET_TITLES.get(widget_type, widget_type))
                btn.setToolTip(
                    f"Add a {WIDGET_TITLES.get(widget_type, widget_type)}. "
                    "If a widget is selected, change it to this type and keep compatible settings."
                )
                btn.clicked.connect(lambda _=False, t=widget_type: self._add_widget(t))
                layout.addWidget(btn)
        layout.addSpacing(12)
        layout.addWidget(QtWidgets.QLabel("Templates"))
        for name, tip, factory in TEMPLATES:
            btn = TemplateButton(name, editable=False)
            btn.setToolTip(tip)
            btn.apply_requested.connect(lambda fn=factory, title=name: self._apply_template(title, fn))
            layout.addWidget(btn)
        layout.addWidget(QtWidgets.QLabel("Saved templates"))
        self._user_templates_host = QtWidgets.QWidget()
        self._user_templates_layout = QtWidgets.QVBoxLayout(self._user_templates_host)
        self._user_templates_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._user_templates_host)
        self._refresh_user_templates()
        layout.addStretch()
        bg = Color.actionBackgroundColor()
        panel.setStyleSheet(f"QWidget {{ background: {bg}; }}")
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(220)
        scroll.setMaximumWidth(280)
        return scroll

    def _add_widget(self, widget_type: str):
        if self.scene.convert_selected(widget_type):
            self.canvas.setFocus()
            return
        size = DEFAULT_SIZES.get(widget_type, (80, 80))
        x, y = self._viewport_add_origin(int(size[0]), int(size[1]))
        self.scene.add_widget(widget_type, x, y)
        self.canvas.setFocus()

    def _viewport_add_origin(self, width: int, height: int) -> tuple[int, int]:
        scroll = getattr(self, "_canvas_scroll", None)
        canvas_w = max(1, int(self.scene.canvas.get("width") or 1280))
        canvas_h = max(1, int(self.scene.canvas.get("height") or 720))
        if scroll is not None:
            viewport = scroll.viewport()
            center = self.canvas.mapFrom(viewport, viewport.rect().center())
            scene = self.canvas.map_to_scene(QtCore.QPointF(center))
            x = int(scene.x() - width / 2)
            y = int(scene.y() - height / 2)
        else:
            x = int(canvas_w / 2 - width / 2)
            y = int(canvas_h / 2 - height / 2)
        return max(0, min(canvas_w - width, x)), max(0, min(canvas_h - height, y))

    def _apply_template(self, title: str, factory):
        items = factory()
        if not items:
            if title.lower().startswith("blank"):
                self.scene.push_undo()
                self.scene.widgets = []
                self.scene.selected_ids = []
                self.scene._dirty = True
                self.scene.changed.emit()
                self.scene.selection_changed.emit()
            return
        self.scene.add_widgets(items)

    def _refresh_user_templates(self):
        layout = getattr(self, "_user_templates_layout", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        entries = list_user_templates()
        if not entries:
            hint = QtWidgets.QLabel("None yet — use Save template.")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            return
        for name, tip, factory, filename in entries:
            btn = TemplateButton(name, editable=True)
            btn.setToolTip(f"{tip}. Click to apply. Right-click to update with the current widgets or delete.")
            btn.apply_requested.connect(lambda fn=factory, title=name: self._apply_template(title, fn))
            btn.update_requested.connect(lambda fname=filename, title=name: self._update_template(fname, title))
            btn.delete_requested.connect(lambda fname=filename, title=name: self._delete_template(fname, title))
            layout.addWidget(btn)

    def _update_template(self, filename: str, title: str):
        if not self.scene.widgets:
            QtWidgets.QMessageBox.information(self, "OBS Overlay", "Add widgets before updating a template.")
            return
        try:
            update_user_template(filename, self.scene.widgets)
        except Exception as err:
            QtWidgets.QMessageBox.warning(self, "OBS Overlay", f"Could not update template:\n{err}")
            return
        self._refresh_user_templates()
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Updated {title}", self)

    def _delete_template(self, filename: str, title: str):
        try:
            delete_user_template(filename)
        except Exception as err:
            QtWidgets.QMessageBox.warning(self, "OBS Overlay", f"Could not delete template:\n{err}")
            return
        self._refresh_user_templates()
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Deleted {title}", self)

    def _save_template(self):
        if not self.scene.widgets:
            QtWidgets.QMessageBox.information(self, "OBS Overlay", "Add widgets before saving a template.")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save template", "Template name:")
        if not ok or not str(name).strip():
            return
        try:
            path = save_user_template(str(name).strip(), self.scene.widgets)
        except Exception as err:
            QtWidgets.QMessageBox.warning(self, "OBS Overlay", f"Could not save template:\n{err}")
            return
        self._refresh_user_templates()
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Saved {path}", self)

    def _toggle_overlay(self):
        manager = self._overlay_manager
        if manager is not None:
            if manager.overlay_is_visible():
                manager.hide_overlay()
            else:
                manager.show_overlay()
            self._refresh_overlay_button()
            return
        if callable(self._overlay_callback):
            self._overlay_callback()
        self._refresh_overlay_button()

    def _refresh_overlay_button(self):
        button = getattr(self, "_overlay_button", None)
        if button is None:
            return
        visible = bool(self._overlay_manager and self._overlay_manager.overlay_is_visible())
        button.setText("Hide overlay" if visible else "Show overlay")

    def refresh_profile_title(self):
        self._title.setText(f"Overlay — {profile_display_name()}")
        self._refresh_overlay_button()

    def _save(self):
        if self.scene.save():
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Saved overlay for {profile_display_name()}", self)
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "OBS Overlay",
                "Save the GEX profile first so this overlay can be stored with it.",
            )

    def _load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import overlay layout", "", "Overlay JSON (*.overlay.json *.json)")
        if path:
            self.scene.load(path)
            self.refresh_profile_title()

    def showEvent(self, event):
        self.canvas.attach_bus()
        self._refresh_overlay_button()
        super().showEvent(event)

    def hideEvent(self, event):
        self.canvas.detach_bus()
        if self.scene.dirty:
            self.scene.save()
        super().hideEvent(event)


OverlayDesignerDialog = OverlayDesignerWidget
