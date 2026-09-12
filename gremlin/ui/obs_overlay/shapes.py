# -*- coding: utf-8; -*-

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui


SHAPE_KINDS = (
    "rectangle",
    "circle",
    "triangle",
    "diamond",
    "line",
    "freeform",
)

SHAPE_KIND_LABELS = (
    ("rectangle", "Rectangle"),
    ("circle", "Circle"),
    ("triangle", "Triangle"),
    ("diamond", "Diamond"),
    ("line", "Line"),
    ("freeform", "Freeform"),
)


def normalize_shape_kind(value) -> str:
    kind = str(value or "rectangle").casefold().replace(" ", "_")
    if kind in ("rect", "rounded", "panel"):
        return "rectangle"
    if kind in ("ellipse", "oval"):
        return "circle"
    if kind in ("poly", "polygon", "bezier"):
        return "freeform"
    if kind in ("lines", "polyline"):
        return "line"
    return kind if kind in SHAPE_KINDS else "rectangle"


def is_shape_widget(item: dict[str, Any] | None) -> bool:
    return bool(item) and item.get("type") in ("shape", "panel")


def uses_editable_points(item: dict[str, Any] | None) -> bool:
    if not is_shape_widget(item):
        return False
    kind = normalize_shape_kind((item.get("style") or {}).get("shape_kind"))
    return kind in ("triangle", "diamond", "line", "freeform")


def _point(x: float, y: float) -> dict[str, float]:
    return {"x": float(x), "y": float(y), "in_x": 0.0, "in_y": 0.0, "out_x": 0.0, "out_y": 0.0}


def default_shape_points(kind: str) -> list[dict[str, float]]:
    kind = normalize_shape_kind(kind)
    if kind == "triangle":
        return [_point(0.5, 0.04), _point(0.96, 0.96), _point(0.04, 0.96)]
    if kind == "diamond":
        return [_point(0.5, 0.04), _point(0.96, 0.5), _point(0.5, 0.96), _point(0.04, 0.5)]
    if kind == "line":
        return [_point(0.04, 0.5), _point(0.96, 0.5)]
    if kind == "freeform":
        return [_point(0.08, 0.08), _point(0.92, 0.08), _point(0.92, 0.92), _point(0.08, 0.92)]
    return []


def normalize_shape_points(raw, kind: str | None = None) -> list[dict[str, float]]:
    points = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        try:
            x = max(0.0, min(1.0, float(entry.get("x", 0))))
            y = max(0.0, min(1.0, float(entry.get("y", 0))))
        except (TypeError, ValueError):
            continue
        try:
            in_x = float(entry.get("in_x") or 0)
            in_y = float(entry.get("in_y") or 0)
            out_x = float(entry.get("out_x") or 0)
            out_y = float(entry.get("out_y") or 0)
        except (TypeError, ValueError):
            in_x = in_y = out_x = out_y = 0.0
        points.append({"x": x, "y": y, "in_x": in_x, "in_y": in_y, "out_x": out_x, "out_y": out_y})
    if len(points) < 2:
        return default_shape_points(kind or "freeform")
    return points


def ensure_shape_points(item: dict[str, Any]) -> list[dict[str, float]]:
    kind = normalize_shape_kind((item.get("style") or {}).get("shape_kind"))
    points = normalize_shape_points(item.get("points"), kind)
    if kind == "freeform" and points and not any(_has_handles(point) for point in points):
        closed = shape_closed(item)
        for index in range(len(points)):
            _apply_tangent_handles(points, index, closed)
    item["points"] = points
    return points


def shape_closed(item: dict[str, Any]) -> bool:
    style = item.get("style") or {}
    kind = normalize_shape_kind(style.get("shape_kind"))
    if kind == "line":
        return bool(style.get("shape_closed"))
    if "shape_closed" in style:
        return bool(style.get("shape_closed"))
    return kind != "line"


def _abs_point(item: dict[str, Any], point: dict[str, float]) -> QtCore.QPointF:
    return QtCore.QPointF(
        float(item["x"]) + float(point["x"]) * float(item["w"]),
        float(item["y"]) + float(point["y"]) * float(item["h"]),
    )


def _handle_point(item: dict[str, Any], point: dict[str, float], prefix: str) -> QtCore.QPointF:
    origin = _abs_point(item, point)
    return QtCore.QPointF(
        origin.x() + float(point.get(f"{prefix}_x") or 0) * float(item["w"]),
        origin.y() + float(point.get(f"{prefix}_y") or 0) * float(item["h"]),
    )


def _has_handles(point: dict[str, float]) -> bool:
    return any(abs(float(point.get(key) or 0)) > 0.0005 for key in ("in_x", "in_y", "out_x", "out_y"))


def _apply_tangent_handles(points: list[dict[str, float]], index: int, closed: bool) -> None:
    """Place in/out handles at 1/3 of the adjacent segments so a rectangle stays straight but is editable."""
    count = len(points)
    if count < 2 or index < 0 or index >= count:
        return
    cur = points[index]
    if closed:
        prev = points[(index - 1) % count]
        nxt = points[(index + 1) % count]
    else:
        prev = points[index - 1] if index > 0 else None
        nxt = points[index + 1] if index + 1 < count else None
        if prev is None and nxt is not None:
            prev = {"x": cur["x"] - (nxt["x"] - cur["x"]), "y": cur["y"] - (nxt["y"] - cur["y"])}
        elif nxt is None and prev is not None:
            nxt = {"x": cur["x"] - (prev["x"] - cur["x"]), "y": cur["y"] - (prev["y"] - cur["y"])}
    if prev is None or nxt is None:
        return
    cur["in_x"] = (prev["x"] - cur["x"]) / 3.0
    cur["in_y"] = (prev["y"] - cur["y"]) / 3.0
    cur["out_x"] = (nxt["x"] - cur["x"]) / 3.0
    cur["out_y"] = (nxt["y"] - cur["y"]) / 3.0


def shape_path(item: dict[str, Any]) -> QtGui.QPainterPath:
    style = item.get("style") or {}
    kind = normalize_shape_kind(style.get("shape_kind"))
    rect = QtCore.QRectF(item["x"], item["y"], item["w"], item["h"])
    path = QtGui.QPainterPath()
    if kind == "rectangle":
        radius = float(style.get("corner_radius") or 0)
        if radius > 0:
            path.addRoundedRect(rect, radius, radius)
        else:
            path.addRect(rect)
        return path
    if kind == "circle":
        side = min(rect.width(), rect.height())
        path.addEllipse(QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side))
        return path
    points = ensure_shape_points(item)
    if len(points) < 2:
        path.addRect(rect)
        return path
    first = _abs_point(item, points[0])
    path.moveTo(first)
    count = len(points)
    last_index = count if shape_closed(item) else count - 1
    for i in range(last_index):
        current = points[i]
        nxt = points[(i + 1) % count]
        dest = _abs_point(item, nxt)
        if _has_handles(current) or _has_handles(nxt):
            path.cubicTo(_handle_point(item, current, "out"), _handle_point(item, nxt, "in"), dest)
        else:
            path.lineTo(dest)
    if shape_closed(item) and count >= 3:
        path.closeSubpath()
    return path


def scene_to_normalized(item: dict[str, Any], pos: QtCore.QPointF) -> tuple[float, float]:
    w = max(1.0, float(item.get("w") or 1))
    h = max(1.0, float(item.get("h") or 1))
    return (
        max(0.0, min(1.0, (pos.x() - float(item["x"])) / w)),
        max(0.0, min(1.0, (pos.y() - float(item["y"])) / h)),
    )


def closest_segment(item: dict[str, Any], pos: QtCore.QPointF) -> tuple[int, float]:
    points = ensure_shape_points(item)
    if len(points) < 2:
        return 0, 1e9
    best_i = 0
    best_d = 1e9
    count = len(points)
    steps = count if shape_closed(item) else count - 1
    for i in range(steps):
        a = _abs_point(item, points[i])
        b = _abs_point(item, points[(i + 1) % count])
        dist = _distance_to_segment(pos, a, b)
        if dist < best_d:
            best_d = dist
            best_i = i
    return best_i, best_d


def _distance_to_segment(pos: QtCore.QPointF, a: QtCore.QPointF, b: QtCore.QPointF) -> float:
    ax, ay = a.x(), a.y()
    bx, by = b.x(), b.y()
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length <= 1e-6:
        return QtCore.QLineF(pos, a).length()
    t = max(0.0, min(1.0, ((pos.x() - ax) * dx + (pos.y() - ay) * dy) / length))
    proj = QtCore.QPointF(ax + t * dx, ay + t * dy)
    return QtCore.QLineF(pos, proj).length()


def insert_shape_point(item: dict[str, Any], after_index: int, pos: QtCore.QPointF) -> int:
    points = ensure_shape_points(item)
    nx, ny = scene_to_normalized(item, pos)
    index = max(0, min(len(points), after_index + 1))
    points.insert(index, _point(nx, ny))
    if normalize_shape_kind((item.get("style") or {}).get("shape_kind")) == "freeform":
        _apply_tangent_handles(points, index, shape_closed(item))
    item["points"] = points
    return index


def remove_shape_point(item: dict[str, Any], index: int) -> bool:
    points = ensure_shape_points(item)
    kind = normalize_shape_kind((item.get("style") or {}).get("shape_kind"))
    minimum = 2 if kind == "line" else 3
    if index < 0 or index >= len(points) or len(points) <= minimum:
        return False
    points.pop(index)
    item["points"] = points
    return True
