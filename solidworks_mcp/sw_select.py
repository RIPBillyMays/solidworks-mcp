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

"""Undo/redo and explicit selection tools (fork addition, ADR-0002 compliant).

Selection is SOLIDWORKS' implicit global state; these tools expose it so a
client can pick an entity, inspect what is selected, and clear it.
"""

from __future__ import annotations

from typing import Any

from .sw_core import (
    active_document,
    clear_selection,
    extension,
    flag_methods,
    as_list,
    iter_features,
    nothing,
    safe,
    result,
    select_by_id,
    tool,
    to_m,
)

SELECT_TYPES = [
    "FACE", "EDGE", "VERTEX", "PLANE", "AXIS", "SKETCH", "SKETCHSEGMENT", "SKETCHPOINT",
    "BODYFEATURE", "SOLIDBODY", "SURFBODY", "COMPONENT", "DATUMPOINT", "COMPSKETCH",
]


def selection_count(doc: Any) -> int:
    """Number of selected objects (any mark); -1 when the count is unreadable."""
    try:
        manager = flag_methods(doc.SelectionManager, "GetSelectedObjectCount2")
        return int(manager.GetSelectedObjectCount2(-1))
    except Exception:
        return -1


@tool(
    "undo",
    "Undo the last N operations in the active document (default 1). Reports the feature count "
    "before and after, since SOLIDWORKS gives no undo-stack depth. While a sketch is open the "
    "sketch segment and point counts are compared instead. One feature can take several "
    "undo steps (the sketch un-absorb is a separate step), so check feature_tree_changed. "
    "Geometry made by draw_* tools is created outside the undo stack (exact-geometry mode), so "
    "undo will not remove it: use delete_sketch_segment instead.",
    {"count": {"type": "integer", "minimum": 1, "maximum": 50, "default": 1}},
)
def undo(args: dict[str, Any]) -> dict[str, Any]:
    return _step(args, "EditUndo2", "Undid")


@tool(
    "redo",
    "Redo the last N undone operations in the active document (default 1).",
    {"count": {"type": "integer", "minimum": 1, "maximum": 50, "default": 1}},
)
def redo(args: dict[str, Any]) -> dict[str, Any]:
    return _step(args, "EditRedo2", "Redid")


def _sketch_counts(doc: Any) -> tuple[int, int] | None:
    """(segments, points) of the open sketch, or None when no sketch is open."""
    try:
        sketch = doc.SketchManager.ActiveSketch
    except Exception:
        return None
    if sketch is None:
        return None
    return (
        len(as_list(safe(sketch, "GetSketchSegments"))),
        len(as_list(safe(sketch, "GetSketchPoints2"))),
    )


_SKETCH_UNDO_HINT = (
    " Geometry made by draw_* tools is created outside the undo stack (exact-geometry mode), so "
    "undo cannot remove it; use delete_sketch_segment instead."
)


def _step_in_sketch(doc: Any, before: tuple[int, int], member: str, verb: str, count: int) -> dict[str, Any]:
    """Undo/redo inside an open sketch: the feature list never changes there, so
    judge by the sketch's segment and point counts instead (field finding #14)."""
    flag_methods(doc, member)
    getattr(doc, member)(count)
    after = _sketch_counts(doc)
    clear_selection(doc)
    if after is None:
        # The step closed the sketch (e.g. undoing its creation); the sketch is gone.
        return result(
            True, f"{verb} {count} step(s); the sketch is no longer open.",
            steps=count, in_sketch=True, sketch_open=False,
            segments_before=before[0], points_before=before[1],
        )
    changed = after != before
    return result(
        changed,
        f"{verb} {count} step(s) in the open sketch; segments {before[0]} -> {after[0]}, "
        f"points {before[1]} -> {after[1]}."
        if changed else f"SOLIDWORKS refused to {verb.lower().rstrip('d')} {count} step(s) in the sketch (nothing to do?)."
        + _SKETCH_UNDO_HINT,
        steps=count, in_sketch=True, sketch_open=True,
        segments_before=before[0], segments_after=after[0],
        points_before=before[1], points_after=after[1],
        sketch_changed=changed,
    )


def _step(args: dict[str, Any], member: str, verb: str) -> dict[str, Any]:
    _, doc = active_document()
    count = max(1, int(args.get("count", 1)))
    in_sketch = _sketch_counts(doc)
    if in_sketch is not None:
        return _step_in_sketch(doc, in_sketch, member, verb, count)
    before = [f["name"] for f in iter_features(doc)]
    flag_methods(doc, member)
    # EditUndo2/EditRedo2 return void (None) on 2017, so success is judged by the tree.
    returned = getattr(doc, member)(count)
    after = [f["name"] for f in iter_features(doc)]
    clear_selection(doc)
    changed = before != after
    ok = bool(returned) or changed
    return result(
        ok,
        f"{verb} {count} step(s); feature count {len(before)} -> {len(after)}."
        if ok else f"SOLIDWORKS refused to {verb.lower().rstrip('d')} {count} step(s) (nothing to do?).",
        steps=count,
        features_before=len(before),
        features_after=len(after),
        feature_tree_changed=changed,
        last_feature=after[-1] if after else None,
    )


@tool(
    "select_entity",
    "Select one entity so a following tool can act on it. Either by name (name + type) or by a point "
    "on it (x_mm,y_mm,z_mm + type). With ray=true the point is a ray origin and direction "
    "(dir_x/dir_y/dir_z) is used with SelectByRay, which picks the first entity of that type the ray hits.",
    {
        "type": {"type": "string", "enum": SELECT_TYPES, "description": "Entity type to select."},
        "name": {"type": "string", "description": "Entity or feature name, as in the feature tree."},
        "x_mm": {"type": "number"}, "y_mm": {"type": "number"}, "z_mm": {"type": "number"},
        "ray": {"type": "boolean", "default": False},
        "dir_x": {"type": "number"}, "dir_y": {"type": "number"}, "dir_z": {"type": "number"},
        "radius_mm": {"type": "number", "default": 1.0, "description": "Ray radius for ray=true."},
        "append": {"type": "boolean", "default": False, "description": "Keep the existing selection."},
        "mark": {"type": "integer", "default": 0},
    },
    ["type"],
)
def select_entity(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    kind = str(args["type"]).upper()
    append = bool(args.get("append", False))
    mark = int(args.get("mark", 0))
    if not append:
        clear_selection(doc)

    has_point = all(args.get(k) is not None for k in ("x_mm", "y_mm", "z_mm"))
    if args.get("ray"):
        if not has_point or any(args.get(k) is None for k in ("dir_x", "dir_y", "dir_z")):
            return result(False, "ray=true needs x_mm,y_mm,z_mm and dir_x,dir_y,dir_z.")
        ext = extension(doc)
        # SelectByRay's TypeWanted is a swSelectType_e value.
        wanted = {"FACE": 2, "EDGE": 1, "VERTEX": 3, "SOLIDBODY": 76, "SURFBODY": 75}.get(kind)
        if wanted is None:
            return result(False, f"SelectByRay supports FACE, EDGE, VERTEX, SOLIDBODY, SURFBODY, not {kind}.")
        ok = bool(ext.SelectByRay(
            to_m(args["x_mm"]), to_m(args["y_mm"]), to_m(args["z_mm"]),
            float(args["dir_x"]), float(args["dir_y"]), float(args["dir_z"]),
            to_m(args.get("radius_mm", 1.0)), wanted, True, mark, 0,
        ))
    elif has_point:
        ext = extension(doc)
        x, y, z = (to_m(args[k]) for k in ("x_mm", "y_mm", "z_mm"))
        ok = bool(ext.SelectByID2(str(args.get("name", "")), kind, x, y, z, True, mark, nothing(), 0))
    elif args.get("name"):
        ok = select_by_id(doc, str(args["name"]), kind, mark, True)
    else:
        return result(False, "Give a name, or x_mm/y_mm/z_mm (optionally ray=true with a direction).")

    count = selection_count(doc)
    return result(
        ok,
        f"Selected {kind}; {count} object(s) now selected." if ok else f"Nothing of type {kind} was found there.",
        type=kind,
        selected_count=count,
    )


@tool("clear_selection", "Clear the current selection in the active document.")
def clear_selection_tool(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    clear_selection(doc)
    return result(True, "Selection cleared.", selected_count=selection_count(doc))
