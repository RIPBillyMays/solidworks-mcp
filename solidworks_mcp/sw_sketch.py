# Copyright 2026 JIALE LIU
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Modified for SOLIDWORKS 2017 support (fork).

"""Sketch creation, geometry, editing, relations, and dimensions.

Relations and dimensions are what turn a floating sketch into a driveable,
parametric one, so they are the centre of gravity of this module rather than an
afterthought.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from .sw_core import (
    active_document,
    sketch_point_objects,
    dispatch_array,
    empty_variant,
    dimension_dialog_suppressed,
    as_list,
    apply_selection,
    clear_selection,
    enumerate_sketch_segments,
    extension,
    feature_property,
    find_feature,
    flag_methods,
    invoke_no_arg,
    iter_feature_objects,
    latest_sketch,
    logger,
    rebuild,
    require_part,
    require_selection,
    resolve_plane_name,
    resolve_sketch,
    result,
    safe,
    SELECTION_SCHEMA,
    select_by_id,
    sketch_manager,
    sketch_names,
    sketch_segment_objects,
    tool,
    to_deg,
    to_m,
    mm_point,
    to_mm,
    to_rad,
    TRIM_CHOICES,
    value,
)


# swConstraintType_e.  ISketchRelationManager takes these codes and can be
# verified afterwards, unlike SketchAddConstraints, which accepts a magic
# string and silently ignores anything it does not recognise.
RELATIONS = {
    "horizontal": 4,
    "vertical": 5,
    "tangent": 6,
    "parallel": 7,
    "perpendicular": 8,
    "coincident": 9,
    "concentric": 10,
    "symmetric": 11,
    "midpoint": 12,
    "intersection": 13,
    "equal": 14,
    "fixed": 17,
    "collinear": 27,
    "coradial": 28,
}
RELATION_NAMES = {code: name for name, code in RELATIONS.items()}

DIMENSION_DIRECTIONS = {"right": 0, "up": 1, "left": 2, "down": 3}


def _segment_count(doc: Any) -> int:
    """How many segments the open sketch holds right now."""
    sketch = doc.SketchManager.ActiveSketch
    if sketch is None:
        return 0
    return len(as_list(safe(sketch, "GetSketchSegments")))


def _drawn(doc: Any, before: int, what: str) -> dict[str, Any]:
    """Report a drawing tool by what the sketch actually gained.

    The Create* APIs return arrays whose truthiness is not a reliable success
    signal under late binding, so count segments instead.
    """
    added = _segment_count(doc) - before
    if added <= 0:
        return result(False, f"SOLIDWORKS did not create {what}.")
    return result(True, f"Added {what} ({added} segments).", segments_added=added)


def _active_sketch(doc: Any) -> Any:
    sketch = doc.SketchManager.ActiveSketch
    if sketch is None:
        raise RuntimeError("No sketch is open. Call create_sketch or edit_sketch first.")
    return sketch


def _require_open_sketch() -> tuple[Any, Any]:
    _, doc = active_document()
    _active_sketch(doc)
    return doc, sketch_manager(doc)


# --------------------------------------------------------------------------
# Exact placement.  SketchManager.Create* runs with sketch inference and
# snapping active, so in a crowded sketch the new geometry silently snaps to
# nearby points (field finding #1: endpoints shifted ~1.2 mm, an arc centre
# (0.5, 0) snapped to (0, 0)).  AddToDB creates geometry straight in the
# database with no inference, and every drawing tool then reads the segment
# back and compares it with the request, so a shift is reported, not hidden.
# --------------------------------------------------------------------------

# 1 micrometre, in metres.
VERIFY_TOL_M = 1e-6


@contextmanager
def _sketch_db_mode(doc: Any) -> Iterator[None]:
    """Create sketch geometry without inference or snapping, then restore.

    Sets ``SketchManager.AddToDB`` and clears ``DisplayWhenAdded``; the previous
    values come back in ``finally`` even if a Create* call raises.  User
    preferences are not touched.
    """
    sketch_mgr = doc.SketchManager
    previous = {
        "AddToDB": safe(sketch_mgr, "AddToDB", False),
        "DisplayWhenAdded": safe(sketch_mgr, "DisplayWhenAdded", True),
    }
    try:
        sketch_mgr.AddToDB = True
        sketch_mgr.DisplayWhenAdded = False
        yield
    finally:
        for name, old in previous.items():
            try:
                setattr(sketch_mgr, name, bool(old))
            except Exception:
                logger.warning("Could not restore SketchManager.%s to %s.", name, old)
        try:
            invoke_no_arg(doc, "GraphicsRedraw2")
        except Exception:
            logger.info("Sketch geometry added; SOLIDWORKS declined an immediate graphics redraw.")


def _xy(point: Any) -> tuple[float, float]:
    """(x, y) in metres from a SOLIDWORKS point object or a plain sequence."""
    if hasattr(point, "X"):
        return float(point.X), float(point.Y)
    return float(point[0]), float(point[1])


def _read_point(segment: Any, member: str) -> tuple[float, float]:
    return _xy(value(segment, member))


def _mm2(point: tuple[float, float]) -> list[float]:
    return mm_point(point)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _points_differ(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) > VERIFY_TOL_M or abs(a[1] - b[1]) > VERIFY_TOL_M


def _mismatch(label: str, requested: Any, actual: Any, bad: list[str]) -> None:
    bad.append(f"{label}: requested {requested}, actual {actual}")


def _line_ends(segment: Any) -> tuple[tuple[float, float], tuple[float, float]]:
    """Endpoints of an ISketchLine, via the line-specific members (2017 compatible)."""
    return _read_point(segment, "GetStartPoint2"), _read_point(segment, "GetEndPoint2")


def _verify_line(
    segment: Any, start: tuple[float, float], end: tuple[float, float]
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    """Returns (actual, requested, problems); actual is None when unreadable."""
    requested = {"start_mm": _mm2(start), "end_mm": _mm2(end)}
    try:
        actual_start, actual_end = _line_ends(segment)
    except Exception:
        logger.info("Line created but its endpoints could not be read back.")
        return None, requested, []
    actual = {"start_mm": _mm2(actual_start), "end_mm": _mm2(actual_end)}
    bad: list[str] = []
    if _points_differ(actual_start, start):
        _mismatch("start", requested["start_mm"], actual["start_mm"], bad)
    if _points_differ(actual_end, end):
        _mismatch("end", requested["end_mm"], actual["end_mm"], bad)
    return actual, requested, bad


def _finish_verified(
    doc: Any,
    before: int,
    what: str,
    actual: dict[str, Any] | None,
    requested: dict[str, Any],
    bad: list[str],
) -> dict[str, Any]:
    """Combine the segment-count check with the read-back comparison."""
    drawn = _drawn(doc, before, what)
    if not drawn["ok"]:
        return drawn
    if bad:
        return result(
            False,
            f"SOLIDWORKS created {what} but not where requested ({'; '.join(bad)}). "
            "The geometry is in the sketch at the actual position; delete or fix it before continuing.",
            requested=requested,
            actual=actual,
            segments_added=drawn["data"]["segments_added"],
        )
    drawn["data"]["verified"] = actual is not None
    if actual is not None:
        drawn["data"]["actual"] = actual
    return drawn


def _verify_circle(
    segment: Any, center: tuple[float, float], radius: float
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    requested = {"center_mm": _mm2(center), "radius_mm": round(to_mm(radius), 6)}
    try:
        actual_center = _read_point(segment, "GetCenterPoint2")
        actual_radius = float(value(segment, "GetRadius"))
    except Exception:
        logger.info("Circle created but its centre/radius could not be read back.")
        return None, requested, []
    actual = {"center_mm": _mm2(actual_center), "radius_mm": round(to_mm(actual_radius), 6)}
    bad: list[str] = []
    if _points_differ(actual_center, center):
        _mismatch("centre", requested["center_mm"], actual["center_mm"], bad)
    if abs(actual_radius - radius) > VERIFY_TOL_M:
        _mismatch("radius", requested["radius_mm"], actual["radius_mm"], bad)
    return actual, requested, bad


def _verify_arc(
    segment: Any,
    center: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    direction: int = 1,
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    """Check a centre/start/end arc.  The end point is projected onto the radius.

    Live on 2017: a clockwise request keeps the requested start/end order and
    reports GetRotationDir = -1.  The sweep side is checked through
    GetRotationDir (direction of travel from the read-back start to the
    read-back end), which must equal the requested direction.  Swapped ends are
    still tolerated as a set match, with the expected rotation then inverted.
    """
    radius = _dist(center, start)
    span = _dist(center, end)
    if span > 0:
        end = (center[0] + (end[0] - center[0]) * radius / span, center[1] + (end[1] - center[1]) * radius / span)
    requested = {
        "center_mm": _mm2(center),
        "start_mm": _mm2(start),
        "end_mm": _mm2(end),
        "radius_mm": round(to_mm(radius), 6),
    }
    try:
        actual_center = _read_point(segment, "GetCenterPoint2")
        actual_start = _read_point(segment, "GetStartPoint2")
        actual_end = _read_point(segment, "GetEndPoint2")
        actual_radius = float(value(segment, "GetRadius"))
    except Exception:
        logger.info("Arc created but its geometry could not be read back.")
        return None, requested, []
    actual = {
        "center_mm": _mm2(actual_center),
        "start_mm": _mm2(actual_start),
        "end_mm": _mm2(actual_end),
        "radius_mm": round(to_mm(actual_radius), 6),
    }
    bad: list[str] = []
    if _points_differ(actual_center, center):
        _mismatch("centre", requested["center_mm"], actual["center_mm"], bad)
    if abs(actual_radius - radius) > VERIFY_TOL_M:
        _mismatch("radius", requested["radius_mm"], actual["radius_mm"], bad)
    in_order = not _points_differ(actual_start, start) and not _points_differ(actual_end, end)
    swapped = not _points_differ(actual_start, end) and not _points_differ(actual_end, start)
    if not (in_order or swapped):
        _mismatch("end points", [requested["start_mm"], requested["end_mm"]],
                  [actual["start_mm"], actual["end_mm"]], bad)
    else:
        try:
            rotation = int(value(segment, "GetRotationDir"))
        except Exception:
            rotation = 0  # unreadable: the sweep side cannot be checked
        if rotation in (1, -1):
            expected = direction if in_order else -direction
            actual["rotation_dir"] = rotation
            if rotation != expected:
                _mismatch("sweep", "counter-clockwise" if direction == 1 else "clockwise",
                          "the other side of the circle", bad)
    return actual, requested, bad


def _verify_3point_arc(
    segment: Any,
    first: tuple[float, float],
    second: tuple[float, float],
    through: tuple[float, float],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    """The two ends may come back in either order; the third point must lie on the arc's circle."""
    requested = {"end_points_mm": [_mm2(first), _mm2(second)], "through_mm": _mm2(through)}
    try:
        actual_center = _read_point(segment, "GetCenterPoint2")
        actual_start = _read_point(segment, "GetStartPoint2")
        actual_end = _read_point(segment, "GetEndPoint2")
        actual_radius = float(value(segment, "GetRadius"))
    except Exception:
        logger.info("3-point arc created but its geometry could not be read back.")
        return None, requested, []
    actual = {
        "end_points_mm": [_mm2(actual_start), _mm2(actual_end)],
        "center_mm": _mm2(actual_center),
        "radius_mm": round(to_mm(actual_radius), 6),
    }
    bad: list[str] = []
    straight = not _points_differ(actual_start, first) and not _points_differ(actual_end, second)
    swapped = not _points_differ(actual_start, second) and not _points_differ(actual_end, first)
    if not (straight or swapped):
        _mismatch("end points", requested["end_points_mm"], actual["end_points_mm"], bad)
    if abs(_dist(actual_center, through) - actual_radius) > VERIFY_TOL_M:
        _mismatch("through point", requested["through_mm"], "not on the created arc", bad)
    return actual, requested, bad


def _flat_segments(created: Any) -> list[Any]:
    """Flatten the (possibly nested) array a multi-segment Create* call returns."""
    flat: list[Any] = []
    for item in as_list(created):
        if isinstance(item, (list, tuple)):
            flat.extend(_flat_segments(item))
        elif item is not None:
            flat.append(item)
    return flat


def _line_segments(segments: Sequence[Any]) -> list[Any]:
    """Keep only line segments (swSketchLINE is 0).

    On 2017 CreatePolygon also returns its construction circle; counting it as
    a side or a corner gave a false mismatch.  An unreadable type is kept.
    """
    kept = []
    for segment in segments:
        seg_type = safe(segment, "GetType")
        try:
            is_line = seg_type is None or int(seg_type) == 0
        except (TypeError, ValueError):
            is_line = True  # unreadable: keep, and let the read-back decide
        if is_line:
            kept.append(segment)
    return kept


def _vertices_of(segments: Sequence[Any]) -> list[tuple[float, float]] | None:
    """Every line endpoint of the created segments, or None when any is unreadable."""
    points: list[tuple[float, float]] = []
    try:
        for segment in segments:
            points.extend(_line_ends(segment))
    except Exception:
        return None
    return points or None


def _verify_rectangle(
    segments: Sequence[Any], first: tuple[float, float], second: tuple[float, float]
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    low = (min(first[0], second[0]), min(first[1], second[1]))
    high = (max(first[0], second[0]), max(first[1], second[1]))
    requested = {"min_corner_mm": _mm2(low), "max_corner_mm": _mm2(high)}
    points = _vertices_of(_line_segments(segments))
    if points is None:
        logger.info("Rectangle created but its edges could not be read back.")
        return None, requested, []
    actual_low = (min(p[0] for p in points), min(p[1] for p in points))
    actual_high = (max(p[0] for p in points), max(p[1] for p in points))
    actual = {"min_corner_mm": _mm2(actual_low), "max_corner_mm": _mm2(actual_high)}
    bad: list[str] = []
    if _points_differ(actual_low, low):
        _mismatch("min corner", requested["min_corner_mm"], actual["min_corner_mm"], bad)
    if _points_differ(actual_high, high):
        _mismatch("max corner", requested["max_corner_mm"], actual["max_corner_mm"], bad)
    return actual, requested, bad


def _verify_polygon(
    segments: Sequence[Any],
    center: tuple[float, float],
    circumradius: float,
    sides: int,
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    """Centroid of the corners must be the centre; every corner sits at the corner radius."""
    requested = {"center_mm": _mm2(center), "circumradius_mm": round(to_mm(circumradius), 6), "sides": sides}
    segments = _line_segments(segments)
    points = _vertices_of(segments)
    if points is None:
        logger.info("Polygon created but its edges could not be read back.")
        return None, requested, []
    # Edges share corners, so de-duplicate the endpoints (edge order is not guaranteed).
    corners: list[tuple[float, float]] = []
    for candidate in points:
        if not any(not _points_differ(candidate, known) for known in corners):
            corners.append(candidate)
    centroid = (sum(p[0] for p in corners) / len(corners), sum(p[1] for p in corners) / len(corners))
    radii = [_dist(center, corner) for corner in corners]
    actual = {
        "center_mm": _mm2(centroid),
        "circumradius_mm": round(to_mm(max(radii)), 6),
        "sides": len(segments),
    }
    bad: list[str] = []
    if _points_differ(centroid, center):
        _mismatch("centre", requested["center_mm"], actual["center_mm"], bad)
    if any(abs(r - circumradius) > VERIFY_TOL_M for r in radii):
        _mismatch("circumradius", requested["circumradius_mm"], [round(to_mm(r), 6) for r in radii], bad)
    if len(segments) != sides:
        _mismatch("sides", sides, len(segments), bad)
    return actual, requested, bad


# --------------------------------------------------------------------------
# Sketch lifecycle
# --------------------------------------------------------------------------


@tool(
    "create_sketch",
    "Open a new 2D sketch on a reference plane or on a planar face of the model. "
    "Pass plane_name (exact localized name from list_reference_planes) or plane=front/top/right, "
    "or face_index from list_faces to sketch directly on a face.",
    {
        "plane": {"type": "string", "enum": ["front", "top", "right"], "default": "front"},
        "plane_name": {"type": "string", "description": "Exact localized plane name from list_reference_planes."},
        "face_index": {"type": "integer", "description": "Sketch on this face instead of a reference plane."},
        "name": {"type": "string", "description": "Rename the sketch once created."},
    },
)
def create_sketch(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    face_index = args.get("face_index")
    if face_index is not None:
        require_selection(doc, {"faces": [int(face_index)]})
        target = f"face {face_index}"
    else:
        plane_name = str(args.get("plane_name") or args.get("plane") or "front")
        resolved = resolve_plane_name(doc, plane_name)
        clear_selection(doc)
        if not select_by_id(doc, resolved, "PLANE"):
            return result(False, f"Could not select reference plane '{resolved}'.")
        target = resolved

    sketch_manager(doc).InsertSketch(True)
    if doc.SketchManager.ActiveSketch is None:
        return result(False, f"SOLIDWORKS did not open a sketch on {target}.")

    name = args.get("name")
    created = ""
    try:
        created, feature = latest_sketch(doc)
        if name:
            feature.Name = str(name)
            created = str(name)
    except Exception:
        logger.info("Sketch opened but its feature could not be resolved for renaming.")
    return result(True, f"Opened a sketch on {target}.", sketch=created, target=target)


@tool(
    "edit_sketch",
    "Reopen an existing sketch for editing by name.",
    {"sketch_name": {"type": "string"}},
    ["sketch_name"],
)
def edit_sketch(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    name, _ = resolve_sketch(doc, str(args["sketch_name"]))
    clear_selection(doc)
    if not select_by_id(doc, name, "SKETCH"):
        return result(False, f"Could not select sketch '{name}'.")
    sketch_manager(doc).InsertSketch(True)
    return result(True, f"Reopened sketch '{name}' for editing.", sketch=name)


@tool("close_sketch", "Exit the open sketch without creating a feature.", {})
def close_sketch(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    if doc.SketchManager.ActiveSketch is None:
        return result(False, "No sketch is open.")
    name = ""
    try:
        name, _ = latest_sketch(doc)
    except Exception:
        pass
    sketch_manager(doc).InsertSketch(True)
    return result(True, "Closed the open sketch.", sketch=name)


@tool("list_sketches", "Read-only: list every sketch feature in the active document.", {})
def list_sketches(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    open_sketch = doc.SketchManager.ActiveSketch is not None
    return result(True, "Read sketches.", sketches=sketch_names(doc), sketch_open=open_sketch)


@tool(
    "list_sketch_segments",
    "Read-only: list the segments of the open sketch (or a named one) with the indices used by "
    "add_relation, add_dimension, and selection specs.",
    {"sketch_name": {"type": "string", "description": "Defaults to the currently open sketch."}},
)
def list_sketch_segments(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    name, segments = enumerate_sketch_segments(doc, args.get("sketch_name") or None)
    return result(True, f"Read {len(segments)} sketch segments.", sketch=name, segments=segments)


# --------------------------------------------------------------------------
# Sketch geometry.  All coordinates are millimetres in sketch space.
# --------------------------------------------------------------------------

_XY = {"x_mm": {"type": "number"}, "y_mm": {"type": "number"}}


@tool(
    "draw_line",
    "Add a line to the open sketch. Coordinates are millimetres in sketch space and are exact: "
    "the line is created without sketch inference or snapping, then its endpoints are read back "
    "and compared with the request; ok is false (with requested and actual in mm) on any mismatch.",
    {
        "x1_mm": {"type": "number"}, "y1_mm": {"type": "number"},
        "x2_mm": {"type": "number"}, "y2_mm": {"type": "number"},
        "construction": {"type": "boolean", "default": False},
    },
    ["x1_mm", "y1_mm", "x2_mm", "y2_mm"],
)
def draw_line(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    start = (to_m(args["x1_mm"]), to_m(args["y1_mm"]))
    end = (to_m(args["x2_mm"]), to_m(args["y2_mm"]))
    before = _segment_count(doc)
    with _sketch_db_mode(doc):
        segment = manager.CreateLine(start[0], start[1], 0.0, end[0], end[1], 0.0)
        if segment is not None and bool(args.get("construction", False)):
            segment.ConstructionGeometry = True
        actual, requested, bad = _verify_line(segment, start, end) if segment is not None else (None, {}, [])
    return _finish_verified(doc, before, "a line", actual, requested, bad)


@tool(
    "draw_polyline",
    "Add a chain of connected lines through an ordered list of points (optionally closed back to the "
    "first). Millimetres in sketch space; coordinates are exact (created without inference or "
    "snapping, so dense or coincident geometry cannot shift them). Every vertex is read back and "
    "verified; ok is false with the offending vertices (requested/actual in mm) on any mismatch. "
    "Prefer this over many draw_line calls for outlines such as stars or stepped profiles.",
    {
        "points": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "properties": {"x_mm": {"type": "number"}, "y_mm": {"type": "number"}},
                "required": ["x_mm", "y_mm"],
            },
        },
        "closed": {"type": "boolean", "default": False},
        "construction": {"type": "boolean", "default": False},
    },
    ["points"],
)
def draw_polyline(args: dict[str, Any]) -> dict[str, Any]:
    raw_points = args.get("points") or []
    closed = bool(args.get("closed", False))
    vertices: list[tuple[float, float]] = []
    for index, point in enumerate(raw_points):
        try:
            vertices.append((to_m(point["x_mm"]), to_m(point["y_mm"])))
        except (KeyError, TypeError, ValueError):
            return result(False, f"Point {index} needs numeric x_mm and y_mm.")
    if len(vertices) < 2:
        return result(False, "draw_polyline needs at least 2 points.")
    if closed and len(vertices) < 3:
        return result(False, "A closed polyline needs at least 3 points.")
    pairs = list(zip(vertices, vertices[1:]))
    if closed:
        pairs.append((vertices[-1], vertices[0]))
    for index, (start, end) in enumerate(pairs):
        if _dist(start, end) < VERIFY_TOL_M:
            return result(False, f"Segment {index} has zero length (its two points coincide); nothing was drawn.")

    doc, manager = _require_open_sketch()
    construction = bool(args.get("construction", False))
    before = _segment_count(doc)
    segments: list[dict[str, Any]] = []
    bad_vertices: dict[int, dict[str, Any]] = {}
    unreadable = 0
    with _sketch_db_mode(doc):
        for index, (start, end) in enumerate(pairs):
            segment = manager.CreateLine(start[0], start[1], 0.0, end[0], end[1], 0.0)
            if segment is None:
                segments.append({"index": index, "created": False})
                continue
            if construction:
                segment.ConstructionGeometry = True
            actual, _, bad = _verify_line(segment, start, end)
            entry: dict[str, Any] = {"index": index, "created": True}
            if actual is None:
                unreadable += 1
            else:
                entry.update(actual)
            segments.append(entry)
            if bad and actual is not None:
                start_vertex = index
                end_vertex = (index + 1) % len(vertices)
                actual_start, actual_end = _line_ends(segment)
                if _points_differ(actual_start, start):
                    bad_vertices[start_vertex] = {
                        "vertex": start_vertex, "requested_mm": _mm2(start), "actual_mm": actual["start_mm"],
                    }
                if _points_differ(actual_end, end):
                    bad_vertices[end_vertex] = {
                        "vertex": end_vertex, "requested_mm": _mm2(end), "actual_mm": actual["end_mm"],
                    }

    added = _segment_count(doc) - before
    missing = [entry["index"] for entry in segments if not entry["created"]]
    if missing or added < len(pairs):
        return result(
            False,
            f"SOLIDWORKS created {max(added, 0)} of {len(pairs)} segments (segments {missing} were not "
            "created); the partial polyline remains in the sketch.",
            segments=segments, segments_added=max(added, 0), requested_segments=len(pairs),
        )
    if bad_vertices:
        ordered = [bad_vertices[key] for key in sorted(bad_vertices)]
        return result(
            False,
            f"{len(ordered)} polyline vertices are not where requested: "
            + "; ".join(f"vertex {v['vertex']} requested {v['requested_mm']}, actual {v['actual_mm']}" for v in ordered)
            + ". The segments remain in the sketch at their actual positions.",
            bad_vertices=ordered, segments=segments, segments_added=added,
        )
    return result(
        True,
        f"Added a {'closed ' if closed else ''}polyline ({len(pairs)} segments).",
        segments=segments, segments_added=added, closed=closed, verified=unreadable == 0,
    )


@tool(
    "draw_centerline",
    "Add a construction centerline to the open sketch, for revolve axes and symmetry. Millimetres. "
    "Created without snapping; endpoints are read back and verified (ok false with requested/actual on mismatch).",
    {
        "x1_mm": {"type": "number"}, "y1_mm": {"type": "number"},
        "x2_mm": {"type": "number"}, "y2_mm": {"type": "number"},
    },
    ["x1_mm", "y1_mm", "x2_mm", "y2_mm"],
)
def draw_centerline(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    start = (to_m(args["x1_mm"]), to_m(args["y1_mm"]))
    end = (to_m(args["x2_mm"]), to_m(args["y2_mm"]))
    before = _segment_count(doc)
    with _sketch_db_mode(doc):
        segment = manager.CreateCenterLine(start[0], start[1], 0.0, end[0], end[1], 0.0)
        actual, requested, bad = _verify_line(segment, start, end) if segment is not None else (None, {}, [])
    return _finish_verified(doc, before, "a centerline", actual, requested, bad)


@tool(
    "draw_circle",
    "Add a circle to the open sketch. Centre and radius are millimetres and are exact (no snapping); "
    "centre and radius are read back and verified, ok false with requested/actual on mismatch.",
    {
        "x_mm": {"type": "number"}, "y_mm": {"type": "number"},
        "radius_mm": {"type": "number", "exclusiveMinimum": 0},
        "construction": {"type": "boolean", "default": False},
    },
    ["x_mm", "y_mm", "radius_mm"],
)
def draw_circle(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    center = (to_m(args["x_mm"]), to_m(args["y_mm"]))
    radius = to_m(args["radius_mm"])
    before = _segment_count(doc)
    with _sketch_db_mode(doc):
        segment = manager.CreateCircleByRadius(center[0], center[1], 0.0, radius)
        if segment is not None and bool(args.get("construction", False)):
            segment.ConstructionGeometry = True
        actual, requested, bad = (None, {}, [])
        if segment is not None:
            actual, requested, bad = _verify_circle(segment, center, radius)
    return _finish_verified(doc, before, "a circle", actual, requested, bad)


@tool(
    "draw_rectangle",
    "Add a corner rectangle to the open sketch. Both corners are millimetres and are exact (no snapping); "
    "the rectangle's extent is read back and verified, ok false with requested/actual on mismatch.",
    {
        "x1_mm": {"type": "number"}, "y1_mm": {"type": "number"},
        "x2_mm": {"type": "number"}, "y2_mm": {"type": "number"},
    },
    ["x1_mm", "y1_mm", "x2_mm", "y2_mm"],
)
def draw_rectangle(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    first = (to_m(args["x1_mm"]), to_m(args["y1_mm"]))
    second = (to_m(args["x2_mm"]), to_m(args["y2_mm"]))
    before = _segment_count(doc)
    with _sketch_db_mode(doc):
        created = manager.CreateCornerRectangle(first[0], first[1], 0.0, second[0], second[1], 0.0)
        actual, requested, bad = _verify_rectangle(_flat_segments(created), first, second)
    return _finish_verified(doc, before, "a rectangle", actual, requested, bad)


@tool(
    "draw_arc",
    "Add an arc defined by centre, start point, and end point. direction 1 is counter-clockwise, "
    "-1 is clockwise. The start point sets the radius; the end point is projected onto it. Millimetres. "
    "Created without snapping; centre, radius and endpoints are read back and verified, ok false with "
    "requested/actual on mismatch.",
    {
        "center_x_mm": {"type": "number"}, "center_y_mm": {"type": "number"},
        "start_x_mm": {"type": "number"}, "start_y_mm": {"type": "number"},
        "end_x_mm": {"type": "number"}, "end_y_mm": {"type": "number"},
        "direction": {"type": "integer", "enum": [1, -1], "default": 1},
    },
    ["center_x_mm", "center_y_mm", "start_x_mm", "start_y_mm", "end_x_mm", "end_y_mm"],
)
def draw_arc(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    center = (to_m(args["center_x_mm"]), to_m(args["center_y_mm"]))
    start = (to_m(args["start_x_mm"]), to_m(args["start_y_mm"]))
    end = (to_m(args["end_x_mm"]), to_m(args["end_y_mm"]))
    before = _segment_count(doc)
    with _sketch_db_mode(doc):
        segment = manager.CreateArc(
            center[0], center[1], 0.0, start[0], start[1], 0.0, end[0], end[1], 0.0,
            int(args.get("direction", 1)),
        )
        actual, requested, bad = (None, {}, [])
        if segment is not None:
            actual, requested, bad = _verify_arc(segment, center, start, end, int(args.get("direction", 1)))
    return _finish_verified(doc, before, "an arc", actual, requested, bad)


@tool(
    "draw_3point_arc",
    "Add an arc through three points: start, end, and a point on the arc. Millimetres. "
    "Created without snapping; end points and the through point are read back and verified, ok false "
    "with requested/actual on mismatch.",
    {
        "x1_mm": {"type": "number"}, "y1_mm": {"type": "number"},
        "x2_mm": {"type": "number"}, "y2_mm": {"type": "number"},
        "x3_mm": {"type": "number"}, "y3_mm": {"type": "number"},
    },
    ["x1_mm", "y1_mm", "x2_mm", "y2_mm", "x3_mm", "y3_mm"],
)
def draw_3point_arc(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    first = (to_m(args["x1_mm"]), to_m(args["y1_mm"]))
    second = (to_m(args["x2_mm"]), to_m(args["y2_mm"]))
    through = (to_m(args["x3_mm"]), to_m(args["y3_mm"]))
    before = _segment_count(doc)
    with _sketch_db_mode(doc):
        segment = manager.Create3PointArc(
            first[0], first[1], 0.0, second[0], second[1], 0.0, through[0], through[1], 0.0,
        )
        actual, requested, bad = (None, {}, [])
        if segment is not None:
            actual, requested, bad = _verify_3point_arc(segment, first, second, through)
    return _finish_verified(doc, before, "a 3-point arc", actual, requested, bad)


@tool(
    "draw_ellipse",
    "Add an ellipse from its centre, a major-axis point, and a minor-axis point. Millimetres.",
    {
        "center_x_mm": {"type": "number"}, "center_y_mm": {"type": "number"},
        "major_x_mm": {"type": "number"}, "major_y_mm": {"type": "number"},
        "minor_x_mm": {"type": "number"}, "minor_y_mm": {"type": "number"},
    },
    ["center_x_mm", "center_y_mm", "major_x_mm", "major_y_mm", "minor_x_mm", "minor_y_mm"],
)
def draw_ellipse(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    before = _segment_count(doc)
    manager.CreateEllipse(
        to_m(args["center_x_mm"]), to_m(args["center_y_mm"]), 0.0,
        to_m(args["major_x_mm"]), to_m(args["major_y_mm"]), 0.0,
        to_m(args["minor_x_mm"]), to_m(args["minor_y_mm"]), 0.0,
    )
    return _drawn(doc, before, "an ellipse")


@tool(
    "draw_polygon",
    "Add a regular polygon from its centre and a point that sets the radius. Millimetres. The radius is the "
    "distance from the centre to the point: the corner radius when inscribed (default), the apothem "
    "(centre to edge midpoint) when circumscribed. A corner is always placed in the direction of the point "
    "(the circumscribed corner radius is computed as apothem / cos(pi/sides)). Created without snapping; "
    "centre and corner radius are read back and verified, ok false with requested/actual on mismatch.",
    {
        "center_x_mm": {"type": "number"}, "center_y_mm": {"type": "number"},
        "point_x_mm": {"type": "number"}, "point_y_mm": {"type": "number"},
        "sides": {"type": "integer", "minimum": 3, "maximum": 100, "default": 6},
        "inscribed": {"type": "boolean", "default": True},
    },
    ["center_x_mm", "center_y_mm", "point_x_mm", "point_y_mm"],
)
def draw_polygon(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    center = (to_m(args["center_x_mm"]), to_m(args["center_y_mm"]))
    point = (to_m(args["point_x_mm"]), to_m(args["point_y_mm"]))
    sides = int(args.get("sides", 6))
    inscribed = bool(args.get("inscribed", True))
    # 2017 ignores the inscribed flag and always puts a corner at the given
    # point, so compute that corner ourselves and always pass inscribed=True.
    reach = _dist(center, point)
    corner_radius = reach if inscribed else reach / math.cos(math.pi / sides)
    scale = corner_radius / reach if reach > 0 else 1.0
    corner = (center[0] + (point[0] - center[0]) * scale, center[1] + (point[1] - center[1]) * scale)
    before = _segment_count(doc)
    with _sketch_db_mode(doc):
        created = manager.CreatePolygon(
            center[0], center[1], 0.0, corner[0], corner[1], 0.0, sides, True,
        )
        actual, requested, bad = _verify_polygon(_flat_segments(created), center, corner_radius, sides)
    return _finish_verified(doc, before, "a polygon", actual, requested, bad)


@tool(
    "draw_slot",
    "Add a straight slot from two centre points and a width. length_type center_center measures "
    "between arc centres; full_length measures overall. Millimetres.",
    {
        "x1_mm": {"type": "number"}, "y1_mm": {"type": "number"},
        "x2_mm": {"type": "number"}, "y2_mm": {"type": "number"},
        "width_mm": {"type": "number", "exclusiveMinimum": 0},
        "length_type": {"type": "string", "enum": ["center_center", "full_length"], "default": "center_center"},
        "add_dimensions": {"type": "boolean", "default": False},
    },
    ["x1_mm", "y1_mm", "x2_mm", "y2_mm", "width_mm"],
)
def draw_slot(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    length_type = 0 if str(args.get("length_type", "center_center")) == "center_center" else 1
    before = _segment_count(doc)
    manager.CreateSketchSlot(
        0,  # swSketchSlotCreationType_line
        length_type,
        to_m(args["width_mm"]),
        to_m(args["x1_mm"]), to_m(args["y1_mm"]), 0.0,
        to_m(args["x2_mm"]), to_m(args["y2_mm"]), 0.0,
        0.0, 0.0, 0.0,
        1,  # arc direction, unused for a straight slot
        bool(args.get("add_dimensions", False)),
    )
    return _drawn(doc, before, "a slot")


@tool(
    "draw_point",
    "Add a sketch point, useful as a pierce/coincident reference. Millimetres.",
    dict(_XY),
    ["x_mm", "y_mm"],
)
def draw_point(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    point = manager.CreatePoint(to_m(args["x_mm"]), to_m(args["y_mm"]), 0.0)
    return result(bool(point), "Added a sketch point." if point else "SOLIDWORKS did not create the point.")


@tool(
    "draw_spline",
    "Add a spline through an ordered list of points. Millimetres.",
    {
        "points": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "properties": {"x_mm": {"type": "number"}, "y_mm": {"type": "number"}},
                "required": ["x_mm", "y_mm"],
            },
        }
    },
    ["points"],
)
def draw_spline(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    flat: list[float] = []
    for point in args["points"]:
        flat.extend([to_m(point["x_mm"]), to_m(point["y_mm"]), 0.0])
    from .sw_core import double_array

    before = _segment_count(doc)
    manager.CreateSpline(double_array(flat))
    return _drawn(doc, before, "a spline")


# --------------------------------------------------------------------------
# Sketch editing
# --------------------------------------------------------------------------


@tool(
    "sketch_fillet",
    "Round the corners between the selected sketch segments. Select two segments (or a shared "
    "endpoint) via selection, then give the radius in millimetres.",
    {
        "radius_mm": {"type": "number", "exclusiveMinimum": 0},
        "selection": SELECTION_SCHEMA,
        "keep_constraints": {"type": "boolean", "default": True},
    },
    ["radius_mm", "selection"],
)
def sketch_fillet(args: dict[str, Any]) -> dict[str, Any]:
    doc, _ = _require_open_sketch()
    require_selection(doc, args["selection"])
    ok = bool(doc.SketchFillet2(to_m(args["radius_mm"]), 1 if args.get("keep_constraints", True) else 0))
    clear_selection(doc)
    return result(ok, "Applied a sketch fillet." if ok else "SOLIDWORKS did not apply the sketch fillet.")


@tool(
    "sketch_chamfer",
    "Chamfer the corner between two selected sketch segments. Millimetres and degrees.",
    {
        "distance_mm": {"type": "number", "exclusiveMinimum": 0},
        "angle_deg": {"type": "number", "default": 45},
        "mode": {"type": "string", "enum": ["distance_angle", "distance_distance", "equal_distance"], "default": "equal_distance"},
        "second_distance_mm": {"type": "number", "description": "Only used by distance_distance."},
        "selection": SELECTION_SCHEMA,
    },
    ["distance_mm", "selection"],
)
def sketch_chamfer(args: dict[str, Any]) -> dict[str, Any]:
    doc, _ = _require_open_sketch()
    require_selection(doc, args["selection"])
    mode = str(args.get("mode", "equal_distance"))
    option = {"distance_angle": 0, "distance_distance": 1, "equal_distance": 2}[mode]
    if mode == "distance_angle":
        first, second = to_rad(args.get("angle_deg", 45)), to_m(args["distance_mm"])
    elif mode == "distance_distance":
        first = to_m(args.get("second_distance_mm", args["distance_mm"]))
        second = to_m(args["distance_mm"])
    else:
        first, second = to_m(args["distance_mm"]), to_m(args["distance_mm"])
    doc.SketchChamfer(first, second, option)
    clear_selection(doc)
    return result(True, "Applied a sketch chamfer.")


def _sketch_shape(doc: Any) -> tuple[int, float]:
    """A cheap fingerprint of the open sketch: segment count and total length."""
    sketch = doc.SketchManager.ActiveSketch
    if sketch is None:
        return (0, 0.0)
    segments = as_list(safe(sketch, "GetSketchSegments"))
    total = 0.0
    for segment in segments:
        try:
            total += float(value(segment, "GetLength"))
        except Exception:
            pass
    return (len(segments), round(total, 9))


@tool(
    "sketch_trim",
    "Trim sketch geometry. Put the segment to trim in selection, then give a point on the piece "
    "you want removed; SOLIDWORKS cuts it back to the nearest intersection. Millimetres.",
    {
        "x_mm": {"type": "number"}, "y_mm": {"type": "number"},
        "selection": SELECTION_SCHEMA,
        "mode": {"type": "string", "enum": list(TRIM_CHOICES), "default": "closest"},
    },
    ["x_mm", "y_mm", "selection"],
)
def sketch_trim(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    option = TRIM_CHOICES[str(args.get("mode", "closest"))]
    # SketchTrim acts on the current selection. With none it does nothing, and
    # with a stale one left by an earlier tool it silently trims the wrong
    # entity, so the selection is established here every time.
    clear_selection(doc)
    if not args.get("selection"):
        return result(
            False,
            "sketch_trim needs the segment to trim in selection; without one SOLIDWORKS "
            "either does nothing or trims whatever happened to be selected before.",
        )
    require_selection(doc, args["selection"])
    before = _sketch_shape(doc)
    # SketchTrim reports False even when it succeeds, so judge by the sketch.
    manager.SketchTrim(option, to_m(args["x_mm"]), to_m(args["y_mm"]), 0.0)
    after = _sketch_shape(doc)
    clear_selection(doc)
    if after == before:
        return result(
            False,
            "Nothing was trimmed. Give a point that lies on the piece you want gone, on the "
            "segment named in selection.",
        )
    return result(
        True,
        f"Trimmed the sketch ({before[0]} segments to {after[0]}).",
        segments_before=before[0],
        segments_after=after[0],
    )


@tool(
    "sketch_offset",
    "Offset the selected sketch entities by a distance in millimetres.",
    {
        "distance_mm": {"type": "number"},
        "selection": SELECTION_SCHEMA,
        "both_directions": {"type": "boolean", "default": False},
        "chain": {"type": "boolean", "default": True},
    },
    ["distance_mm", "selection"],
)
def sketch_offset(args: dict[str, Any]) -> dict[str, Any]:
    doc, _ = _require_open_sketch()
    require_selection(doc, args["selection"])
    ok = bool(
        doc.SketchOffset2(
            to_m(args["distance_mm"]),
            bool(args.get("both_directions", False)),
            bool(args.get("chain", True)),
        )
    )
    clear_selection(doc)
    return result(ok, "Offset the sketch entities." if ok else "SOLIDWORKS did not offset the selection.")


@tool(
    "sketch_mirror",
    "Mirror sketch entities about a centerline. Put the entities to mirror in selection and the "
    "centerline index in mirror_segment.",
    {
        "selection": SELECTION_SCHEMA,
        "mirror_segment": {"type": "integer", "description": "Index of the centerline segment from list_sketch_segments."},
    },
    ["selection", "mirror_segment"],
)
def sketch_mirror(args: dict[str, Any]) -> dict[str, Any]:
    doc, _ = _require_open_sketch()
    require_selection(doc, args["selection"], mark=0)
    segments = sketch_segment_objects(doc, None)
    index = int(args["mirror_segment"])
    if not 0 <= index < len(segments):
        return result(False, f"mirror_segment {index} is out of range (0..{len(segments) - 1}).")
    from .sw_core import select_object

    if not select_object(doc, segments[index], mark=0, append=True):
        return result(False, "Could not add the mirror centerline to the selection.")
    doc.SketchMirror()
    clear_selection(doc)
    return result(True, "Mirrored the sketch entities.")


@tool(
    "convert_entities",
    "Project the selected model edges or a face's loops onto the open sketch (Convert Entities).",
    {
        "selection": SELECTION_SCHEMA,
        "chain": {"type": "boolean", "default": True},
        "inner_loops": {"type": "boolean", "default": False},
    },
    ["selection"],
)
def convert_entities(args: dict[str, Any]) -> dict[str, Any]:
    doc, manager = _require_open_sketch()
    require_selection(doc, args["selection"])
    ok = bool(manager.SketchUseEdge3(bool(args.get("chain", True)), bool(args.get("inner_loops", False))))
    return result(ok, "Converted the selected entities into the sketch." if ok else "SOLIDWORKS did not convert the selection.")


@tool(
    "set_construction_geometry",
    "Toggle the selected sketch segments between normal and construction geometry.",
    {"selection": SELECTION_SCHEMA, "construction": {"type": "boolean", "default": True}},
    ["selection"],
)
def set_construction_geometry(args: dict[str, Any]) -> dict[str, Any]:
    doc, _ = _require_open_sketch()
    spec = dict(args["selection"])
    indices = [int(i) for i in spec.get("sketch_segments", [])]
    if not indices:
        return result(False, "Pass sketch_segments indices in the selection.")
    segments = sketch_segment_objects(doc, spec.get("sketch_name"))
    flag = bool(args.get("construction", True))
    changed = 0
    for index in indices:
        if not 0 <= index < len(segments):
            return result(False, f"Sketch segment index {index} is out of range (0..{len(segments) - 1}).")
        segments[index].ConstructionGeometry = flag
        changed += 1
    return result(True, f"Set construction={flag} on {changed} segments.", changed=changed)


# --------------------------------------------------------------------------
# Relations and dimensions
# --------------------------------------------------------------------------


def _relation_entities(doc: Any, spec: dict[str, Any]) -> list[Any]:
    """Resolve a selection spec to the sketch objects AddRelation wants."""
    sketch_name = spec.get("sketch_name")
    entities: list[Any] = []
    if spec.get("sketch_segments"):
        segments = sketch_segment_objects(doc, sketch_name)
        for raw in spec["sketch_segments"]:
            index = int(raw)
            if not 0 <= index < len(segments):
                raise RuntimeError(f"Sketch segment index {index} is out of range (0..{len(segments) - 1}).")
            entities.append(segments[index])
    if spec.get("sketch_points"):
        points = sketch_point_objects(doc, sketch_name)
        for raw in spec["sketch_points"]:
            index = int(raw)
            if not 0 <= index < len(points):
                raise RuntimeError(f"Sketch point index {index} is out of range (0..{len(points) - 1}).")
            entities.append(points[index])
    return entities


@tool(
    "add_relation",
    "Add a geometric relation between the selected sketch entities. This is what makes a sketch "
    "fully defined and driveable, so add relations before dimensions. Select the entities via "
    "selection (sketch_segments / sketch_points), then name the relation.",
    {
        "relation": {"type": "string", "enum": sorted(RELATIONS), "description": "Geometric relation to add."},
        "selection": SELECTION_SCHEMA,
    },
    ["relation", "selection"],
)
def add_relation(args: dict[str, Any]) -> dict[str, Any]:
    doc, _ = _require_open_sketch()
    relation = str(args["relation"])
    code = RELATIONS[relation]
    sketch = doc.SketchManager.ActiveSketch
    manager = value(sketch, "RelationManager")
    flag_methods(manager, "AddRelation", "GetRelationsCount", "GetAllowedRelations")

    entities = _relation_entities(doc, args["selection"])
    if not entities:
        raise RuntimeError(
            "add_relation needs sketch_segments or sketch_points in the selection. "
            "Call list_sketch_segments to see the indices."
        )

    before = int(manager.GetRelationsCount(0))
    status_before = _sketch_status(doc)
    payload = dispatch_array(entities)
    try:
        manager.AddRelation(payload, code)
    except Exception as exc:
        clear_selection(doc)
        return result(False, f"SOLIDWORKS rejected the '{relation}' relation: {exc}", entities=len(entities))

    added = int(manager.GetRelationsCount(0)) - before
    clear_selection(doc)
    if added <= 0:
        # SOLIDWORKS adds nothing rather than complaining when a relation does
        # not apply, so say which ones would have.
        allowed: list[str] = []
        try:
            allowed = sorted(
                RELATION_NAMES.get(int(c), f"code_{int(c)}")
                for c in as_list(manager.GetAllowedRelations(payload))
            )
        except Exception:
            pass
        return result(
            False,
            f"SOLIDWORKS did not add a {relation} relation to that selection.",
            entities=len(entities),
            allowed_relations=allowed,
        )
    status = _sketch_status(doc)
    if status in {"over_defined", "no_solution"} and status != status_before:
        # The relation went in, but the sketch can no longer solve, so the
        # geometry will not have moved. Say so instead of reporting a clean win.
        return result(
            False,
            f"The {relation} relation was added but left the sketch {status}, so the geometry did "
            "not move. Remove a conflicting relation or dimension first.",
            entities=len(entities),
            sketch_status=status,
            sketch_status_before=status_before,
        )
    return result(
        True,
        f"Added a {relation} relation across {len(entities)} entities.",
        entities=len(entities),
        sketch_status=status,
    )


def _sketch_status(doc: Any) -> str:
    """Report whether the open sketch is under/fully/over defined."""
    try:
        sketch = doc.SketchManager.ActiveSketch
        if sketch is None:
            return "closed"
        code = int(value(sketch, "GetConstrainedStatus"))
    except Exception:
        return "unknown"
    # swConstrainedStatus_e is 1-based: 1 unknown, 2 under, 3 fully, 4 over.
    return {
        1: "unknown", 2: "under_defined", 3: "fully_defined",
        4: "over_defined", 5: "no_solution", 6: "invalid_solution",
        7: "autosolve_off",
    }.get(code, f"status_{code}")


_DIMENSION_METHODS = {
    "auto": "AddDimension2",
    "horizontal": "AddHorizontalDimension2",
    "vertical": "AddVerticalDimension2",
    "radius": "AddRadialDimension2",
    "diameter": "AddDiameterDimension2",
}


@tool(
    "add_dimension",
    "Add a driving dimension to the selected sketch entities and set its value. Select one entity "
    "(length/radius) or two (distance/angle) via selection. value_mm drives linear dimensions; "
    "value_deg drives angular ones. place_*_mm is where the dimension text sits (millimetres). "
    "Use kind to force a horizontal, vertical, radius, or diameter dimension instead of letting "
    "SOLIDWORKS infer one.",
    {
        "selection": SELECTION_SCHEMA,
        "value_mm": {"type": "number", "description": "Target value for a linear dimension, in millimetres."},
        "value_deg": {"type": "number", "description": "Target value for an angular dimension, in degrees."},
        "kind": {"type": "string", "enum": sorted(_DIMENSION_METHODS), "default": "auto"},
        "place_x_mm": {"type": "number", "default": 0},
        "place_y_mm": {"type": "number", "default": 0},
        "place_z_mm": {"type": "number", "default": 0},
        "name": {"type": "string", "description": "Rename the dimension so equations can reference it."},
    },
    ["selection"],
)
def add_dimension(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = active_document()
    count = require_selection(doc, args["selection"])
    member = _DIMENSION_METHODS[str(args.get("kind", "auto"))]
    flag_methods(doc, member)

    # ModelDoc2.AddDimension2 rather than ModelDocExtension.AddDimension: the
    # latter reproducibly crashes SOLIDWORKS 2026 on a sketch selection.
    with dimension_dialog_suppressed(app):
        display = getattr(doc, member)(
            to_m(args.get("place_x_mm", 0)),
            to_m(args.get("place_y_mm", 0)),
            to_m(args.get("place_z_mm", 0)),
        )
    if display is None:
        clear_selection(doc)
        return result(
            False,
            "SOLIDWORKS did not create a dimension for that selection. "
            "Check that the entities can actually carry one dimension between them.",
            entities=count,
        )

    dimension = None
    try:
        dimension = flag_methods(display, "GetDimension2").GetDimension2(0)
    except Exception:
        dimension = safe(display, "GetDimension")

    applied: dict[str, Any] = {}
    if dimension is not None:
        target = None
        if args.get("value_mm") is not None:
            target = to_m(args["value_mm"])
            applied["value_mm"] = float(args["value_mm"])
        elif args.get("value_deg") is not None:
            target = to_rad(args["value_deg"])
            applied["value_deg"] = float(args["value_deg"])
        if target is not None:
            # swSetValueInConfiguration_e.swSetValue_InAllConfigurations = 2
            flag_methods(dimension, "SetSystemValue3")
            code = int(dimension.SetSystemValue3(target, 2, empty_variant()))
            actual = float(safe(dimension, "SystemValue", target) or 0.0)
            applied["applied"] = abs(actual - target) < 1e-9
            if code:
                applied["set_value_status"] = code
        if args.get("name"):
            try:
                dimension.Name = str(args["name"])
            except Exception:
                logger.info("Could not rename the new dimension.")
        applied["full_name"] = str(safe(dimension, "FullName", ""))

    clear_selection(doc)
    # EditRebuild3 exits sketch mode, which would strand the caller mid-sketch;
    # the sketch solver already applied the value, so only rebuild outside one.
    if doc.SketchManager.ActiveSketch is None:
        rebuild(doc)
    status = _sketch_status(doc)
    return result(True, "Added a dimension.", sketch_status=status, **applied)


@tool(
    "set_dimension",
    "Change an existing dimension by its full name, for example 'D1@草图1'. Use list_dimensions to "
    "find names. Linear values are millimetres, angular values are degrees.",
    {
        "full_name": {"type": "string"},
        "value_mm": {"type": "number"},
        "value_deg": {"type": "number"},
    },
    ["full_name"],
)
def set_dimension(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    name = str(args["full_name"])
    dimension = doc.Parameter(name)
    if dimension is None:
        return result(False, f"No dimension named '{name}' exists. Call list_dimensions to see valid names.")
    if args.get("value_mm") is not None:
        target, applied = to_m(args["value_mm"]), {"value_mm": float(args["value_mm"])}
    elif args.get("value_deg") is not None:
        target, applied = to_rad(args["value_deg"]), {"value_deg": float(args["value_deg"])}
    else:
        return result(False, "Pass value_mm or value_deg.")

    flag_methods(dimension, "SetSystemValue3")
    code = int(dimension.SetSystemValue3(target, 2, empty_variant()))
    actual = float(safe(dimension, "SystemValue", target) or 0.0)
    if abs(actual - target) > 1e-9:
        return result(
            False,
            f"SOLIDWORKS did not accept the new value for {name}; the sketch may be over defined.",
            status=code,
            **applied,
        )
    if doc.SketchManager.ActiveSketch is not None:
        return result(True, f"Set {name} in the open sketch.", **applied)
    rebuilt = rebuild(doc)
    return result(rebuilt, f"Set {name}." if rebuilt else f"Set {name}, but the rebuild reported a problem.", **applied)


@tool(
    "list_dimensions",
    "Read-only: list every driving dimension in the document, or only those of one feature/sketch, "
    "with the full names that set_dimension takes.",
    {"feature_name": {"type": "string", "description": "Restrict to one feature or sketch."}},
)
def list_dimensions(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    target = args.get("feature_name")
    features = [find_feature(doc, str(target))] if target else iter_feature_objects(doc)
    if target and features[0] is None:
        return result(False, f"No feature named '{target}' exists in this document.")

    dimensions: list[dict[str, Any]] = []
    for feature in features:
        if feature is None:
            continue
        owner = str(feature_property(feature, "Name", ""))
        try:
            display = value(feature, "GetFirstDisplayDimension")
        except Exception:
            continue
        while display is not None:
            try:
                dimension = flag_methods(display, 'GetDimension2').GetDimension2(0)
                full_name = str(safe(dimension, "FullName", ""))
                system_value = float(safe(dimension, "SystemValue", 0.0) or 0.0)
                entry: dict[str, Any] = {
                    "owner": owner,
                    "full_name": full_name,
                    "name": str(safe(dimension, "Name", "")),
                    "driven": bool(safe(dimension, "DrivenState", 1) == 2),
                }
                # Dimension type 3 is angular in swDimensionType_e; everything
                # else we surface here is a length.
                if int(safe(dimension, "GetType", 0) or 0) == 3:
                    entry["value_deg"] = round(to_deg(system_value), 6)
                else:
                    entry["value_mm"] = round(to_mm(system_value), 6)
                dimensions.append(entry)
            except Exception:
                logger.info("Skipped an unreadable display dimension on %s", owner)
            display = _next_display(feature, display)
    return result(True, f"Read {len(dimensions)} dimensions.", dimensions=dimensions)


def _next_display(feature: Any, current: Any) -> Any:
    try:
        return flag_methods(feature, 'GetNextDisplayDimension').GetNextDisplayDimension(current)
    except Exception:
        return None


@tool(
    "get_sketch_status",
    "Read-only: report whether the open sketch is under defined, fully defined, or over defined.",
    {},
)
def get_sketch_status(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    status = _sketch_status(doc)
    return result(True, f"The open sketch is {status}.", sketch_status=status)
