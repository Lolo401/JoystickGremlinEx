# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import math
import os
from typing import Any

from PySide6 import QtCore, QtGui

from .model import is_onscreen_mode, normalize_background_mode
from .shapes import normalize_shape_kind, shape_path


def qcolor(value, default="#ffffff") -> QtGui.QColor:
    color = QtGui.QColor(value if value else default)
    if not color.isValid():
        color = QtGui.QColor(default)
    return color


def _font_scale(item: dict[str, Any] | None) -> float:
    if not item:
        return 1.0
    style = item.get("style") or {}
    if not style.get("auto_scale_font"):
        return 1.0
    base = float(style.get("font_scale_base") or 0)
    if base <= 1:
        base = 100.0
    current = min(float(item.get("w") or 1), float(item.get("h") or 1))
    return max(0.35, min(6.0, current / base))


def _scaled_font_px(style: dict[str, Any], key: str, item: dict[str, Any] | None, default: int = 11) -> int:
    size = style.get(key)
    if size is None and key.startswith("axis_"):
        size = style.get("font_size")
    px = float(size if size is not None else default)
    return max(6, int(round(px * _font_scale(item))))


def effective_font_size(item: dict[str, Any] | None, key: str = "font_size", default: int = 11) -> int:
    """Pixel size actually drawn, including auto-scale."""
    style = (item or {}).get("style") or {}
    return _scaled_font_px(style, key, item, default)


def _make_font(family: str | None, size, bold: bool) -> QtGui.QFont:
    font = QtGui.QFont()
    font.setFamily(family or "Segoe UI")
    font.setPixelSize(max(6, int(size or 11)))
    font.setBold(bool(bold))
    font.setStyleStrategy(QtGui.QFont.PreferAntialias)
    return font


def _font(style: dict[str, Any], item: dict[str, Any] | None = None) -> QtGui.QFont:
    return _make_font(style.get("font_family"), _scaled_font_px(style, "font_size", item), style.get("font_bold", True))


def _axis_label_font(style: dict[str, Any], item: dict[str, Any] | None = None) -> QtGui.QFont:
    return _make_font(
        style.get("axis_label_font_family") or style.get("font_family"),
        _scaled_font_px(style, "axis_label_font_size", item),
        style.get("axis_label_font_bold", style.get("font_bold", True)),
    )


def _pen(color, width=1.0) -> QtGui.QPen:
    pen = QtGui.QPen(qcolor(color))
    pen.setWidthF(float(width))
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    return pen


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _deadzone(value: float, style: dict) -> float:
    zone = float(style.get("deadzone") or 0.0)
    if zone > 0 and abs(value) < zone:
        return 0.0
    return value


def _xy(value) -> tuple[float, float]:
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return _clamp(float(value[0])), _clamp(float(value[1]))
    if isinstance(value, (int, float)):
        return _clamp(float(value)), 0.0
    return 0.0, 0.0


def _axis(value) -> float:
    if isinstance(value, (tuple, list)):
        return _clamp(float(value[0] if value else 0.0))
    if isinstance(value, (int, float)):
        return _clamp(float(value))
    return 0.0


def _pressed(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return abs(value) > 0.5
    if isinstance(value, (tuple, list)) and value:
        return any(abs(float(v)) > 0.15 for v in value)
    return False


def widget_rect(item: dict[str, Any]) -> QtCore.QRectF:
    return QtCore.QRectF(item["x"], item["y"], item["w"], item["h"])


def _inner_rect(rect: QtCore.QRectF, style: dict[str, Any]) -> QtCore.QRectF:
    inset = max(0.5, float(style.get("border_width") or 2) * 0.5)
    return rect.adjusted(inset, inset, -inset, -inset)


def _with_grid_fade(painter: QtGui.QPainter, bounds: QtCore.QRectF, style: dict[str, Any], circular: bool, draw_cb):
    if not style.get("grid_fade") or bounds.width() < 4 or bounds.height() < 4:
        draw_cb(painter)
        return
    width = max(1, int(math.ceil(bounds.width())))
    height = max(1, int(math.ceil(bounds.height())))
    pm = QtGui.QPixmap(width, height)
    pm.fill(QtCore.Qt.transparent)
    gp = QtGui.QPainter(pm)
    gp.translate(-bounds.left(), -bounds.top())
    draw_cb(gp)
    gp.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
    radius = min(bounds.width(), bounds.height()) / 2.0 if circular else max(bounds.width(), bounds.height()) / 2.0
    gradient = QtGui.QRadialGradient(bounds.center(), max(1.0, radius))
    gradient.setColorAt(0.0, QtGui.QColor(0, 0, 0, 255))
    gradient.setColorAt(0.55, QtGui.QColor(0, 0, 0, 255))
    gradient.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
    gp.fillRect(bounds, gradient)
    gp.end()
    painter.drawPixmap(bounds.topLeft(), pm)


def _draw_square_grid(painter: QtGui.QPainter, inner: QtCore.QRectF, style: dict[str, Any]):
    if not style.get("show_grid", True):
        return

    def _lines(target: QtGui.QPainter):
        target.setPen(_pen(style.get("grid"), style.get("grid_width") or 1))
        for i in range(1, 4):
            t = i / 4.0
            target.drawLine(
                QtCore.QPointF(inner.left() + inner.width() * t, inner.top()),
                QtCore.QPointF(inner.left() + inner.width() * t, inner.bottom()),
            )
            target.drawLine(
                QtCore.QPointF(inner.left(), inner.top() + inner.height() * t),
                QtCore.QPointF(inner.right(), inner.top() + inner.height() * t),
            )

    _with_grid_fade(painter, inner, style, False, _lines)


def _draw_ring_grid(painter: QtGui.QPainter, circle: QtCore.QRectF, style: dict[str, Any], rings: int):
    if not style.get("show_grid", True):
        return
    rings = max(1, int(rings))

    def _rings(target: QtGui.QPainter):
        target.setBrush(QtCore.Qt.NoBrush)
        target.setPen(_pen(style.get("grid"), style.get("grid_width") or 1))
        for i in range(1, rings + 1):
            t = i / float(rings)
            inset = (1.0 - t) * min(circle.width(), circle.height()) / 2.0
            target.drawEllipse(circle.adjusted(inset, inset, -inset, -inset))

    _with_grid_fade(painter, circle, style, True, _rings)


def _draw_crosshairs(painter: QtGui.QPainter, bounds: QtCore.QRectF, style: dict[str, Any]):
    if not style.get("show_center_line", True):
        return
    painter.setPen(_pen(style.get("crosshair"), max(1.0, float(style.get("grid_width") or 1.2))))
    painter.drawLine(QtCore.QPointF(bounds.center().x(), bounds.top()), QtCore.QPointF(bounds.center().x(), bounds.bottom()))
    painter.drawLine(QtCore.QPointF(bounds.left(), bounds.center().y()), QtCore.QPointF(bounds.right(), bounds.center().y()))


def widget_dirty_rect(item: dict[str, Any]) -> QtCore.QRect:
    """Widget bounds plus label overflow, for partial updates."""
    rect = widget_rect(item).toAlignedRect()
    pad = max(28, _scaled_font_px(item.get("style") or {}, "font_size", item) + 12)
    return rect.adjusted(-pad, -pad, pad, pad)


def _draw_label(painter: QtGui.QPainter, item: dict[str, Any], rect: QtCore.QRectF, color=None):
    style = item.get("style") or {}
    if not style.get("show_label", True):
        return
    text = item.get("label") or ""
    if not text:
        return
    painter.save()
    painter.setPen(qcolor(color or style.get("font_color"), "#f4efe4"))
    painter.setFont(_font(style, item))
    label_rect = rect.adjusted(
        float(style.get("label_offset_x") or 0),
        float(style.get("label_offset_y") or 0),
        float(style.get("label_offset_x") or 0),
        float(style.get("label_offset_y") or 0),
    )
    painter.drawText(label_rect, int(QtCore.Qt.AlignCenter), text)
    painter.restore()


def _rounded(rect: QtCore.QRectF, radius: float) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def paint_shape(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    kind = normalize_shape_kind(style.get("shape_kind"))
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    painter.setPen(_pen(style.get("border"), style.get("border_width") or 2))
    fill = qcolor(style.get("fill"), "#101820")
    closed = bool(style.get("shape_closed")) if kind == "line" else True
    if kind == "line" and not closed:
        painter.setBrush(QtCore.Qt.NoBrush)
    else:
        painter.setBrush(fill)
    painter.drawPath(shape_path(item))
    _draw_label(painter, item, rect)
    painter.restore()


_widget_image_cache: dict[str, QtGui.QPixmap] = {}


def _widget_image_pixmap(path: str) -> QtGui.QPixmap:
    if not path:
        return QtGui.QPixmap()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return QtGui.QPixmap()
    key = f"{path}|{mtime}"
    pixmap = _widget_image_cache.get(key)
    if pixmap is not None and not pixmap.isNull():
        return pixmap
    image = QtGui.QImage(path)
    if image.isNull():
        return QtGui.QPixmap()
    if image.hasAlphaChannel():
        image = image.convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied)
    pixmap = QtGui.QPixmap.fromImage(image)
    if len(_widget_image_cache) > 24:
        _widget_image_cache.clear()
    _widget_image_cache[key] = pixmap
    return pixmap


def paint_image(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    fill = qcolor(style.get("fill"), "#00000000")
    border_w = float(style.get("border_width") or 0)
    if fill.alpha() > 0:
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRect(rect)
    path = style.get("image_path") or ""
    pixmap = _widget_image_pixmap(path)
    if pixmap.isNull():
        painter.setPen(_pen(style.get("border"), max(1.0, border_w or 1.5)))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(rect)
        painter.setPen(qcolor(style.get("font_color"), "#f4efe4"))
        painter.drawText(rect, int(QtCore.Qt.AlignCenter), "No image")
        _draw_label(painter, item, rect)
        painter.restore()
        return
    keep_aspect = bool(style.get("image_keep_aspect", True))
    mode = QtCore.Qt.KeepAspectRatio if keep_aspect else QtCore.Qt.IgnoreAspectRatio
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
    scaled = pixmap.scaled(rect.size().toSize(), mode, QtCore.Qt.SmoothTransformation)
    target = QtCore.QRectF(
        rect.center().x() - scaled.width() / 2.0,
        rect.center().y() - scaled.height() / 2.0,
        scaled.width(),
        scaled.height(),
    )
    painter.drawPixmap(target.toRect(), scaled)
    if border_w > 0:
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(_pen(style.get("border"), border_w))
        painter.drawRect(rect)
    _draw_label(painter, item, rect)
    painter.restore()


def paint_panel(painter: QtGui.QPainter, item: dict[str, Any], value):
    paint_shape(painter, item, value)


def paint_label(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    fill = qcolor(style.get("fill"), "#00000000")
    border_w = float(style.get("border_width") or 0)
    if fill.alpha() > 0 or border_w > 0:
        if border_w > 0:
            painter.setPen(_pen(style.get("border"), border_w))
        else:
            painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(fill if fill.alpha() > 0 else QtCore.Qt.NoBrush)
        radius = float(style.get("corner_radius") or 0)
        if radius > 0:
            painter.drawRoundedRect(rect, radius, radius)
        else:
            painter.drawRect(rect)
    _draw_label(painter, item, rect)
    painter.restore()


def paint_button(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    on = _pressed(value)
    fill = style.get("fill_on") if on else style.get("fill")
    border = style.get("border_on") if on else style.get("border")
    shape = (style.get("shape") or "rounded").casefold()
    radius = float(style.get("corner_radius") or 6)
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    painter.setPen(_pen(border, style.get("border_width") or 2))
    painter.setBrush(qcolor(fill, "#3a1518"))
    if shape == "circle":
        side = min(rect.width(), rect.height())
        painter.drawEllipse(QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side))
    elif shape == "pill":
        painter.drawPath(_rounded(rect, rect.height() / 2))
    elif shape == "rect":
        painter.drawRect(rect)
    else:
        painter.drawPath(_rounded(rect, radius))
    _draw_label(painter, item, rect)
    painter.restore()


def _draw_axis_labels(painter: QtGui.QPainter, item: dict[str, Any], rect: QtCore.QRectF):
    style = item.get("style") or {}
    if not style.get("show_axis_labels", True):
        return
    painter.save()
    painter.setPen(qcolor(style.get("axis_label_font_color") or style.get("font_color"), "#f4efe4"))
    painter.setFont(_axis_label_font(style, item))
    painter.drawText(rect.adjusted(0, 2, 0, 0), int(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop), style.get("axis_label_n") or "")
    painter.drawText(rect.adjusted(0, 0, 0, -2), int(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom), style.get("axis_label_s") or "")
    painter.drawText(rect.adjusted(4, 0, 0, 0), int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft), style.get("axis_label_w") or "")
    painter.drawText(rect.adjusted(0, 0, -4, 0), int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight), style.get("axis_label_e") or "")
    painter.restore()


def _indicator(painter: QtGui.QPainter, center: QtCore.QPointF, style: dict[str, Any], glow=None):
    size = float(style.get("indicator_size") or 12)
    color = qcolor(style.get("indicator"), "#ff5a3c")
    shape = (style.get("indicator_shape") or "circle").casefold()
    if glow is None:
        glow = bool(style.get("show_dot_shadow", True))
    painter.setPen(QtCore.Qt.NoPen)
    if glow:
        glow_color = QtGui.QColor(color)
        glow_color.setAlpha(80)
        painter.setBrush(glow_color)
        extra = size * 0.45
        if shape == "square":
            painter.drawRect(QtCore.QRectF(center.x() - size / 2 - extra / 2, center.y() - size / 2 - extra / 2, size + extra, size + extra))
        else:
            painter.drawEllipse(center, size * 0.95, size * 0.95)
    painter.setBrush(color)
    if shape == "square":
        painter.drawRect(QtCore.QRectF(center.x() - size / 2, center.y() - size / 2, size, size))
    else:
        painter.drawEllipse(center, size / 2, size / 2)


def _draw_dot_crosshair(painter: QtGui.QPainter, bounds: QtCore.QRectF, cx: float, cy: float, style: dict[str, Any], circular: bool = False):
    """Horizontal/vertical lines through the moving dot, in the dot color."""
    if not style.get("show_dot_crosshair"):
        return
    painter.setPen(_pen(style.get("indicator"), style.get("grid_width") or 1.0))
    if circular:
        origin = bounds.center()
        radius = min(bounds.width(), bounds.height()) / 2.0
        dx2 = radius * radius - (cy - origin.y()) ** 2
        dy2 = radius * radius - (cx - origin.x()) ** 2
        if dx2 > 0.5:
            dx = math.sqrt(dx2)
            painter.drawLine(QtCore.QPointF(origin.x() - dx, cy), QtCore.QPointF(origin.x() + dx, cy))
        if dy2 > 0.5:
            dy = math.sqrt(dy2)
            painter.drawLine(QtCore.QPointF(cx, origin.y() - dy), QtCore.QPointF(cx, origin.y() + dy))
        return
    painter.drawLine(QtCore.QPointF(bounds.left(), cy), QtCore.QPointF(bounds.right(), cy))
    painter.drawLine(QtCore.QPointF(cx, bounds.top()), QtCore.QPointF(cx, bounds.bottom()))


def _angle_step(style: dict[str, Any]) -> int:
    try:
        step = int(style.get("angle_step") or 0)
    except (TypeError, ValueError):
        return 0
    return step if step in (15, 30, 45) else 0


def _draw_angle_lines(painter: QtGui.QPainter, center: QtCore.QPointF, radius: float, style: dict[str, Any]):
    step = _angle_step(style)
    if not step:
        return
    painter.setPen(_pen(style.get("grid"), style.get("grid_width") or 1))
    for deg in range(0, 360, step):
        angle = math.radians(deg)
        painter.drawLine(center, QtCore.QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius))


def _caption(painter: QtGui.QPainter, item: dict[str, Any], rect: QtCore.QRectF, vertical: bool):
    if not (item.get("style") or {}).get("show_label", True) or not item.get("label"):
        return
    if vertical:
        _draw_label(painter, item, QtCore.QRectF(rect.x(), rect.bottom() + 2, rect.width(), 18))
    else:
        _draw_label(painter, item, QtCore.QRectF(rect.x(), rect.y() - 18, rect.width(), 16))


def paint_axis_bar(painter: QtGui.QPainter, item: dict[str, Any], value):
    """1D pad: track + moving dot, horizontal or vertical."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    vertical = (style.get("orientation") or "vertical").casefold() != "horizontal"
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    painter.setPen(_pen(style.get("border"), style.get("border_width") or 2))
    painter.setBrush(qcolor(style.get("fill"), "#121826"))
    painter.drawRoundedRect(rect, float(style.get("corner_radius") or 6), float(style.get("corner_radius") or 6))
    inner = _inner_rect(rect, style)
    if style.get("show_grid", True):

        def _bar_grid(target: QtGui.QPainter):
            target.setPen(_pen(style.get("grid"), style.get("grid_width") or 1))
            if vertical:
                for i in range(1, 4):
                    t = i / 4.0
                    y = inner.top() + inner.height() * t
                    target.drawLine(QtCore.QPointF(inner.left(), y), QtCore.QPointF(inner.right(), y))
            else:
                for i in range(1, 4):
                    t = i / 4.0
                    x = inner.left() + inner.width() * t
                    target.drawLine(QtCore.QPointF(x, inner.top()), QtCore.QPointF(x, inner.bottom()))

        _with_grid_fade(painter, inner, style, False, _bar_grid)
    if style.get("show_center_line", True):
        painter.setPen(_pen(style.get("crosshair"), 1.2))
        if vertical:
            painter.drawLine(QtCore.QPointF(inner.center().x(), inner.top()), QtCore.QPointF(inner.center().x(), inner.bottom()))
        else:
            painter.drawLine(QtCore.QPointF(inner.left(), inner.center().y()), QtCore.QPointF(inner.right(), inner.center().y()))
    if vertical:
        t = (axis + 1.0) / 2.0
        cx = inner.center().x()
        cy = inner.bottom() - t * inner.height()
    else:
        t = (axis + 1.0) / 2.0
        cx = inner.left() + t * inner.width()
        cy = inner.center().y()
    _draw_dot_crosshair(painter, inner, cx, cy, style)
    _indicator(painter, QtCore.QPointF(cx, cy), style)
    _caption(painter, item, rect, vertical)
    painter.restore()


def paint_axis_radio(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Stepped 1D selector (Touch OSC Radio)."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    steps = max(2, int(style.get("radio_steps") or 5))
    idx = int(round((axis + 1.0) / 2.0 * (steps - 1)))
    idx = max(0, min(steps - 1, idx))
    vertical = (style.get("orientation") or "horizontal").casefold() == "vertical"
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    gap = 3.0
    if vertical:
        cell_h = (rect.height() - gap * (steps - 1)) / steps
        for i in range(steps):
            cell = QtCore.QRectF(rect.x(), rect.y() + i * (cell_h + gap), rect.width(), cell_h)
            on = i == (steps - 1 - idx)
            painter.setPen(_pen(style.get("border_on") if on else style.get("border"), style.get("border_width") or 1.5))
            painter.setBrush(qcolor(style.get("fill_on") if on else style.get("fill"), "#121826"))
            painter.drawRoundedRect(cell, 3, 3)
    else:
        cell_w = (rect.width() - gap * (steps - 1)) / steps
        for i in range(steps):
            cell = QtCore.QRectF(rect.x() + i * (cell_w + gap), rect.y(), cell_w, rect.height())
            on = i == idx
            painter.setPen(_pen(style.get("border_on") if on else style.get("border"), style.get("border_width") or 1.5))
            painter.setBrush(qcolor(style.get("fill_on") if on else style.get("fill"), "#121826"))
            painter.drawRoundedRect(cell, 3, 3)
    _caption(painter, item, rect, vertical)
    painter.restore()


def paint_axis_fader(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Touch OSC fader: ladder track, value fill up to the thumb, sliding thumb."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    vertical = (style.get("orientation") or "vertical").casefold() != "horizontal"
    steps = max(3, int(style.get("radio_steps") or 8))
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    radius = float(style.get("corner_radius") or 4)
    painter.setPen(_pen(style.get("border"), style.get("border_width") or 2))
    painter.setBrush(qcolor(style.get("fill") or style.get("track"), "#121826"))
    painter.drawRoundedRect(rect, radius, radius)
    inner = rect.adjusted(3, 3, -3, -3)
    t = (axis + 1.0) / 2.0
    painter.setClipPath(_rounded(rect, radius))
    if vertical:
        thumb_h = max(8.0, float(style.get("indicator_size") or 0) or (inner.height() / steps))
        thumb_h = min(thumb_h, inner.height() * 0.45)
        travel = max(0.0, inner.height() - thumb_h)
        y = inner.bottom() - thumb_h - t * travel
        thumb = QtCore.QRectF(inner.x(), y, inner.width(), thumb_h)
        fill_h = max(0.0, inner.bottom() - thumb.bottom())
        filled = QtCore.QRectF(inner.x(), thumb.bottom(), inner.width(), fill_h)
    else:
        thumb_w = max(8.0, float(style.get("indicator_size") or 0) or (inner.width() / steps))
        thumb_w = min(thumb_w, inner.width() * 0.45)
        travel = max(0.0, inner.width() - thumb_w)
        x = inner.left() + t * travel
        thumb = QtCore.QRectF(x, inner.y(), thumb_w, inner.height())
        filled = QtCore.QRectF(inner.x(), inner.y(), max(0.0, thumb.left() - inner.left()), inner.height())
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(qcolor(style.get("fill_bar"), "#ff6b35"))
    painter.drawRect(filled)
    painter.setPen(_pen(style.get("grid"), style.get("grid_width") or 1.2))
    if vertical:
        for i in range(1, steps):
            gy = inner.top() + inner.height() * (i / steps)
            painter.drawLine(QtCore.QPointF(inner.left(), gy), QtCore.QPointF(inner.right(), gy))
    else:
        for i in range(1, steps):
            gx = inner.left() + inner.width() * (i / steps)
            painter.drawLine(QtCore.QPointF(gx, inner.top()), QtCore.QPointF(gx, inner.bottom()))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(qcolor(style.get("fill_on") or style.get("indicator"), "#ff5a3c"))
    painter.drawRect(thumb)
    painter.setClipping(False)
    painter.setPen(_pen(style.get("border"), style.get("border_width") or 2))
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
    _caption(painter, item, rect, vertical)
    painter.restore()


def paint_axis_radial(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Touch OSC radial: 270° arc with ticks and value fill."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    side = min(rect.width(), rect.height())
    circle = QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
    track = circle.adjusted(12, 12, -12, -12)
    width = max(8.0, float(style.get("needle_width") or 14))
    start = 225 * 16
    span = -270 * 16
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(_pen(style.get("track") or style.get("fill"), width))
    painter.drawArc(track, start, span)
    filled = int(-270 * ((axis + 1) / 2) * 16)
    painter.setPen(_pen(style.get("fill_bar") or style.get("indicator"), width))
    painter.drawArc(track, start, filled)
    border_w = float(style.get("border_width") or 2)
    if border_w > 0:
        cx_track, cy_track = track.center().x(), track.center().y()
        track_r = min(track.width(), track.height()) / 2.0
        outer_r = track_r + width / 2.0
        inner_r_track = max(1.0, track_r - width / 2.0)
        painter.setPen(_pen(style.get("border"), border_w))
        painter.drawArc(QtCore.QRectF(cx_track - outer_r, cy_track - outer_r, outer_r * 2, outer_r * 2), start, span)
        painter.drawArc(QtCore.QRectF(cx_track - inner_r_track, cy_track - inner_r_track, inner_r_track * 2, inner_r_track * 2), start, span)
        for deg in (225.0, -45.0):
            rad = math.radians(deg)
            c, s = math.cos(rad), math.sin(rad)
            painter.drawLine(
                QtCore.QPointF(cx_track + c * inner_r_track, cy_track - s * inner_r_track),
                QtCore.QPointF(cx_track + c * outer_r, cy_track - s * outer_r),
            )
    ticks = max(2, int(style.get("radio_steps") or 11))
    painter.setPen(_pen(style.get("grid") or style.get("border"), 1.5))
    cx, cy = circle.center().x(), circle.center().y()
    outer = side / 2 - 2
    inner_r = side / 2 - width - 10
    for i in range(ticks):
        t = i / (ticks - 1)
        angle = math.radians(225 - 270 * t)
        painter.drawLine(
            QtCore.QPointF(cx + math.cos(angle) * inner_r, cy - math.sin(angle) * inner_r),
            QtCore.QPointF(cx + math.cos(angle) * outer, cy - math.sin(angle) * outer),
        )
    _draw_label(painter, item, rect)
    painter.restore()


def _donut_slice(cx: float, cy: float, inner_r: float, outer_r: float, start_deg: float, span_deg: float) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    outer = QtCore.QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
    inner = QtCore.QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
    path.arcMoveTo(outer, start_deg)
    path.arcTo(outer, start_deg, span_deg)
    path.arcTo(inner, start_deg + span_deg, -span_deg)
    path.closeSubpath()
    return path


def paint_axis_encoder(painter: QtGui.QPainter, item: dict[str, Any], value):
    """Touch OSC encoder: full donut with ticks and one moving highlighted wedge."""
    style = item.get("style") or {}
    rect = widget_rect(item)
    axis = _deadzone(_axis(value), style)
    if style.get("invert_display"):
        axis = -axis
    ticks = max(4, int(style.get("radio_steps") or 16))
    idx = int(round((axis + 1.0) / 2.0 * (ticks - 1)))
    idx = max(0, min(ticks - 1, idx))
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    side = min(rect.width(), rect.height())
    cx, cy = rect.center().x(), rect.center().y()
    outer_r = side / 2 - 2
    ring_w = float(style.get("needle_width") or 0)
    if ring_w >= 8:
        inner_r = max(outer_r * 0.22, outer_r - ring_w)
    else:
        inner_r = outer_r * 0.48
    span = 360.0 / ticks
    dim = qcolor(style.get("fill") or style.get("track"), "#121826")
    lit = qcolor(style.get("fill_on") or style.get("indicator") or style.get("fill_bar"), "#ff5a3c")
    painter.setPen(QtCore.Qt.NoPen)
    for i in range(ticks):
        painter.setBrush(lit if i == idx else dim)
        # Qt 0° = 3 o'clock, positive CCW; start at 12 o'clock and walk clockwise.
        start = 90.0 - i * span
        painter.drawPath(_donut_slice(cx, cy, inner_r, outer_r, start, -span))
    painter.setPen(_pen(style.get("grid") or style.get("border"), style.get("grid_width") or 1.2))
    inset = 1.0
    for i in range(ticks):
        rad = math.radians(90.0 - i * span)
        c, s = math.cos(rad), math.sin(rad)
        painter.drawLine(
            QtCore.QPointF(cx + c * (inner_r + inset), cy - s * (inner_r + inset)),
            QtCore.QPointF(cx + c * (outer_r - inset), cy - s * (outer_r - inset)),
        )
    border_w = float(style.get("border_width") or 2)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(_pen(style.get("border"), border_w))
    painter.drawEllipse(QtCore.QPointF(cx, cy), outer_r, outer_r)
    painter.drawEllipse(QtCore.QPointF(cx, cy), inner_r, inner_r)
    _draw_label(painter, item, rect)
    painter.restore()


def paint_axis_dial(painter: QtGui.QPainter, item: dict[str, Any], value):
    paint_axis_radial(painter, item, value)


def paint_axis_stick_square(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    x, y = _xy(value)
    x, y = _deadzone(x, style), _deadzone(y, style)
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    painter.setPen(_pen(style.get("border"), style.get("border_width") or 2))
    painter.setBrush(qcolor(style.get("fill"), "#121826"))
    painter.drawRoundedRect(rect, 6, 6)
    inner = _inner_rect(rect, style)
    _draw_square_grid(painter, inner, style)
    _draw_crosshairs(painter, inner, style)
    cx = inner.center().x() + x * (inner.width() / 2)
    cy = inner.center().y() + y * (inner.height() / 2)
    _draw_dot_crosshair(painter, inner, cx, cy, style)
    _indicator(painter, QtCore.QPointF(cx, cy), style)
    _draw_axis_labels(painter, item, rect)
    _draw_label(painter, item, rect)
    painter.restore()


def paint_axis_stick_circle(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    x, y = _xy(value)
    x, y = _deadzone(x, style), _deadzone(y, style)
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    side = min(rect.width(), rect.height())
    circle = QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
    painter.setPen(_pen(style.get("border"), style.get("border_width") or 2))
    painter.setBrush(qcolor(style.get("fill"), "#121826"))
    painter.drawEllipse(circle)
    radius = min(circle.width(), circle.height()) / 2.0
    _draw_angle_lines(painter, circle.center(), radius, style)
    _draw_ring_grid(painter, circle, style, int(style.get("ring_count") or 2))
    _draw_crosshairs(painter, circle, style)
    cx = circle.center().x() + x * radius
    cy = circle.center().y() + y * radius
    _draw_dot_crosshair(painter, circle, cx, cy, style, circular=True)
    _indicator(painter, QtCore.QPointF(cx, cy), style)
    _draw_axis_labels(painter, item, rect)
    _draw_label(painter, item, rect)
    painter.restore()


def paint_axis_crosshair(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    x, y = _xy(value)
    x, y = _deadzone(x, style), _deadzone(y, style)
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    side = min(rect.width(), rect.height())
    circle = QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
    painter.setPen(_pen(style.get("border"), style.get("border_width") or 1.5))
    painter.setBrush(qcolor(style.get("fill"), "#0a1220"))
    painter.drawEllipse(circle)
    radius = min(circle.width(), circle.height()) / 2.0
    _draw_angle_lines(painter, circle.center(), radius, style)
    _draw_ring_grid(painter, circle, style, int(style.get("ring_count") or 3))
    _draw_crosshairs(painter, circle, style)
    origin = circle.center()
    travel = max(8.0, radius - 2)
    cx = origin.x() + x * travel
    cy = origin.y() + y * travel
    _draw_dot_crosshair(painter, circle, cx, cy, style, circular=True)
    dist = math.hypot(cx - origin.x(), cy - origin.y())
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(_pen(style.get("indicator"), max(1.5, float(style.get("needle_width") or 2))))
    if dist > 2:
        painter.drawEllipse(origin, dist, dist)
    painter.drawLine(origin, QtCore.QPointF(cx, cy))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(qcolor(style.get("indicator"), "#ff5a3c"))
    painter.drawEllipse(origin, 2.5, 2.5)
    _indicator(painter, QtCore.QPointF(cx, cy), style)
    _draw_label(painter, item, rect)
    painter.restore()


def _hat_plus(painter: QtGui.QPainter, cx: float, cy: float, arm: float, thickness: float):
    painter.drawRoundedRect(QtCore.QRectF(cx - thickness / 2, cy - arm * 2, thickness, arm * 4), 4, 4)
    painter.drawRoundedRect(QtCore.QRectF(cx - arm * 2, cy - thickness / 2, arm * 4, thickness), 4, 4)


def paint_hat(painter: QtGui.QPainter, item: dict[str, Any], value):
    style = item.get("style") or {}
    rect = widget_rect(item)
    x, y = _xy(value)
    eight = int(style.get("hat_positions") or 4) >= 8
    painter.save()
    painter.setOpacity(float(style.get("opacity") or 1.0))
    painter.setPen(_pen(style.get("border"), style.get("border_width") or 2))
    painter.setBrush(qcolor(style.get("fill"), "#121826"))
    radius = float(style.get("corner_radius") or 8)
    painter.drawRoundedRect(rect, radius, radius)
    cx, cy = rect.center().x(), rect.center().y()
    arm = min(rect.width(), rect.height()) * 0.18
    thickness = min(rect.width(), rect.height()) * (0.14 + 0.04 * float(style.get("grid_width") or 1))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(qcolor(style.get("crosshair"), "#5a6a84"))
    _hat_plus(painter, cx, cy, arm, thickness)
    if eight:
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(45)
        _hat_plus(painter, 0, 0, arm * 0.92, thickness * 0.85)
        painter.restore()
    nx, ny = 0, 0
    if abs(x) > 0.15 or abs(y) > 0.15:
        if eight:
            nx = 0 if abs(x) < 0.15 else (1 if x > 0 else -1)
            ny = 0 if abs(y) < 0.15 else (1 if y > 0 else -1)
        elif abs(x) >= abs(y):
            nx = 1 if x > 0 else -1
        else:
            ny = 1 if y > 0 else -1
    if nx or ny:
        length = math.hypot(nx, ny) or 1.0
        dist = arm * 1.45
        px = cx + (nx / length) * dist
        py = cy - (ny / length) * dist
        color = qcolor(style.get("fill_on") or style.get("indicator"), "#ff6b35")
    else:
        px, py = cx, cy
        color = qcolor(style.get("indicator"), "#ff5a3c")
    size = float(style.get("indicator_size") or 12) * 0.45
    painter.setBrush(color)
    painter.drawEllipse(QtCore.QPointF(px, py), size, size)
    _draw_axis_labels(painter, item, rect)
    painter.restore()


_PAINTERS = {
    "axis_bar": paint_axis_bar,
    "axis_radio": paint_axis_radio,
    "axis_fader": paint_axis_fader,
    "axis_radial": paint_axis_radial,
    "axis_encoder": paint_axis_encoder,
    "axis_dial": paint_axis_radial,
    "axis_stick_square": paint_axis_stick_square,
    "axis_stick_circle": paint_axis_stick_circle,
    "axis_crosshair": paint_axis_crosshair,
    "button": paint_button,
    "hat": paint_hat,
    "label": paint_label,
    "shape": paint_shape,
    "panel": paint_shape,
    "image": paint_image,
}


def paint_widget(painter: QtGui.QPainter, item: dict[str, Any], value):
    if not item.get("visible", True):
        return
    fn = _PAINTERS.get(item.get("type"), paint_button)
    fn(painter, item, value)


_bg_image_cache: dict[tuple, QtGui.QPixmap] = {}


def paint_background(painter: QtGui.QPainter, canvas: dict[str, Any], rect: QtCore.QRect, preview: bool = False):
    mode = normalize_background_mode(canvas.get("background_mode"))
    if is_onscreen_mode(canvas):
        if preview:
            painter.fillRect(rect, QtGui.QColor("#1b2230"))
        return
    if mode == "image":
        path = canvas.get("image_path") or ""
        if path:
            key = (path, rect.width(), rect.height())
            pixmap = _bg_image_cache.get(key)
            if pixmap is None or pixmap.isNull():
                loaded = QtGui.QPixmap(path)
                if not loaded.isNull():
                    pixmap = loaded.scaled(rect.size(), QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
                    _bg_image_cache.clear()
                    _bg_image_cache[key] = pixmap
            if pixmap is not None and not pixmap.isNull():
                painter.drawPixmap(rect, pixmap)
                return
    painter.fillRect(rect, qcolor(canvas.get("chroma_color"), "#00FF00"))
