# Fork addition for SOLIDWORKS 2017 support (see docs/adr/0007-batchC-modules-and-feature-data-access.md).
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

"""Batch C3: surface extrude/revolve/loft/offset/knit/trim, thicken and replace-face (plan items 3.1-3.8).

Four of the 2017 members behind these tools return void (``FeatureExtruRefSurface3``,
``InsertLoftRefSurface2``, ``InsertOffsetSurface``, ``InsertFeatureReplaceFace``), and
trim goes through a Pre/Post pair whose twin in split_body is a known silent no-op.
So no tool here trusts a return value: each one snapshots the feature tree, the
surface and solid bodies, the surface area and the volume before and after, and
reports ``ok`` only when the expected delta is really there.

Surface bodies are not reachable through ``list_faces`` / ``list_bodies`` (they
walk solid bodies only), so the tools take three ways to name an input:

* ``selection``: the usual SELECTION_SCHEMA spec (solid faces, sketches, planes...);
* ``surface_faces``: indices into the faces of all surface bodies, in order;
* ``surface_bodies``: surface body names (every result lists them).

Constants marked LIVE-PROBE are unverified on 2017; the live script
(tests/live_p5_batchC3.py) settles each one.
"""

from __future__ import annotations

from typing import Any, Final

from .sw_core import (
    BODY_SHEET,
    BODY_SOLID,
    END_CONDITIONS,
    SELECTION_SCHEMA,
    apply_selection,
    as_list,
    byref_long,
    clear_selection,
    dialogs_suppressed,
    exit_active_sketch,
    extension,
    feature_manager,
    feature_result,
    get_bodies,
    iter_feature_objects,
    register_flag_methods,
    rename_feature,
    require_part,
    result,
    safe,
    select_at_point,
    select_by_id,
    select_object,
    select_sketch_for_feature,
    to_m,
    to_rad,
    tool,
)
from .sw_feature import _feature_created_after, _feature_names

register_flag_methods(
    "IFeatureManager",
    (
        "FeatureExtruRefSurface3", "InsertRevolvedRefSurface", "InsertSewRefSurface",
        "FeatureBossThicken", "PreTrimSurface", "PostTrimSurface",
    ),
)
register_flag_methods("IModelDoc2", ("InsertLoftRefSurface2", "InsertOffsetSurface", "InsertFeatureReplaceFace"))

# swStartConditions_e.swStartSketchPlane
START_SKETCH_PLANE: Final = 0
# swRevolveType_e: one direction / two directions (angles as given, not the 360 variants)
REVOLVE_ONE_DIRECTION: Final = 0
REVOLVE_TWO_DIRECTIONS: Final = 2
# Selection mark InsertRevolvedRefSurface reads the axis from.  LIVE-PROBE: FeatureRevolve2 uses 4.
REVOLVE_MARK_AXIS: Final = 4
# Selection mark for every loft profile.  LIVE-PROBE: the solid loft (InsertProtrusionBlend2) uses 1.
LOFT_MARK_PROFILE: Final = 1
# InsertLoftRefSurface2 TessToleranceFactor and start/end matching (none = 0).  LIVE-PROBE.
LOFT_TESS_TOLERANCE: Final = 1.0
LOFT_MATCH_NONE: Final = 0
# Select type string for a surface body in SelectByID2.  LIVE-PROBE.
SURFACE_BODY_TYPE: Final = "SURFACEBODY"
# InsertSewRefSurface knit tolerance (metres) and gap range.  LIVE-PROBE: 0.1 mm as the UI default.
KNIT_TOLERANCE_M: Final = 0.0001
KNIT_MAX_GAP_RANGE_M: Final = 0.0
# FeatureBossThicken Direction.  LIVE-PROBE: 0 = side 1 (along the surface normal), 1 = side 2, 2 = both.
THICKEN_SIDES: Final = {"side1": 0, "side2": 1, "both": 2}
# FeatureBossThicken FaceIndex (0 = thicken the whole selected surface).  LIVE-PROBE.
THICKEN_FACE_INDEX: Final = 0
# PreTrimSurface selection marks.  LIVE-PROBE: tool surface 1, pieces to keep/remove 2.
TRIM_MARK_TOOL: Final = 1
TRIM_MARK_PIECES: Final = 2
# InsertFeatureReplaceFace selection marks.  LIVE-PROBE: target faces 1, replacement surface 2.
REPLACE_MARK_TARGET: Final = 1
REPLACE_MARK_SURFACE: Final = 2

# Selection mark knit/thicken read their surfaces from.  Probed live on 2017: mark 0 makes
# FeatureBossThicken return None; mark 1 works.
SURFACE_INPUT_MARK: Final = 1

_AREA_TOLERANCE_MM2: Final = 1e-6

_Inputs = tuple[Any, list[int], list[str]]


# --------------------------------------------------------------------------
# Measurement and selection helpers
# --------------------------------------------------------------------------


def _volume_mm3(doc: Any) -> float:
    """Total solid volume; 0.0 when the part has none (a surface-only part)."""
    try:
        values = extension(doc).GetMassProperties2(2, byref_long(0), False)
        if values is not None and len(values) >= 6:
            return round(float(values[3]) * 1e9, 4)
    except Exception:
        pass
    return 0.0


def _bounding_box_mm(doc: Any) -> list[float] | None:
    try:
        box = doc.GetPartBox(True)
        if box is not None and len(box) >= 6:
            return [round(float(v) * 1000.0, 4) for v in box[:6]]
    except Exception:
        pass
    return None


def _sheet_faces(doc: Any) -> list[Any]:
    return [face for body in get_bodies(doc, BODY_SHEET) for face in as_list(safe(body, "GetFaces"))]


def _snapshot(doc: Any) -> dict[str, Any]:
    """Everything a surface tool is judged by, read from the live model."""
    sheets = get_bodies(doc, BODY_SHEET)
    area_m2 = 0.0
    for body in sheets:
        for face in as_list(safe(body, "GetFaces")):
            area_m2 += float(safe(face, "GetArea", 0.0) or 0.0)
    return {
        "features": len(iter_feature_objects(doc)),
        "surface_bodies": len(sheets),
        "surface_body_names": [str(safe(body, "Name", "")) for body in sheets],
        "solid_bodies": len(get_bodies(doc, BODY_SOLID)),
        "surface_area_mm2": round(area_m2 * 1e6, 4),
        "volume_mm3": _volume_mm3(doc),
        "bbox_mm": _bounding_box_mm(doc),
    }


def _resolve(doc: Any, returned: Any, before_names: list[str]) -> Any | None:
    """The new feature: the returned object, else whatever appeared in the tree.

    A bool or number is not a feature (several of these members return void or a
    flag), so it must not be taken for one.
    """
    if returned is not None and not isinstance(returned, (bool, int, float, str, tuple, list)):
        return returned
    return _feature_created_after(doc, before_names)


def _finish(
    doc: Any,
    feature: Any,
    action: str,
    before: dict[str, Any],
    expect: Any,
    **data: Any,
) -> dict[str, Any]:
    """Standard envelope plus the measured delta; ``expect(before, after)`` -> (ok, why)."""
    payload = feature_result(doc, feature, action, **data)
    after = _snapshot(doc)
    info = payload.setdefault("data", {})
    info["before"] = before
    info["after"] = after
    info["surface_bodies"] = after["surface_body_names"]
    if feature is not None:
        verdict_ok, why = expect(before, after)
        info["verified"] = verdict_ok
        if not verdict_ok:
            payload["ok"] = False
            payload["message"] += f" NOT VERIFIED: {why}"
    return payload


def _expect_new_surface(before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, str]:
    delta = after["surface_bodies"] - before["surface_bodies"]
    if delta == 1:
        return True, ""
    return False, f"expected exactly one new surface body, the surface-body count changed by {delta}."


def _input_props(prefix: str, what: str) -> dict[str, Any]:
    return {
        f"{prefix}selection": {**SELECTION_SCHEMA, "description": f"{what} given as a normal selection spec."},
        f"{prefix}surface_faces": {
            "type": "array", "items": {"type": "integer", "minimum": 0},
            "description": f"{what} as indices into the faces of all surface bodies, in body order.",
        },
        f"{prefix}surface_bodies": {
            "type": "array", "items": {"type": "string"},
            "description": f"{what} as surface body names (every surface tool result lists them).",
        },
    }


def _gather(args: dict[str, Any], prefix: str = "") -> _Inputs:
    return (
        args.get(f"{prefix}selection") or None,
        [int(i) for i in args.get(f"{prefix}surface_faces") or []],
        [str(n) for n in args.get(f"{prefix}surface_bodies") or []],
    )


def _has_inputs(spec: _Inputs) -> bool:
    return bool(spec[0] or spec[1] or spec[2])


def _select_inputs(doc: Any, spec: _Inputs, mark: int, append: bool) -> int:
    """Select faces/bodies/sketches named by one input group; raise if nothing resolved."""
    selection, surface_faces, surface_bodies = spec
    if not append:
        clear_selection(doc)
    count = 0
    if selection:
        picks = list(selection.get("points") or [])
        if picks:
            # Live 2017: SelectByID2 "FACE" never finds a sheet-body face; "FACE2" does.
            # Try FACE then FACE2 per point so one spec works for solids and surfaces.
            selection = {**selection, "points": []}
            for pick in picks:
                point = [to_m(pick["x_mm"]), to_m(pick["y_mm"]), to_m(pick["z_mm"])]
                kind = str(pick.get("type", "FACE")).upper()
                kinds = ["FACE", "FACE2"] if kind == "FACE" else [kind]
                if not any(select_at_point(doc, k, point, mark, True) for k in kinds):
                    raise RuntimeError(f"Nothing of type {kind} was found at {pick}.")
                count += 1
        if any(selection.get(k) for k in selection):
            count += apply_selection(doc, selection, mark, True)
    if surface_faces:
        faces = _sheet_faces(doc)
        for index in surface_faces:
            if not 0 <= index < len(faces):
                raise RuntimeError(f"surface_faces index {index} is out of range (0..{len(faces) - 1}).")
            if not select_object(doc, faces[index], mark, True):
                raise RuntimeError(f"SOLIDWORKS refused to select surface face {index}.")
            count += 1
    for name in surface_bodies:
        if not select_by_id(doc, name, SURFACE_BODY_TYPE, mark, True):
            raise RuntimeError(f"Could not select surface body '{name}'. Use a name from a surface tool result.")
        count += 1
    if count == 0:
        raise RuntimeError("The selection did not resolve to anything.")
    return count


def _number(value: Any, label: str, *, minimum_exclusive: float | None = None, minimum: float | None = None) -> float:
    """A real number (not a bool) within bounds, or ValueError naming ``label``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    if minimum_exclusive is not None and value <= minimum_exclusive:
        raise ValueError(f"{label} must be greater than {minimum_exclusive:g}.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum:g}.")
    return float(value)


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


def _expect_extrude(cap: bool) -> Any:
    """One new surface body; a capped mid-plane/two-sided extrude closes up and SW makes it a solid."""
    def check(before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, str]:
        ok, why = _expect_new_surface(before, after)
        if ok:
            return ok, why
        if cap and after["solid_bodies"] - before["solid_bodies"] == 1 and after["surface_bodies"] == before["surface_bodies"]:
            return True, ""  # both ends capped: SOLIDWORKS closes the surface into a solid
        return ok, why
    return check


@tool(
    "surface_extrude",
    "Extrude a sketch into a surface body (no caps unless cap_ends). Depth in mm; mid_plane extrudes "
    "both ways symmetrically, depth2_mm adds a second direction. Success means exactly one new "
    "surface body appeared; the result lists surface body names and total surface area (face area = "
    "profile perimeter x depth).",
    {
        "sketch_name": {"type": "string", "description": "Profile sketch; defaults to the latest sketch."},
        "depth_mm": {"type": "number", "exclusiveMinimum": 0},
        "depth2_mm": {"type": "number", "exclusiveMinimum": 0, "description": "Second direction depth."},
        "mid_plane": {"type": "boolean", "default": False},
        "reverse": {"type": "boolean", "default": False},
        "cap_ends": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["depth_mm"],
)
def surface_extrude(args: dict[str, Any]) -> dict[str, Any]:
    try:
        depth = _number(args.get("depth_mm"), "depth_mm", minimum_exclusive=0)
        depth2 = (
            _number(args["depth2_mm"], "depth2_mm", minimum_exclusive=0) if args.get("depth2_mm") is not None else None
        )
    except ValueError as exc:
        return result(False, str(exc))
    mid_plane = bool(args.get("mid_plane", False))
    if mid_plane and depth2 is not None:
        return result(False, "mid_plane and depth2_mm are mutually exclusive.")
    _, doc = require_part()
    exit_active_sketch(doc)
    sketch = select_sketch_for_feature(doc, args.get("sketch_name"))
    cap = bool(args.get("cap_ends", False))
    before, names = _snapshot(doc), _feature_names(doc)
    with dialogs_suppressed():
        returned = feature_manager(doc).FeatureExtruRefSurface3(
            depth2 is None, bool(args.get("reverse", False)),
            START_SKETCH_PLANE, 0.0,
            END_CONDITIONS["mid_plane"] if mid_plane else END_CONDITIONS["blind"],
            END_CONDITIONS["blind"],
            to_m(depth), to_m(depth2) if depth2 is not None else 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False,
            cap, cap and depth2 is not None,
            False, False,
        )
    feature = _resolve(doc, returned, names)
    rename_feature(feature, args.get("name"))
    return _finish(
        doc, feature, "surface extrusion", before, _expect_extrude(cap), sketch=sketch, depth_mm=depth,
    )


@tool(
    "surface_revolve",
    "Revolve a sketch into a surface body about a centerline in the sketch or axis_selection. Angle "
    "in degrees; angle2_deg adds a second direction. Success means exactly one new surface body "
    "(full-turn area = 2 pi x centroid radius x profile length).",
    {
        "sketch_name": {"type": "string"},
        "angle_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 360, "default": 360},
        "angle2_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 360},
        "axis_selection": SELECTION_SCHEMA,
        "reverse": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
)
def surface_revolve(args: dict[str, Any]) -> dict[str, Any]:
    try:
        angle = _number(args.get("angle_deg", 360), "angle_deg", minimum_exclusive=0)
        angle2 = (
            _number(args["angle2_deg"], "angle2_deg", minimum_exclusive=0) if args.get("angle2_deg") is not None else None
        )
    except ValueError as exc:
        return result(False, str(exc))
    if angle > 360 or (angle2 is not None and angle2 > 360):
        return result(False, "Angles must be at most 360 degrees.")
    _, doc = require_part()
    exit_active_sketch(doc)
    sketch = select_sketch_for_feature(doc, args.get("sketch_name"))
    if args.get("axis_selection"):
        apply_selection(doc, args["axis_selection"], REVOLVE_MARK_AXIS, True)
    before, names = _snapshot(doc), _feature_names(doc)
    with dialogs_suppressed():
        returned = feature_manager(doc).InsertRevolvedRefSurface(
            to_rad(angle), bool(args.get("reverse", False)),
            to_rad(angle2) if angle2 is not None else 0.0,
            REVOLVE_TWO_DIRECTIONS if angle2 is not None else REVOLVE_ONE_DIRECTION,
        )
    feature = _resolve(doc, returned, names)
    rename_feature(feature, args.get("name"))
    return _finish(doc, feature, "surface revolve", before, _expect_new_surface, sketch=sketch, angle_deg=angle)


@tool(
    "surface_loft",
    "Loft a surface body through two or more profile sketches, in the order given. Success means "
    "exactly one new surface body.",
    {
        "profile_sketches": {"type": "array", "minItems": 2, "items": {"type": "string"}},
        "closed": {"type": "boolean", "default": False},
        "keep_tangency": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["profile_sketches"],
)
def surface_loft(args: dict[str, Any]) -> dict[str, Any]:
    profiles = [str(n) for n in args.get("profile_sketches") or []]
    if len(profiles) < 2:
        return result(False, "surface_loft needs at least two profile sketches.")
    if len(set(profiles)) != len(profiles):
        return result(False, "profile_sketches must not repeat a sketch.")
    _, doc = require_part()
    exit_active_sketch(doc)
    clear_selection(doc)
    for index, name in enumerate(profiles):
        if not select_by_id(doc, name, "SKETCH", LOFT_MARK_PROFILE, index > 0):
            return result(False, f"Could not select profile sketch '{name}'.")
    before, names = _snapshot(doc), _feature_names(doc)
    with dialogs_suppressed():
        returned = doc.InsertLoftRefSurface2(
            bool(args.get("closed", False)), bool(args.get("keep_tangency", False)), False,
            LOFT_TESS_TOLERANCE, LOFT_MATCH_NONE, LOFT_MATCH_NONE,
        )
    feature = _resolve(doc, returned, names)
    rename_feature(feature, args.get("name"))
    return _finish(doc, feature, "surface loft", before, _expect_new_surface, profiles=profiles)


@tool(
    "surface_offset",
    "Offset faces (solid or surface) into a new surface body by distance_mm (0 copies the surface). "
    "Give the faces as selection, surface_faces or surface_bodies. Success means exactly one new "
    "surface body; the result lists areas before and after.",
    {
        **_input_props("", "The faces to offset"),
        "distance_mm": {"type": "number", "minimum": 0},
        "reverse": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["distance_mm"],
)
def surface_offset(args: dict[str, Any]) -> dict[str, Any]:
    try:
        distance = _number(args.get("distance_mm"), "distance_mm", minimum=0)
    except ValueError as exc:
        return result(False, str(exc))
    spec = _gather(args)
    if not _has_inputs(spec):
        return result(False, "Name the faces to offset with selection, surface_faces or surface_bodies.")
    _, doc = require_part()
    exit_active_sketch(doc)
    _select_inputs(doc, spec, 0, False)
    before, names = _snapshot(doc), _feature_names(doc)
    with dialogs_suppressed():
        returned = doc.InsertOffsetSurface(to_m(distance), bool(args.get("reverse", False)))
    feature = _resolve(doc, returned, names)
    rename_feature(feature, args.get("name"))
    return _finish(doc, feature, "surface offset", before, _expect_new_surface, distance_mm=distance)


def _expect_knit(try_form_solid: bool) -> Any:
    def check(before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, str]:
        if try_form_solid:
            if after["solid_bodies"] > before["solid_bodies"] and after["volume_mm3"] > 0:
                return True, ""
            return False, "try_form_solid was requested but no solid with volume formed; the surfaces have gaps."
        if after["surface_bodies"] < before["surface_bodies"]:
            return True, ""
        return False, "the number of surface bodies did not drop, so nothing was knit."

    return check


@tool(
    "surface_knit",
    "Knit (sew) surfaces into one surface body, optionally forming a solid when they close a volume. "
    "Give surfaces as surface_bodies names, surface_faces or selection. With try_form_solid the "
    "result must contain a new solid with volume > 0; otherwise the surface-body count must drop.",
    {
        **_input_props("", "The surfaces to knit"),
        "try_form_solid": {"type": "boolean", "default": False},
        "merge_entities": {"type": "boolean", "default": True},
        "tolerance_mm": {"type": "number", "exclusiveMinimum": 0, "default": 0.1},
        "name": {"type": "string"},
    },
)
def surface_knit(args: dict[str, Any]) -> dict[str, Any]:
    spec = _gather(args)
    if not _has_inputs(spec):
        return result(False, "Name the surfaces to knit with surface_bodies, surface_faces or selection.")
    try:
        tolerance = _number(args.get("tolerance_mm", KNIT_TOLERANCE_M * 1000.0), "tolerance_mm", minimum_exclusive=0)
    except ValueError as exc:
        return result(False, str(exc))
    solid = bool(args.get("try_form_solid", False))
    _, doc = require_part()
    exit_active_sketch(doc)
    _select_inputs(doc, spec, SURFACE_INPUT_MARK, False)
    before, names = _snapshot(doc), _feature_names(doc)
    with dialogs_suppressed():
        returned = feature_manager(doc).InsertSewRefSurface(
            # Live 2017: TryToFormSolid only yields a solid when UseGapFilters is True.
            solid, solid, bool(args.get("merge_entities", True)), to_m(tolerance), KNIT_MAX_GAP_RANGE_M,
        )
    feature = _resolve(doc, returned, names)
    rename_feature(feature, args.get("name"))
    return _finish(doc, feature, "surface knit", before, _expect_knit(solid), try_form_solid=solid)


@tool(
    "thicken",
    "Thicken a surface body into a solid. side: side1 / side2 (one side of the surface) or both (thickness applied on each side, so the total is 2x). "
    "Without merge the result must be exactly one new solid body; the result reports the volume added "
    "and the expected area x thickness for a single-surface, single-side thicken.",
    {
        **_input_props("", "The surface to thicken"),
        "thickness_mm": {"type": "number", "exclusiveMinimum": 0},
        "side": {"type": "string", "enum": sorted(THICKEN_SIDES), "default": "side1"},
        "merge": {"type": "boolean", "default": False, "description": "Merge into an existing solid."},
        "fill_volume": {"type": "boolean", "default": False, "description": "Fill a closed surface."},
        "name": {"type": "string"},
    },
    ["thickness_mm"],
)
def thicken(args: dict[str, Any]) -> dict[str, Any]:
    try:
        thickness = _number(args.get("thickness_mm"), "thickness_mm", minimum_exclusive=0)
    except ValueError as exc:
        return result(False, str(exc))
    side = str(args.get("side", "side1"))
    if side not in THICKEN_SIDES:
        return result(False, f"Unknown side '{side}'. Choose from {sorted(THICKEN_SIDES)}.")
    spec = _gather(args)
    if not _has_inputs(spec):
        return result(False, "Name the surface to thicken with surface_bodies, surface_faces or selection.")
    merge = bool(args.get("merge", False))
    _, doc = require_part()
    exit_active_sketch(doc)
    _select_inputs(doc, spec, SURFACE_INPUT_MARK, False)
    before, names = _snapshot(doc), _feature_names(doc)
    with dialogs_suppressed():
        # FeatureBossThicken returns the feature (FeatureBossThicken2 is void).
        returned = feature_manager(doc).FeatureBossThicken(
            to_m(thickness), THICKEN_SIDES[side], THICKEN_FACE_INDEX,
            bool(args.get("fill_volume", False)), merge, True, True,
        )
    feature = _resolve(doc, returned, names)
    rename_feature(feature, args.get("name"))

    def check(b: dict[str, Any], a: dict[str, Any]) -> tuple[bool, str]:
        if a["volume_mm3"] <= b["volume_mm3"]:
            return False, "the solid volume did not grow."
        if not merge and a["solid_bodies"] != b["solid_bodies"] + 1:
            return False, f"expected one new solid body, the count changed by {a['solid_bodies'] - b['solid_bodies']}."
        return True, ""

    payload = _finish(doc, feature, "thicken", before, check, thickness_mm=thickness, side=side)
    info = payload["data"]
    # Live 2017: side="both" thickens thickness_mm on EACH side (total 2x).
    info["expected_volume_mm3"] = round(before["surface_area_mm2"] * thickness * (2 if side == "both" else 1), 4)
    info["volume_added_mm3"] = round(info["after"]["volume_mm3"] - before["volume_mm3"], 4)
    return payload


@tool(
    "surface_trim",
    "Trim surfaces with PreTrimSurface + PostTrimSurface. tool_* names the trimming surface, sketch "
    "or plane; pieces_* names the pieces to keep (keep_selected=true) or remove. mutual trims both "
    "surfaces against each other. Success means the feature built and the surface area or body count "
    "changed; this Pre/Post pair is suspect on 2017 (like split_body) and the answer says which step "
    "stopped.",
    {
        **_input_props("tool_", "The trimming tool"),
        **_input_props("pieces_", "The pieces to keep or remove"),
        "mutual": {"type": "boolean", "default": False},
        "keep_selected": {"type": "boolean", "default": True, "description": "Keep (true) or remove (false) the pieces."},
        "sew": {"type": "boolean", "default": False, "description": "Knit the trimmed surfaces afterwards."},
        "name": {"type": "string"},
    },
)
def surface_trim(args: dict[str, Any]) -> dict[str, Any]:
    tool_spec, pieces_spec = _gather(args, "tool_"), _gather(args, "pieces_")
    if not _has_inputs(tool_spec):
        return result(False, "Name the trimming tool with tool_selection, tool_surface_faces or tool_surface_bodies.")
    if not _has_inputs(pieces_spec):
        return result(False, "Name the pieces to keep/remove with pieces_selection, pieces_surface_faces or pieces_surface_bodies.")
    _, doc = require_part()
    exit_active_sketch(doc)
    _select_inputs(doc, tool_spec, TRIM_MARK_TOOL, False)
    _select_inputs(doc, pieces_spec, TRIM_MARK_PIECES, True)
    before, names = _snapshot(doc), _feature_names(doc)
    manager = feature_manager(doc)
    with dialogs_suppressed():
        prepared = manager.PreTrimSurface(
            bool(args.get("mutual", False)), False, False, not bool(args.get("keep_selected", True)),
        )
        if not prepared:
            clear_selection(doc)
            return result(False, "PreTrimSurface refused the selection (tool and pieces must be intersecting surfaces).")
        returned = manager.PostTrimSurface(bool(args.get("sew", False)))
    feature = _resolve(doc, returned, names)
    rename_feature(feature, args.get("name"))

    def check(b: dict[str, Any], a: dict[str, Any]) -> tuple[bool, str]:
        if abs(a["surface_area_mm2"] - b["surface_area_mm2"]) > _AREA_TOLERANCE_MM2 or a["surface_bodies"] != b["surface_bodies"]:
            return True, ""
        return False, "PostTrimSurface returned a feature but the surface area and body count are unchanged (silent no-op)."

    return _finish(doc, feature, "surface trim", before, check)


@tool(
    "replace_face",
    "Replace faces of a solid with a surface (Replace Face). target_* names the faces to replace; "
    "replacement_* names the replacement surface. Success means the volume or bounding box changed.",
    {
        **_input_props("target_", "The solid faces to replace"),
        **_input_props("replacement_", "The replacement surface"),
        "name": {"type": "string"},
    },
)
def replace_face(args: dict[str, Any]) -> dict[str, Any]:
    target, replacement = _gather(args, "target_"), _gather(args, "replacement_")
    if not _has_inputs(target):
        return result(False, "Name the faces to replace with target_selection (solid faces).")
    if not _has_inputs(replacement):
        return result(False, "Name the replacement surface with replacement_surface_bodies, replacement_surface_faces or replacement_selection.")
    _, doc = require_part()
    exit_active_sketch(doc)
    _select_inputs(doc, target, REPLACE_MARK_TARGET, False)
    _select_inputs(doc, replacement, REPLACE_MARK_SURFACE, True)
    before, names = _snapshot(doc), _feature_names(doc)
    with dialogs_suppressed():
        returned = doc.InsertFeatureReplaceFace()
    feature = _resolve(doc, returned, names)
    rename_feature(feature, args.get("name"))

    def check(b: dict[str, Any], a: dict[str, Any]) -> tuple[bool, str]:
        if abs(a["volume_mm3"] - b["volume_mm3"]) > 1e-6 or a["bbox_mm"] != b["bbox_mm"]:
            return True, ""
        return False, "a feature was created but the volume and bounding box are unchanged."

    return _finish(doc, feature, "replace face", before, check)
