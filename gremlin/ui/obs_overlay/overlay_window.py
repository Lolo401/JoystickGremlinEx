# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging
import sys

import math

from PySide6 import QtCore, QtGui, QtWidgets

from .bindings import OverlayValueBus
from .model import DEFAULT_GUIDE_COLOR, OVERLAY_WINDOW_TITLE, OverlayScene, is_onscreen_mode, normalize_background_mode
from .widgets import paint_background, paint_widget, qcolor, widget_dirty_rect

syslog = logging.getLogger("system")

DESIGNER_OVERFLOW_PAD = 48
DESIGNER_OVERFLOW_FILL = QtGui.QColor("#151a22")
DESIGNER_CANVAS_BORDER = QtGui.QColor("#7ec8ff")


def list_overlay_screens() -> list[dict]:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return []
    primary = app.primaryScreen()
    screens = []
    for index, screen in enumerate(app.screens()):
        geo = screen.geometry()
        name = screen.name() or f"Display {index + 1}"
        tag = " (primary)" if screen is primary else ""
        screens.append(
            {
                "index": index,
                "name": name,
                "width": int(geo.width()),
                "height": int(geo.height()),
                "x": int(geo.x()),
                "y": int(geo.y()),
                "label": f"{index + 1}: {name} — {geo.width()}×{geo.height()}{tag}",
            }
        )
    return screens


def resolve_overlay_screen(canvas: dict | None) -> dict | None:
    screens = list_overlay_screens()
    if not screens:
        return None
    canvas = canvas or {}
    name = str(canvas.get("monitor_name") or "").strip()
    if name:
        for screen in screens:
            if screen["name"] == name:
                return screen
    try:
        index = int(canvas.get("monitor_index") or 0)
    except (TypeError, ValueError):
        index = 0
    if 0 <= index < len(screens):
        return screens[index]
    return screens[0]


def apply_onscreen_geometry(scene: OverlayScene, monitor_index=None, emit: bool = True) -> bool:
    """Size the canvas to the chosen monitor when on-screen mode is active."""
    if not is_onscreen_mode(scene.canvas):
        return False
    if monitor_index is not None:
        scene.canvas["monitor_index"] = int(monitor_index)
        scene.canvas["monitor_name"] = ""
    info = resolve_overlay_screen(scene.canvas)
    if not info:
        return False
    changed = False
    for key in ("width", "height", "monitor_index", "monitor_name"):
        value = info["index"] if key == "monitor_index" else info["name"] if key == "monitor_name" else info[key]
        if scene.canvas.get(key) != value:
            scene.canvas[key] = value
            changed = True
    if changed:
        scene._dirty = True
        if emit:
            scene.changed.emit()
    return changed


class OverlayView(QtWidgets.QWidget):
    """Paints an overlay scene at 1:1 canvas size (designer may zoom)."""

    zoom_changed = QtCore.Signal(float)

    def __init__(self, scene: OverlayScene, interactive: bool = False, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.interactive = interactive
        self.bus = OverlayValueBus()
        self._zoom = 1.0
        self._scene_origin = QtCore.QPoint(0, 0)
        self._rubber = QtCore.QRectF()
        self._grid_pm: QtGui.QPixmap | None = None
        self.setMouseTracking(interactive)
        self.setFocusPolicy(QtCore.Qt.StrongFocus if interactive else QtCore.Qt.NoFocus)
        self._sync_paint_mode()
        self._apply_size()
        self.scene.changed.connect(self._on_scene_changed)
        self._bus_connected = False

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float):
        if not self.interactive:
            return
        zoom = max(0.25, min(4.0, float(zoom)))
        zoom = round(zoom * 100.0) / 100.0
        if abs(zoom - self._zoom) < 0.001:
            return
        self._zoom = zoom
        self._grid_pm = None
        self._apply_size()
        self.update()
        self.zoom_changed.emit(zoom)

    def canvas_size(self) -> tuple[int, int]:
        w = max(64, int(self.scene.canvas.get("width") or 1280))
        h = max(64, int(self.scene.canvas.get("height") or 720))
        return w, h

    def _content_rect(self) -> QtCore.QRect:
        """Scene rect that includes the canvas and, in the designer, overflow widgets."""
        cw, ch = self.canvas_size()
        canvas = QtCore.QRect(0, 0, cw, ch)
        if not self.interactive:
            return canvas
        bounds = QtCore.QRect(canvas)
        for item in self.scene.widgets:
            try:
                x = int(item.get("x") or 0)
                y = int(item.get("y") or 0)
                w = max(1, int(item.get("w") or 1))
                h = max(1, int(item.get("h") or 1))
            except (TypeError, ValueError):
                continue
            bounds = bounds.united(QtCore.QRect(x, y, w, h))
        if bounds == canvas:
            return canvas
        pad = DESIGNER_OVERFLOW_PAD
        return bounds.adjusted(-pad, -pad, pad, pad).united(canvas)

    def map_to_scene(self, pos: QtCore.QPointF) -> QtCore.QPointF:
        z = self._zoom or 1.0
        origin = self._scene_origin
        return QtCore.QPointF(pos.x() / z + origin.x(), pos.y() / z + origin.y())

    def _scene_clip(self, widget_rect: QtCore.QRect) -> QtCore.QRect:
        z = self._zoom or 1.0
        ox, oy = self._scene_origin.x(), self._scene_origin.y()
        if abs(z - 1.0) < 0.001:
            return widget_rect.translated(ox, oy)
        inv = 1.0 / z
        return QtCore.QRect(
            math.floor(widget_rect.x() * inv) + ox - 2,
            math.floor(widget_rect.y() * inv) + oy - 2,
            math.ceil(widget_rect.width() * inv) + 4,
            math.ceil(widget_rect.height() * inv) + 4,
        )

    def _widget_rect(self, scene_rect: QtCore.QRect) -> QtCore.QRect:
        z = self._zoom or 1.0
        ox, oy = self._scene_origin.x(), self._scene_origin.y()
        if abs(z - 1.0) < 0.001:
            return scene_rect.translated(-ox, -oy)
        return QtCore.QRect(
            math.floor((scene_rect.x() - ox) * z),
            math.floor((scene_rect.y() - oy) * z),
            max(1, math.ceil(scene_rect.width() * z) + 1),
            max(1, math.ceil(scene_rect.height() * z) + 1),
        )

    def attach_bus(self):
        self.bus.set_widgets(self.scene.widgets)
        self.bus.attach(self.scene.widgets)
        if not self._bus_connected:
            self.bus.values_changed.connect(self._on_values_changed)
            self._bus_connected = True

    def detach_bus(self):
        if self._bus_connected:
            try:
                self.bus.values_changed.disconnect(self._on_values_changed)
            except Exception:
                pass
            self._bus_connected = False
        self.bus.detach()

    def _on_values_changed(self, widget_ids=None):
        if not widget_ids:
            self.update()
            return
        united = QtCore.QRect()
        for widget_id in widget_ids:
            item = self.scene.widget_by_id(widget_id)
            if not item:
                continue
            rect = self._widget_rect(widget_dirty_rect(item))
            united = rect if united.isNull() else united.united(rect)
        if united.isNull():
            self.update()
        else:
            self.update(united)

    def _on_scene_changed(self):
        self.bus.set_widgets(self.scene.widgets)
        self._grid_pm = None
        self._sync_paint_mode()
        self._apply_size()
        self.update()

    def _sync_paint_mode(self):
        live_onscreen = is_onscreen_mode(self.scene.canvas) and not self.interactive
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, not live_onscreen)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, live_onscreen)

    def _apply_size(self):
        content = self._content_rect()
        old_origin = QtCore.QPoint(self._scene_origin)
        origin = content.topLeft()
        z = self._zoom if self.interactive else 1.0
        zw = max(64, int(round(content.width() * z)))
        zh = max(64, int(round(content.height() * z)))
        if self._scene_origin != origin or self.width() != zw or self.height() != zh:
            self._grid_pm = None
        self._scene_origin = origin
        if self.interactive and origin != old_origin:
            self._nudge_scroll((old_origin.x() - origin.x()) * z, (old_origin.y() - origin.y()) * z)
        self.setFixedSize(zw, zh)

    def _nudge_scroll(self, dx: float, dy: float):
        parent = self.parent()
        while parent is not None and not isinstance(parent, QtWidgets.QScrollArea):
            parent = parent.parent()
        if not isinstance(parent, QtWidgets.QScrollArea):
            return
        if abs(dx) >= 1:
            bar = parent.horizontalScrollBar()
            bar.setValue(bar.value() + int(round(dx)))
        if abs(dy) >= 1:
            bar = parent.verticalScrollBar()
            bar.setValue(bar.value() + int(round(dy)))

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        z = self._zoom if self.interactive else 1.0
        cw, ch = self.canvas_size()
        canvas_rect = QtCore.QRect(0, 0, cw, ch)
        clip = event.rect()
        scene_clip = self._scene_clip(clip)
        if self.interactive:
            scene_clip = scene_clip.intersected(self._content_rect())
        else:
            scene_clip = scene_clip.intersected(canvas_rect)
        if abs(z - 1.0) > 0.001:
            painter.scale(z, z)
        origin = self._scene_origin
        if origin.x() or origin.y():
            painter.translate(-origin.x(), -origin.y())
        painter.setClipRect(scene_clip)
        # Live updates skip antialiasing so the UI thread stays free for Input Viewer.
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        live_onscreen = is_onscreen_mode(self.scene.canvas) and not self.interactive
        if live_onscreen:
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
            painter.fillRect(scene_clip, QtCore.Qt.transparent)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        else:
            if self.interactive:
                painter.fillRect(scene_clip, DESIGNER_OVERFLOW_FILL)
            paint_background(painter, self.scene.canvas, canvas_rect, preview=self.interactive)
            if self.interactive:
                painter.setPen(QtGui.QPen(DESIGNER_CANVAS_BORDER, 1))
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawRect(canvas_rect.adjusted(0, 0, -1, -1))
        if self.interactive and self.scene.canvas.get("snap_to_grid"):
            self._paint_grid(painter)
        for item in self.scene.sorted_widgets():
            dirty = widget_dirty_rect(item)
            if not dirty.intersects(scene_clip):
                continue
            value = self.bus.value_for(item)
            paint_widget(painter, item, value)
        if self.interactive:
            self._paint_guides(painter)
            self._paint_selection(painter)
            if not self._rubber.isNull():
                painter.setPen(QtGui.QPen(QtGui.QColor("#7ec8ff"), 1, QtCore.Qt.DashLine))
                painter.setBrush(QtGui.QColor(126, 200, 255, 40))
                painter.drawRect(self._rubber.normalized())
        painter.end()

    def _paint_grid(self, painter: QtGui.QPainter):
        cw, ch = self.canvas_size()
        size = QtCore.QSize(cw, ch)
        if self._grid_pm is None or self._grid_pm.size() != size:
            grid = max(4, int(self.scene.canvas.get("grid_size") or 8))
            pm = QtGui.QPixmap(size)
            pm.fill(QtCore.Qt.transparent)
            gp = QtGui.QPainter(pm)
            gp.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 28), 1))
            for x in range(0, cw, grid):
                gp.drawLine(x, 0, x, ch)
            for y in range(0, ch, grid):
                gp.drawLine(0, y, cw, y)
            gp.end()
            self._grid_pm = pm
        painter.drawPixmap(0, 0, self._grid_pm)

    def _paint_guides(self, painter: QtGui.QPainter):
        cw, ch = self.canvas_size()
        handle = 8.0 / max(self._zoom, 0.25)
        for guide in self.scene.canvas.get("guides") or []:
            color = qcolor(guide.get("color"), DEFAULT_GUIDE_COLOR)
            painter.setPen(QtGui.QPen(color, 1.2, QtCore.Qt.DashLine))
            painter.setBrush(color)
            pos = max(0.0, min(1.0, float(guide.get("position") or 0)))
            if guide.get("axis") == "h":
                y = pos * ch
                painter.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(cw, y))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawPolygon(
                    QtGui.QPolygonF(
                        [
                            QtCore.QPointF(0, y - handle),
                            QtCore.QPointF(handle * 1.6, y),
                            QtCore.QPointF(0, y + handle),
                        ]
                    )
                )
            else:
                x = pos * cw
                painter.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, ch))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawPolygon(
                    QtGui.QPolygonF(
                        [
                            QtCore.QPointF(x - handle, 0),
                            QtCore.QPointF(x + handle, 0),
                            QtCore.QPointF(x, handle * 1.6),
                        ]
                    )
                )

    def guide_at(self, pos: QtCore.QPointF) -> dict | None:
        cw, ch = self.canvas_size()
        if cw <= 0 or ch <= 0:
            return None
        tol = 6.0 / max(self._zoom, 0.25)
        handle = 12.0 / max(self._zoom, 0.25)
        best = None
        best_dist = tol
        for guide in self.scene.canvas.get("guides") or []:
            pos_t = max(0.0, min(1.0, float(guide.get("position") or 0)))
            if guide.get("axis") == "h":
                gy = pos_t * ch
                dist = abs(pos.y() - gy)
                on_handle = pos.x() <= handle * 2
            else:
                gx = pos_t * cw
                dist = abs(pos.x() - gx)
                on_handle = pos.y() <= handle * 2
            limit = tol * 1.8 if on_handle else tol
            if dist <= limit and dist <= best_dist:
                best = guide
                best_dist = dist
        return best

    def _paint_selection(self, painter: QtGui.QPainter):
        painter.save()
        for widget_id in self.scene.selected_ids:
            item = self.scene.widget_by_id(widget_id)
            if not item:
                continue
            rect = QtCore.QRectF(item["x"], item["y"], item["w"], item["h"])
            painter.setPen(QtGui.QPen(QtGui.QColor("#7ec8ff"), 1.5))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(rect.adjusted(-1, -1, 1, 1))
            if widget_id == (self.scene.selected_ids[-1] if self.scene.selected_ids else None):
                painter.setBrush(QtGui.QColor("#7ec8ff"))
                hs = 4.0 / max(self._zoom, 0.25)
                for hx, hy in self.handle_points(item):
                    painter.drawRect(QtCore.QRectF(hx - hs, hy - hs, hs * 2, hs * 2))
        painter.restore()

    def handle_points(self, item: dict):
        x, y, w, h = item["x"], item["y"], item["w"], item["h"]
        return [
            (x, y),
            (x + w / 2, y),
            (x + w, y),
            (x + w, y + h / 2),
            (x + w, y + h),
            (x + w / 2, y + h),
            (x, y + h),
            (x, y + h / 2),
        ]

    def handle_at(self, pos: QtCore.QPointF) -> tuple[str | None, int]:
        if not self.scene.selected_ids:
            return None, -1
        item = self.scene.widget_by_id(self.scene.selected_ids[-1])
        if not item:
            return None, -1
        tol = 6.0 / max(self._zoom, 0.25)
        for index, (hx, hy) in enumerate(self.handle_points(item)):
            if abs(pos.x() - hx) <= tol and abs(pos.y() - hy) <= tol:
                return item["id"], index
        return None, -1


class OverlayWindow(QtWidgets.QWidget):
    """Bordered-or-frameless capture window titled GEX Overlay."""

    def __init__(self, scene: OverlayScene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.setObjectName("GexOverlayWindow")
        self.setWindowTitle(OVERLAY_WINDOW_TITLE)
        self.view = OverlayView(scene, interactive=False, parent=self)
        self.drag_bar = QtWidgets.QWidget(self)
        self.drag_bar.setFixedHeight(22)
        self.drag_bar.setCursor(QtCore.Qt.SizeAllCursor)
        label = QtWidgets.QLabel("GEX Overlay  —  hide this bar before capturing")
        label.setAlignment(QtCore.Qt.AlignCenter)
        bar_layout = QtWidgets.QHBoxLayout(self.drag_bar)
        bar_layout.setContentsMargins(6, 0, 6, 0)
        bar_layout.addWidget(label)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.drag_bar)
        layout.addWidget(self.view)
        self._drag_origin = None
        self._applying_flags = False
        self.drag_bar.installEventFilter(self)
        self._chrome_sig = None
        self.scene.changed.connect(self._on_scene_changed)
        self._apply_window_flags()
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    def showEvent(self, event):
        super().showEvent(event)
        self.view.attach_bus()
        if not self._applying_flags:
            self._apply_click_through(is_onscreen_mode(self.scene.canvas))

    def hideEvent(self, event):
        self.view.detach_bus()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.view.detach_bus()
        super().closeEvent(event)

    def _chrome_signature(self):
        canvas = self.scene.canvas
        return (
            normalize_background_mode(canvas.get("background_mode")),
            canvas.get("width"),
            canvas.get("height"),
            canvas.get("monitor_index"),
            canvas.get("monitor_name"),
            canvas.get("frameless"),
            canvas.get("always_on_top"),
            canvas.get("show_drag_bar"),
            canvas.get("chroma_color"),
        )

    def _on_scene_changed(self):
        sig = self._chrome_signature()
        if sig == self._chrome_sig:
            return
        self._apply_window_flags()

    def _apply_window_flags(self):
        if self._applying_flags:
            return
        self._applying_flags = True
        try:
            self._chrome_sig = self._chrome_signature()
            onscreen = is_onscreen_mode(self.scene.canvas)
            visible = self.isVisible()
            if onscreen:
                flags = (
                    QtCore.Qt.Window
                    | QtCore.Qt.FramelessWindowHint
                    | QtCore.Qt.WindowStaysOnTopHint
                    | QtCore.Qt.Tool
                    | QtCore.Qt.WindowDoesNotAcceptFocus
                    | QtCore.Qt.WindowTransparentForInput
                )
                self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
                self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
                self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
                flags_changed = int(self.windowFlags()) != int(flags)
                if flags_changed:
                    self.setWindowFlags(flags)
                self.drag_bar.setVisible(False)
                apply_onscreen_geometry(self.scene, emit=False)
                info = resolve_overlay_screen(self.scene.canvas)
                self.view._sync_paint_mode()
                self.view._apply_size()
                if info:
                    self.setGeometry(info["x"], info["y"], info["width"], info["height"])
                else:
                    self.adjustSize()
            else:
                flags = QtCore.Qt.Window | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint
                if self.scene.canvas.get("frameless"):
                    flags = QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint
                if self.scene.canvas.get("always_on_top"):
                    flags |= QtCore.Qt.WindowStaysOnTopHint
                self.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)
                self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
                self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, False)
                flags_changed = int(self.windowFlags()) != int(flags)
                if flags_changed:
                    self.setWindowFlags(flags)
                show_bar = bool(self.scene.canvas.get("show_drag_bar", True))
                self.drag_bar.setVisible(show_bar)
                chroma = qcolor(self.scene.canvas.get("chroma_color"), "#00FF00")
                self.drag_bar.setStyleSheet(f"background:{chroma.darker(130).name()}; color:#111;")
                self.view._sync_paint_mode()
                self.view._apply_size()
                self.adjustSize()
            if visible and flags_changed:
                self.show()
            self._apply_click_through(onscreen)
        finally:
            self._applying_flags = False

    def _apply_click_through(self, enabled: bool):
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            gwl_exstyle = -20
            ws_ex_transparent = 0x00000020
            ws_ex_noactivate = 0x08000000
            ws_ex_toolwindow = 0x00000080
            if ctypes.sizeof(ctypes.c_void_p) == 8:
                user32.GetWindowLongPtrW.restype = ctypes.c_longlong
                user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
                style = user32.GetWindowLongPtrW(hwnd, gwl_exstyle)
                extras = ws_ex_transparent | ws_ex_noactivate | ws_ex_toolwindow
                style = (style | extras) if enabled else (style & ~extras)
                user32.SetWindowLongPtrW(hwnd, gwl_exstyle, style)
            else:
                style = user32.GetWindowLongW(hwnd, gwl_exstyle)
                extras = ws_ex_transparent | ws_ex_noactivate | ws_ex_toolwindow
                style = (style | extras) if enabled else (style & ~extras)
                user32.SetWindowLongW(hwnd, gwl_exstyle, style)
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
        except Exception as err:
            syslog.warning(f"OBS OVERLAY: click-through style failed: {err}")

    def eventFilter(self, watched, event):
        if watched is self.drag_bar:
            if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if event.type() == QtCore.QEvent.MouseMove and self._drag_origin is not None and event.buttons() & QtCore.Qt.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_origin)
                return True
            if event.type() == QtCore.QEvent.MouseButtonRelease:
                self._drag_origin = None
                return True
        return super().eventFilter(watched, event)

    def _context_menu(self, pos):
        if is_onscreen_mode(self.scene.canvas):
            return
        menu = QtWidgets.QMenu(self)
        top = menu.addAction("Always on top")
        top.setCheckable(True)
        top.setChecked(bool(self.scene.canvas.get("always_on_top")))
        bar = menu.addAction("Show drag bar")
        bar.setCheckable(True)
        bar.setChecked(bool(self.scene.canvas.get("show_drag_bar", True)))
        frame = menu.addAction("Frameless window")
        frame.setCheckable(True)
        frame.setChecked(bool(self.scene.canvas.get("frameless")))
        menu.addSeparator()
        close_action = menu.addAction("Close overlay")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is top:
            self.scene.canvas["always_on_top"] = top.isChecked()
            self.scene._dirty = True
            self._apply_window_flags()
            self.show()
        elif chosen is bar:
            self.scene.canvas["show_drag_bar"] = bar.isChecked()
            self.scene._dirty = True
            self._apply_window_flags()
        elif chosen is frame:
            self.scene.canvas["frameless"] = frame.isChecked()
            self.scene._dirty = True
            self._apply_window_flags()
            self.show()
        elif chosen is close_action:
            self.hide()
