# Fork addition for SOLIDWORKS 2017 support (phase 5, batch B).
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

"""Reference points and coordinate systems, multi-body operations (combine,
split, move/copy, scale, mirror, delete, intersect) and a few shaping features
(dome, helix/spiral, wrap).

Every call here is a member of the 2017 type library (checked against
``tools/compat/sw2017_api_members.txt``).  Several argument conventions are
only documented loosely, so the constants that encode them are collected at
the top and each tool says in its description when it is unverified on 2017;
the live checklist is in docs/reports/phase5-batchB-geometry.md.
Constants use ``Final`` annotations so tests/test_sw2017_batchB_geometry.py can
check them against the 2017 enum dump.
"""

from __future__ import annotations

from typing import Any, Final

from .sw_core import (
    apply_selection,
    clear_selection,
    dialogs_suppressed,
    dispatch_array,
    as_list,
    empty_variant,
    exit_active_sketch,
    feature_manager,
    feature_result,
    get_bodies,
    rename_feature,
    require_part,
    require_selection,
    resolve_sketch,
    result,
    select_by_id,
    select_sketch_for_feature,
    SELECTION_SCHEMA,
    tool,
    to_m,
    to_rad,
    value,
)
from .sw_feature import _feature_created_after, _feature_names

# swRefPointType_e
REF_POINT_TYPES: Final = {
    "along_curve": 2, "arc_center": 3, "face_center": 4, "vertex_projection": 5,
    "intersection": 6, "sketch_point": 7,
}
# swRefPointAlongCurveType_e
REF_POINT_ALONG: Final = {"distance": 0, "percentage": 1, "evenly": 2}
# Selection marks for InsertCoordinateSystem: origin, X, Y, Z reference
COORD_MARK_ORIGIN: Final = 1
COORD_MARK_X: Final = 2
COORD_MARK_Y: Final = 4
COORD_MARK_Z: Final = 8
# swCombineBodiesOperationType_e
COMBINE_OPS: Final = {"add": 0, "subtract": 1, "common": 2}
# swScaleType_e
SCALE_ABOUT: Final = {"centroid": 0, "origin": 1, "coordinate_system": 2}
# Selection mark the dome face needs (verified live)
DOME_MARK_FACE: Final = 1
# swHelixDefinedBy_e
HELIX_DEFINED_BY: Final = {
    "pitch_revolutions": 0, "height_revolutions": 1, "height_pitch": 2, "spiral": 3,
}
# swWrapSketchType_e
WRAP_TYPES: Final = {"emboss": 0, "deboss": 1, "scribe": 2}
# swWrapMethods_e
WRAP_METHODS: Final = {"analytical": 0, "spline_surface": 1}
# Selection marks for wrap: the sketch, then the face it wraps onto
# Live 2017: the sketch needs mark 4 and the face mark 1 (the 1/2 guess built nothing)
WRAP_MARK_SKETCH: Final = 4
WRAP_MARK_FACE: Final = 1
# Selection marks for a body mirror (InsertMirrorFeature2): bodies, then the plane
MIRROR_MARK_BODY: Final = 256  # live 2017: mark 1 is refused, 256 mirrors the body
MIRROR_MARK_PLANE: Final = 2


def _resolve(doc: Any, returned: Any, before: list[str]) -> Any | None:
    """The new feature: whatever the call returned, else what appeared in the tree.

    Several of these members return void or a bool on 2017, so a bare ``True``
    must not be mistaken for a feature.
    """
    if returned is not None and not isinstance(returned, (bool, int, float, str, tuple, list)):
        return returned
    return _feature_created_after(doc, before)


def _bodies_by_index(doc: Any, indices: list[int]) -> list[Any]:
    bodies = get_bodies(doc)
    picked = []
    for raw in indices:
        index = int(raw)
        if not 0 <= index < len(bodies):
            raise RuntimeError(f"Body index {index} is out of range (0..{len(bodies) - 1}); call list_bodies.")
        picked.append(bodies[index])
    return picked


# --------------------------------------------------------------------------
# Reference geometry
# --------------------------------------------------------------------------


@tool(
    "create_reference_point",
    "Create a reference point. method: face_center (select a face), arc_center (select a circular "
    "edge), along_curve (select an edge or curve; along=distance uses distance_mm from the start, "
    "along=percentage uses percent, along=evenly uses count), intersection (select two edges or "
    "curves), sketch_point (select a sketch point), vertex_projection (select a face and a "
    "vertex).",
    {
        "method": {"type": "string", "enum": sorted(REF_POINT_TYPES)},
        "selection": SELECTION_SCHEMA,
        "along": {"type": "string", "enum": sorted(REF_POINT_ALONG), "default": "distance"},
        "distance_mm": {"type": "number", "description": "along_curve + along=distance."},
        "percent": {"type": "number", "minimum": 0, "maximum": 100, "description": "along_curve + along=percentage."},
        "count": {"type": "integer", "minimum": 1, "default": 1, "description": "Number of points for along=evenly."},
        "name": {"type": "string"},
    },
    ["method", "selection"],
)
def create_reference_point(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    method = str(args["method"])
    if method not in REF_POINT_TYPES:
        return result(False, f"Unknown method '{method}'. Choose from {sorted(REF_POINT_TYPES)}.")
    along = str(args.get("along", "distance"))
    amount = 0.0
    count = 1
    if method == "along_curve":
        if along == "distance":
            if args.get("distance_mm") is None:
                return result(False, "along=distance needs distance_mm.")
            amount = to_m(args["distance_mm"])
        elif along == "percentage":
            if args.get("percent") is None:
                return result(False, "along=percentage needs percent.")
            # Live 2017: Amount is already in percent (25 = 25%); 0.25 landed 0.25% along the edge.
            amount = float(args["percent"])
        elif along == "evenly":
            count = int(args.get("count", 1))
        else:
            return result(False, f"Unknown along '{along}'.")
    before = _feature_names(doc)
    require_selection(doc, args["selection"])
    with dialogs_suppressed():
        returned = feature_manager(doc).InsertReferencePoint(
            REF_POINT_TYPES[method], REF_POINT_ALONG.get(along, 0), amount, count
        )
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "reference point", method=method)


@tool(
    "create_coordinate_system",
    "Create a coordinate system. origin: a vertex or point. x_axis, y_axis, z_axis: an edge, "
    "planar face or axis giving each direction (give at least x_axis and y_axis). The flip_* "
    "flags reverse a direction. Mark conventions are unverified on 2017 until probed live.",
    {
        "origin": SELECTION_SCHEMA,
        "x_axis": SELECTION_SCHEMA,
        "y_axis": SELECTION_SCHEMA,
        "z_axis": SELECTION_SCHEMA,
        "flip_x": {"type": "boolean", "default": False},
        "flip_y": {"type": "boolean", "default": False},
        "flip_z": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["origin", "x_axis", "y_axis"],
)
def create_coordinate_system(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    before = _feature_names(doc)
    require_selection(doc, args["origin"], mark=COORD_MARK_ORIGIN)
    require_selection(doc, args["x_axis"], mark=COORD_MARK_X, append=True)
    require_selection(doc, args["y_axis"], mark=COORD_MARK_Y, append=True)
    if args.get("z_axis"):
        require_selection(doc, args["z_axis"], mark=COORD_MARK_Z, append=True)
    with dialogs_suppressed():
        returned = feature_manager(doc).InsertCoordinateSystem(
            bool(args.get("flip_x", False)), bool(args.get("flip_y", False)), bool(args.get("flip_z", False))
        )
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "coordinate system")


# --------------------------------------------------------------------------
# Multi-body operations
# --------------------------------------------------------------------------


@tool(
    "combine_bodies",
    "Combine solid bodies (indices from list_bodies). operation=add merges main_body and tool_bodies "
    "into one; subtract removes tool_bodies from main_body; common keeps only the volume shared by "
    "main_body and tool_bodies.",
    {
        "operation": {"type": "string", "enum": sorted(COMBINE_OPS)},
        "main_body": {"type": "integer", "minimum": 0},
        "tool_bodies": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1},
        "name": {"type": "string"},
    },
    ["operation", "main_body", "tool_bodies"],
)
def combine_bodies(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    operation = str(args["operation"])
    if operation not in COMBINE_OPS:
        return result(False, f"Unknown operation '{operation}'. Choose from {sorted(COMBINE_OPS)}.")
    if int(args["main_body"]) in [int(i) for i in args["tool_bodies"]]:
        return result(False, "main_body must not also appear in tool_bodies.")
    main = _bodies_by_index(doc, [args["main_body"]])[0]
    tools = _bodies_by_index(doc, list(args["tool_bodies"]))
    before = _feature_names(doc)
    clear_selection(doc)
    with dialogs_suppressed():
        returned = feature_manager(doc).InsertCombineFeature(COMBINE_OPS[operation], main, dispatch_array(tools))
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, f"combine ({operation})", bodies_after=len(get_bodies(doc)))


@tool(
    "split_body",
    "Split a body with a plane, surface or sketch given in tool_selection. All resulting bodies are "
    "kept unless consume_cut is true. Uses PreSplitBody2/PostSplitBody, whose return values are not "
    "documented for 2017; on failure the answer says which step stopped. method=\"cut\" is the 2017 "
    "retry: tool_selection {\"sketches\": [closed profile]} is cut through all in both directions "
    "(removes the profile volume, reported as kerf).",
    {
        "method": {"type": "string", "enum": ["split", "cut"], "default": "split"},
        "tool_selection": SELECTION_SCHEMA,
        "consume_cut": {"type": "boolean", "default": False, "description": "Delete the cutting surface or sketch's body."},
        "name": {"type": "string"},
    },
    ["tool_selection"],
)
def split_body(args: dict[str, Any]) -> dict[str, Any]:
    # Modified for SOLIDWORKS 2017 support (fork): PostSplitBody is a no-op, so offer a FeatureCut4 route.
    method = str(args.get("method", "split"))
    if method not in ("split", "cut"):
        return result(False, f"Unknown method '{method}'. Choose split or cut.")
    if method == "cut":
        from .sw_edit import split_via_cut  # lazy: sw_edit imports sw_feature/sw_surface, like this module

        return split_via_cut(args)
    _, doc = require_part()
    exit_active_sketch(doc)
    before = _feature_names(doc)
    require_selection(doc, args["tool_selection"])
    manager = feature_manager(doc)
    with dialogs_suppressed():
        # no-argument member: pywin32 may have already evaluated it on attribute access
        pieces = value(manager, "PreSplitBody2")
        targets = as_list(pieces) if not isinstance(pieces, bool) else []
        if not pieces:
            return result(False, "PreSplitBody2 produced nothing: the cutting entity does not cross a body.")
        if not targets:
            return result(False, "PreSplitBody2 returned no resulting bodies to keep; split is not usable here.")
        returned = manager.PostSplitBody(
            dispatch_array(targets), bool(args.get("consume_cut", False)), empty_variant(), empty_variant()
        )
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "split", bodies_after=len(get_bodies(doc)))


@tool(
    "move_copy_body",
    "Translate and/or rotate solid bodies, optionally leaving copies. Translation is in mm along "
    "X/Y/Z; rotation is degrees about axes through the point (pivot_*_mm). With copy=true, count "
    "copies are made, each offset by the same transform.",
    {
        "bodies": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1},
        "dx_mm": {"type": "number", "default": 0},
        "dy_mm": {"type": "number", "default": 0},
        "dz_mm": {"type": "number", "default": 0},
        "rx_deg": {"type": "number", "default": 0},
        "ry_deg": {"type": "number", "default": 0},
        "rz_deg": {"type": "number", "default": 0},
        "pivot_x_mm": {"type": "number", "default": 0},
        "pivot_y_mm": {"type": "number", "default": 0},
        "pivot_z_mm": {"type": "number", "default": 0},
        "copy": {"type": "boolean", "default": False},
        "count": {"type": "integer", "minimum": 1, "default": 1},
        "name": {"type": "string"},
    },
    ["bodies"],
)
def move_copy_body(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    before = _feature_names(doc)
    # Live 2017: InsertMoveCopyBody2 returns Nothing unless the bodies carry mark 1.
    apply_selection(doc, {"bodies": list(args["bodies"])}, mark=1)
    copy = bool(args.get("copy", False))
    with dialogs_suppressed():
        returned = feature_manager(doc).InsertMoveCopyBody2(
            to_m(args.get("dx_mm", 0.0)), to_m(args.get("dy_mm", 0.0)), to_m(args.get("dz_mm", 0.0)), 0.0,
            to_m(args.get("pivot_x_mm", 0.0)), to_m(args.get("pivot_y_mm", 0.0)), to_m(args.get("pivot_z_mm", 0.0)),
            # Live 2017: the three angle slots turn about Z, Y, X in that order (not X, Y, Z).
            to_rad(args.get("rz_deg", 0.0)), to_rad(args.get("ry_deg", 0.0)), to_rad(args.get("rx_deg", 0.0)),
            copy, int(args.get("count", 1)) if copy else 0,
        )
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "move/copy body", bodies_after=len(get_bodies(doc)))


@tool(
    "scale_part",
    "Scale the whole part. Uniform scaling uses factor; non-uniform uses x/y/z factors. about "
    "picks the fixed point: centroid, origin, or coordinate_system (select it in selection).",
    {
        "factor": {"type": "number", "exclusiveMinimum": 0},
        "x_factor": {"type": "number", "exclusiveMinimum": 0},
        "y_factor": {"type": "number", "exclusiveMinimum": 0},
        "z_factor": {"type": "number", "exclusiveMinimum": 0},
        "about": {"type": "string", "enum": sorted(SCALE_ABOUT), "default": "centroid"},
        "selection": SELECTION_SCHEMA,
        "name": {"type": "string"},
    },
)
def scale_part(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    about = str(args.get("about", "centroid"))
    if about not in SCALE_ABOUT:
        return result(False, f"Unknown about '{about}'. Choose from {sorted(SCALE_ABOUT)}.")
    if args.get("factor") is not None:
        uniform, fx = True, float(args["factor"])
        fy = fz = fx
    elif all(args.get(k) is not None for k in ("x_factor", "y_factor", "z_factor")):
        uniform = False
        fx, fy, fz = float(args["x_factor"]), float(args["y_factor"]), float(args["z_factor"])
    else:
        return result(False, "Give factor, or all of x_factor, y_factor and z_factor.")
    before = _feature_names(doc)
    if args.get("selection"):
        require_selection(doc, args["selection"])
    else:
        clear_selection(doc)
    with dialogs_suppressed():
        returned = feature_manager(doc).InsertScale(SCALE_ABOUT[about], uniform, fx, fy, fz)
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "scale", about=about)


@tool(
    "mirror_body",
    "Mirror whole solid bodies (indices from list_bodies) about a plane or planar face. merge=true "
    "fuses the mirror with the original where they touch.",
    {
        "bodies": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1},
        "plane_selection": SELECTION_SCHEMA,
        "merge": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["bodies", "plane_selection"],
)
def mirror_body(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    before = _feature_names(doc)
    require_selection(doc, args["plane_selection"], mark=MIRROR_MARK_PLANE)
    apply_selection(doc, {"bodies": list(args["bodies"])}, mark=MIRROR_MARK_BODY, append=True)
    with dialogs_suppressed():
        returned = feature_manager(doc).InsertMirrorFeature2(True, False, bool(args.get("merge", False)), False, 0)
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "mirror body", bodies_after=len(get_bodies(doc)))


@tool(
    "delete_body",
    "Delete solid bodies. keep=false (default) deletes the listed bodies; keep=true keeps the "
    "listed bodies and deletes all others.",
    {
        "bodies": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1},
        "keep": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["bodies"],
)
def delete_body(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    before = _feature_names(doc)
    apply_selection(doc, {"bodies": list(args["bodies"])})
    with dialogs_suppressed():
        returned = feature_manager(doc).InsertDeleteBody2(bool(args.get("keep", False)))
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "delete body", bodies_after=len(get_bodies(doc)))


@tool(
    "intersect_bodies",
    "Intersect the selected bodies/surfaces/planes (selection.bodies, planes, faces) and keep the "
    "resulting regions. Uses PreIntersect2/PostIntersect; all regions are kept. Unverified on 2017.",
    {
        "selection": SELECTION_SCHEMA,
        "merge": {"type": "boolean", "default": False, "description": "Merge the result into one body."},
        "consume": {"type": "boolean", "default": True, "description": "Consume the surface tools."},
        "cap_planar": {"type": "boolean", "default": True},
        "name": {"type": "string"},
    },
    ["selection"],
)
def intersect_bodies(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    before = _feature_names(doc)
    require_selection(doc, args["selection"])
    manager = feature_manager(doc)
    with dialogs_suppressed():
        started = manager.PreIntersect2(bool(args.get("cap_planar", True)), 0)
        if started is None or started is False:
            return result(False, "PreIntersect2 found no intersecting regions for the selection.")
        returned = manager.PostIntersect(empty_variant(), bool(args.get("merge", False)), bool(args.get("consume", True)))
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "intersect", bodies_after=len(get_bodies(doc)))


# --------------------------------------------------------------------------
# Shaping features
# --------------------------------------------------------------------------


@tool(
    "create_dome",
    "Dome the selected face (selection.faces=[i]) by height_mm; reverse=true domes inward; "
    "elliptical=true makes an elliptical rather than spherical dome.",
    {
        "selection": SELECTION_SCHEMA,
        "height_mm": {"type": "number", "exclusiveMinimum": 0},
        "reverse": {"type": "boolean", "default": False},
        "elliptical": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["selection", "height_mm"],
)
def create_dome(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    before = _feature_names(doc)
    # Live 2017: InsertDome (void) silently does nothing unless the face carries mark 1.
    require_selection(doc, args["selection"], mark=DOME_MARK_FACE)
    with dialogs_suppressed():
        returned = doc.InsertDome(
            to_m(args["height_mm"]), bool(args.get("reverse", False)), bool(args.get("elliptical", False))
        )
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "dome", height_mm=args["height_mm"])


@tool(
    "create_helix",
    "Create a helix or spiral from a circle sketch. defined_by: pitch_revolutions, "
    "height_revolutions, height_pitch, or spiral (pitch and revolutions; height ignored). Give the "
    "values that definition needs. taper_deg > 0 makes a tapered helix (outward flips the taper). "
    "The sketch must be closed (not being edited).",
    {
        "sketch": {"type": "string", "description": "Circle sketch; defaults to the newest sketch."},
        "defined_by": {"type": "string", "enum": sorted(HELIX_DEFINED_BY), "default": "height_pitch"},
        "height_mm": {"type": "number", "exclusiveMinimum": 0},
        "pitch_mm": {"type": "number", "exclusiveMinimum": 0},
        "revolutions": {"type": "number", "exclusiveMinimum": 0},
        "start_angle_deg": {"type": "number", "default": 0},
        "clockwise": {"type": "boolean", "default": True},
        "reverse": {"type": "boolean", "default": False},
        "taper_deg": {"type": "number", "default": 0},
        "outward": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
)
def create_helix(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    defined_by = str(args.get("defined_by", "height_pitch"))
    if defined_by not in HELIX_DEFINED_BY:
        return result(False, f"Unknown defined_by '{defined_by}'. Choose from {sorted(HELIX_DEFINED_BY)}.")
    needs = {
        "pitch_revolutions": ("pitch_mm", "revolutions"),
        "height_revolutions": ("height_mm", "revolutions"),
        "height_pitch": ("height_mm", "pitch_mm"),
        "spiral": ("pitch_mm", "revolutions"),
    }[defined_by]
    missing = [key for key in needs if args.get(key) is None]
    if missing:
        return result(False, f"defined_by={defined_by} needs {', '.join(missing)}.")
    before = _feature_names(doc)
    select_sketch_for_feature(doc, args.get("sketch"))
    taper = float(args.get("taper_deg", 0.0))
    with dialogs_suppressed():
        returned = doc.InsertHelix(
            bool(args.get("reverse", False)), bool(args.get("clockwise", True)), taper != 0.0,
            bool(args.get("outward", False)), HELIX_DEFINED_BY[defined_by],
            to_m(args.get("height_mm", 0.0)), to_m(args.get("pitch_mm", 0.0)),
            float(args.get("revolutions", 0.0)), to_rad(taper), to_rad(args.get("start_angle_deg", 0.0)),
        )
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "spiral" if defined_by == "spiral" else "helix")


@tool(
    "wrap_sketch",
    "Wrap a sketch onto a face: emboss (raised), deboss (cut into the face) or scribe (curves "
    "only). thickness_mm applies to emboss/deboss. Face is given in face_selection. Unverified on "
    "2017 until probed live.",
    {
        "sketch": {"type": "string"},
        "face_selection": SELECTION_SCHEMA,
        "wrap_type": {"type": "string", "enum": sorted(WRAP_TYPES), "default": "emboss"},
        "method": {"type": "string", "enum": sorted(WRAP_METHODS), "default": "spline_surface", "description": "Live 2017: analytical builds nothing on a cylinder; spline_surface works."},
        "thickness_mm": {"type": "number", "exclusiveMinimum": 0, "default": 1},
        "reverse": {"type": "boolean", "default": False},
        "mesh_factor": {"type": "integer", "minimum": 1, "maximum": 10, "default": 4},
        "name": {"type": "string"},
    },
    ["sketch", "face_selection"],
)
def wrap_sketch(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    wrap_type = str(args.get("wrap_type", "emboss"))
    method = str(args.get("method", "spline_surface"))
    if wrap_type not in WRAP_TYPES or method not in WRAP_METHODS:
        return result(False, f"Unknown wrap_type '{wrap_type}' or method '{method}'.")
    sketch_name, _ = resolve_sketch(doc, args["sketch"])
    before = _feature_names(doc)
    clear_selection(doc)
    if not select_by_id(doc, sketch_name, "SKETCH", WRAP_MARK_SKETCH, False):
        return result(False, f"Could not select sketch '{sketch_name}'.")
    require_selection(doc, args["face_selection"], mark=WRAP_MARK_FACE, append=True)
    with dialogs_suppressed():
        returned = feature_manager(doc).InsertWrapFeature2(
            WRAP_TYPES[wrap_type], to_m(args.get("thickness_mm", 1.0)), bool(args.get("reverse", False)),
            WRAP_METHODS[method], int(args.get("mesh_factor", 4)),
        )
    feature = _resolve(doc, returned, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, f"wrap ({wrap_type})")
