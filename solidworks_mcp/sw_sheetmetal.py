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

"""Batch C2 (part features): sheet metal base flange, edge flange, sketched bend, hem, fold/unfold/flatten and flat-pattern DXF export (plan items 2.1-2.6).

Every tool reports the feature-tree count, volume and bounding-box size before and
after, and fails when the expected measured change did not happen: several 2017
feature APIs return a feature object while building nothing, so a return value
is never taken as success.  Constants tagged LIVE-PROBE are the most likely
values for marks/arguments whose meaning the type library does not give; the
live pass confirms or corrects them.
"""

from __future__ import annotations

from typing import Any, Final

from .sw_core import (
    byref_long,
    clear_selection,
    dialogs_suppressed,
    dispatch_array,
    get_bodies,
    empty_variant,
    exit_active_sketch,
    extension,
    feature_manager,
    feature_property,
    feature_result,
    iter_edge_objects,
    iter_feature_objects,
    logger,
    nothing,
    register_flag_methods,
    rebuild,
    rename_feature,
    require_part,
    require_selection,
    resolve_sketch,
    result,
    safe,
    select_object,
    select_sketch_for_feature,
    selectable,
    SELECTION_SCHEMA,
    tool,
    to_m,
    to_rad,
    value,
)
from .sw_file import validated_output_path

register_flag_methods(
    "IFeatureManager",
    ["InsertSheetMetalBaseFlange2", "InsertSheetMetalEdgeFlange2", "InsertSheetMetalHem2", "CreateDefinition", "CreateFeature"],
)
register_flag_methods("IModelDoc2", ["InsertSheetMetalUnfold", "InsertSheetMetalFold"])
register_flag_methods("IPartDoc", ["ExportToDWG2"])

# swFeatureNameID_e.swFmSketchBend
FM_SKETCH_BEND: Final = 35
# swEndConditions_e.swEndCondBlind
SM_END_BLIND: Final = 0
# swSheetMetalReliefTypes_e.swSheetMetalReliefRectangular
SM_RELIEF_RECTANGULAR: Final = 1
# LIVE-PROBE: InsertSheetMetalBaseFlange2 DirToUse (1 = direction 1 only)
SM_BASE_FLANGE_DIR_TO_USE: Final = 1
# swFlangePositionTypes_e; also used for sketched-bend PositionType (LIVE-PROBE for the latter)
FLANGE_POSITIONS: Final = {
    "material_inside": 1, "material_outside": 2, "bend_outside": 3, "bend_centerline": 4,
    "bend_sharp": 5, "bend_tangent": 6,
}
# swInsertEdgeFlangeOptions_e bit flags (BooleanOptions)
EDGE_OPT_DEFAULT_RADIUS: Final = 1
EDGE_OPT_FLIP_DIR: Final = 2
EDGE_OPT_DO_OFFSET: Final = 4
EDGE_OPT_REVERSE_OFFSET: Final = 8
EDGE_OPT_DEFAULT_RELIEF: Final = 128
# LIVE-PROBE: FlangeSharpType (0 = keep the bend)
SM_FLANGE_SHARP_TYPE: Final = 0
# swHemTypes_e / swHemPositionTypes_e
HEM_TYPES: Final = {"open": 0, "closed": 1, "tear_drop": 2, "rolled": 3, "double": 4}
HEM_POSITIONS: Final = {"inside": 0, "outside": 1}
# swReliefTearTypes_e.swReliefTearTypeRip (LIVE-PROBE: only read when UseDefaultRelief is false)
SM_HEM_TEAR_RIP: Final = 1
# LIVE-PROBE: selection marks for InsertSheetMetalUnfold/Fold (fixed face, then bend faces/features)
SM_MARK_FIXED_FACE: Final = 1
SM_MARK_BENDS: Final = 2
# LIVE-PROBE: selection mark of the bend-line sketch for the swFmSketchBend CreateFeature
SB_MARK_SKETCH: Final = 0
# swExportToDWG_e.swExportToDWG_ExportSheetMetal
EXPORT_ACTION_SHEET_METAL: Final = 1
# LIVE-PROBE: ExportToDWG2 SheetMetalOptions bit flags (1 geometry, 4 bend lines, 8 sketches)
EXPORT_SM_GEOMETRY: Final = 1
EXPORT_SM_BEND_LINES: Final = 4
EXPORT_SM_SKETCHES: Final = 8
FLAT_PATTERN_TYPE: Final = "FlatPattern"
# A measured change smaller than this counts as "no change".
_EPS: Final = 1e-6
SM_ACTIONS: Final = ("unfold", "fold", "flatten", "unflatten")


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------


def part_snapshot(doc: Any) -> dict[str, Any]:
    """Feature-tree count, volume (mm3) and bounding-box size (mm) of the part.

    Each reading is best effort: a part with no solid yet has no volume, and
    the caller decides which readings matter.
    """
    snap: dict[str, Any] = {"features": len(iter_feature_objects(doc))}
    try:
        values = extension(doc).GetMassProperties2(2, byref_long(0), False)
        if values is not None and len(values) >= 6:
            snap["volume_mm3"] = round(float(values[3]) * 1e9, 4)
    except Exception:
        pass
    try:
        box = doc.GetPartBox(True)
        if box is not None and len(box) >= 6:
            snap["size_mm"] = [round((float(box[i + 3]) - float(box[i])) * 1000.0, 4) for i in range(3)]
    except Exception:
        pass
    return snap


def changed(before: dict[str, Any], after: dict[str, Any], kind: str) -> bool:
    """Did the measured quantity named by ``kind`` move?  (tree / volume_up / size / geometry)"""
    if kind == "tree":
        return after.get("features", 0) > before.get("features", 0)
    if kind == "volume_up":
        return after.get("volume_mm3", 0.0) > before.get("volume_mm3", 0.0) + _EPS
    if kind == "size":
        a, b = before.get("size_mm"), after.get("size_mm")
        return bool(a and b and any(abs(x - y) > 1e-3 for x, y in zip(a, b)))
    if kind == "geometry":
        return changed(before, after, "size") or abs(
            after.get("volume_mm3", 0.0) - before.get("volume_mm3", 0.0)
        ) > _EPS
    raise ValueError(kind)


def measured(doc: Any, feature: Any, action: str, before: dict[str, Any], expect: str, **data: Any) -> dict[str, Any]:
    """feature_result plus before/after readings; ok only if the expected change happened."""
    out = feature_result(doc, feature, action, **data)
    after = part_snapshot(doc)
    out.setdefault("data", {}).update(before=before, after=after)
    if feature is not None and out["ok"] and not changed(before, after, expect):
        out["ok"] = False
        out["message"] = (
            f"SOLIDWORKS returned a feature for the {action} but the model did not change "
            f"(expected: {expect}); treat it as a silent no-op."
        )
    return out


def _resolve_edges(doc: Any, spec: dict[str, Any] | None) -> list[Any]:
    indices = (spec or {}).get("edges") or []
    if not indices:
        raise RuntimeError("selection.edges is required (indices from list_edges).")
    objects = iter_edge_objects(doc)
    out = []
    for raw in indices:
        index = int(raw)
        if not 0 <= index < len(objects):
            raise RuntimeError(f"Edge index {index} is out of range (0..{len(objects) - 1}).")
        out.append(objects[index][0])
    return out


# --------------------------------------------------------------------------
# 2.1 Base flange
# --------------------------------------------------------------------------


@tool(
    "sheet_metal_base_flange",
    "Turn a profile sketch into a sheet-metal Base-Flange (adds the SheetMetal and Flat-Pattern "
    "features). The sketch is extruded depth_mm and given thickness_mm with bend_radius_mm. "
    "reverse flips the thickness side. Returns the feature-tree count, volume and bounding box "
    "before and after.",
    {
        "sketch": {"type": "string", "description": "Profile sketch; defaults to the newest sketch."},
        "thickness_mm": {"type": "number", "exclusiveMinimum": 0},
        "bend_radius_mm": {"type": "number", "exclusiveMinimum": 0},
        "depth_mm": {"type": "number", "exclusiveMinimum": 0},
        "reverse": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["thickness_mm", "bend_radius_mm", "depth_mm"],
)
def sheet_metal_base_flange(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    for key in ("thickness_mm", "bend_radius_mm", "depth_mm"):
        if args.get(key) is None or float(args[key]) <= 0:
            return result(False, f"{key} must be a positive number.")
    select_sketch_for_feature(doc, args.get("sketch"))
    before = part_snapshot(doc)
    with dialogs_suppressed():
        feature = feature_manager(doc).InsertSheetMetalBaseFlange2(
            to_m(args["thickness_mm"]), bool(args.get("reverse", False)), to_m(args["bend_radius_mm"]),
            to_m(args["depth_mm"]), 0.0, False, SM_END_BLIND, SM_END_BLIND, SM_BASE_FLANGE_DIR_TO_USE,
            nothing(),  # PCBA: default bend allowance (no ICustomBendAllowance)
            True, SM_RELIEF_RECTANGULAR, 0.0, 0.0, 0.5, True,  # relief: default, type, width, depth, ratio, use ratio
            # LIVE (C2): Merge=True makes 2017 return None for a first body; all-False works.
            False, False, False,  # Merge, UseFeatScope, UseAutoSelect
        )
    rename_feature(feature, args.get("name"))
    out = measured(doc, feature, "sheet-metal base flange", before, "tree",
                   thickness_mm=args["thickness_mm"], bend_radius_mm=args["bend_radius_mm"])
    if feature is not None and out["ok"]:
        # A tree entry alone is not a base flange: require one solid body with volume.
        volume = (out.get("data", {}).get("after") or {}).get("volume_mm3")
        try:
            bodies = len(get_bodies(doc))
        except Exception:
            bodies = None
        problems = []
        if volume is not None and volume <= 0:
            problems.append(f"volume is {volume} mm3")
        if bodies is not None and bodies != 1:
            problems.append(f"{bodies} solid bodies instead of 1")
        if problems:
            out["ok"] = False
            out["message"] = "Base flange feature exists but the model is wrong: " + "; ".join(problems) + "."
        out.setdefault("data", {}).update(solid_bodies=bodies)
    return out


# --------------------------------------------------------------------------
# 2.2 Edge flange
# --------------------------------------------------------------------------


@tool(
    "sheet_metal_edge_flange",
    "Add edge flanges to sheet-metal edges (selection.edges from list_edges). The flange length "
    "comes from one profile sketch per edge (profile_sketches, same order as the edges): "
    "the 2017 API has no length argument. position is where the flange sits relative to the "
    "edge; radius_mm omitted uses the part default. Fails when neither volume nor bounding box changed.",
    {
        "selection": SELECTION_SCHEMA,
        "profile_sketches": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "angle_deg": {"type": "number", "default": 90},
        "radius_mm": {"type": "number", "exclusiveMinimum": 0},
        "position": {"type": "string", "enum": sorted(FLANGE_POSITIONS), "default": "material_inside"},
        "offset_mm": {"type": "number", "default": 0},
        "flip": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["selection", "profile_sketches"],
)
def sheet_metal_edge_flange(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    position = str(args.get("position", "material_inside"))
    if position not in FLANGE_POSITIONS:
        return result(False, f"Unknown position '{position}'. Choose from {sorted(FLANGE_POSITIONS)}.")
    sketches = [str(s) for s in args.get("profile_sketches") or []]
    edge_indices = (args.get("selection") or {}).get("edges") or []
    if not sketches or len(sketches) != len(edge_indices):
        return result(False, "profile_sketches needs exactly one sketch per selected edge.")
    angle = float(args.get("angle_deg", 90.0))
    if not 0 < angle <= 180:
        return result(False, "angle_deg must be in (0, 180].")
    exit_active_sketch(doc)
    try:
        edges = _resolve_edges(doc, args["selection"])
        sketch_features = [resolve_sketch(doc, name)[1] for name in sketches]
    except RuntimeError as exc:
        return result(False, str(exc))
    options = EDGE_OPT_DEFAULT_RELIEF
    if args.get("radius_mm") is None:
        options |= EDGE_OPT_DEFAULT_RADIUS
    if bool(args.get("flip", False)):
        options |= EDGE_OPT_FLIP_DIR
    offset = float(args.get("offset_mm", 0.0))
    if offset:
        options |= EDGE_OPT_DO_OFFSET
        if offset < 0:
            options |= EDGE_OPT_REVERSE_OFFSET
    clear_selection(doc)
    before = part_snapshot(doc)
    with dialogs_suppressed():
        feature = feature_manager(doc).InsertSheetMetalEdgeFlange2(
            dispatch_array(edges), dispatch_array(sketch_features), options, to_rad(angle),
            to_m(args.get("radius_mm") or 0.0), FLANGE_POSITIONS[position], to_m(abs(offset)),
            SM_RELIEF_RECTANGULAR, 0.5, 0.0, 0.0, SM_FLANGE_SHARP_TYPE,
            nothing(),  # CustomBendAllowance
        )
    rename_feature(feature, args.get("name"))
    return measured(doc, feature, "sheet-metal edge flange", before, "geometry", angle_deg=angle, edges=len(edges))


# --------------------------------------------------------------------------
# 2.3 Sketched bend
# --------------------------------------------------------------------------


@tool(
    "sheet_metal_sketched_bend",
    "Bend a flat sheet-metal face along a sketched line (sketch holds one line crossing the face). "
    "fixed_point_mm is any point (x,y,z in mm) ON the face that stays put. Built through "
    "CreateDefinition(swFmSketchBend)/CreateFeature because 2017 has no Insert member. Fails "
    "when the bounding box and volume are both unchanged.",
    {
        "sketch": {"type": "string", "description": "Sketch with the bend line; defaults to the newest sketch."},
        "fixed_point_mm": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "angle_deg": {"type": "number", "default": 90},
        "radius_mm": {"type": "number", "exclusiveMinimum": 0},
        "position": {"type": "string", "enum": sorted(FLANGE_POSITIONS), "default": "bend_centerline"},
        "reverse": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["fixed_point_mm"],
)
def sheet_metal_sketched_bend(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    position = str(args.get("position", "bend_centerline"))
    point = args.get("fixed_point_mm")
    if position not in FLANGE_POSITIONS:
        return result(False, f"Unknown position '{position}'. Choose from {sorted(FLANGE_POSITIONS)}.")
    if not point or len(point) != 3:
        return result(False, "fixed_point_mm must be [x, y, z] in millimetres.")
    angle = float(args.get("angle_deg", 90.0))
    if angle == 0 or abs(angle) > 180:
        return result(False, "angle_deg must be non-zero and within +/-180.")
    exit_active_sketch(doc)
    sketch_name, sketch = resolve_sketch(doc, args.get("sketch"))
    clear_selection(doc)
    if not select_object(doc, sketch, SB_MARK_SKETCH, False):
        return result(False, f"Could not select sketch '{sketch_name}'.")
    before = part_snapshot(doc)
    with dialogs_suppressed():
        manager = feature_manager(doc)
        data = manager.CreateDefinition(FM_SKETCH_BEND)
        if data is None:
            return result(False, "SOLIDWORKS returned no definition for a sketched bend (swFmSketchBend).", before=before)
        data.BendAngle = to_rad(angle)
        data.PositionType = FLANGE_POSITIONS[position]
        data.ReverseDirection = bool(args.get("reverse", False))
        if args.get("radius_mm") is not None:
            data.UseDefaultBendRadius = False
            data.BendRadius = to_m(args["radius_mm"])
        else:
            data.UseDefaultBendRadius = True
        data.UseDefaultBendAllowance = True
        data.SetFixedFace(to_m(point[0]), to_m(point[1]), to_m(point[2]), nothing())
        feature = manager.CreateFeature(data)
    rename_feature(feature, args.get("name"))
    return measured(doc, feature, "sketched bend", before, "geometry", angle_deg=angle)


# --------------------------------------------------------------------------
# 2.4 Hem
# --------------------------------------------------------------------------


@tool(
    "sheet_metal_hem",
    "Add a hem to the selected sheet-metal edge (selection.edges). type: open, closed, tear_drop, "
    "rolled or double. length_mm is the hem length, gap_mm the gap of open/closed hems, angle_deg "
    "the open-hem angle, radius_mm the tear-drop/rolled radius. Fails when the volume did not grow.",
    {
        "selection": SELECTION_SCHEMA,
        "type": {"type": "string", "enum": sorted(HEM_TYPES), "default": "closed"},
        "position": {"type": "string", "enum": sorted(HEM_POSITIONS), "default": "inside"},
        "length_mm": {"type": "number", "exclusiveMinimum": 0},
        "gap_mm": {"type": "number", "minimum": 0, "default": 0.1},
        "angle_deg": {"type": "number", "default": 180},
        "radius_mm": {"type": "number", "exclusiveMinimum": 0, "default": 1},
        "miter_gap_mm": {"type": "number", "minimum": 0, "default": 0.1},
        "reverse": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["selection", "length_mm"],
)
def sheet_metal_hem(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    kind = str(args.get("type", "closed"))
    position = str(args.get("position", "inside"))
    if kind not in HEM_TYPES or position not in HEM_POSITIONS:
        return result(False, f"Unknown hem type '{kind}' or position '{position}'.")
    if float(args.get("length_mm") or 0) <= 0 or float(args.get("radius_mm", 1)) <= 0:
        return result(False, "length_mm and radius_mm must be positive.")
    if float(args.get("gap_mm", 0.1)) < 0 or float(args.get("miter_gap_mm", 0.1)) < 0:
        return result(False, "gap_mm and miter_gap_mm must not be negative.")
    if args.get("length_mm") is None or float(args["length_mm"]) <= 0:
        return result(False, "length_mm must be a positive number.")
    if not (args.get("selection") or {}).get("edges"):
        return result(False, "selection.edges is required (the edge to hem).")
    exit_active_sketch(doc)
    require_selection(doc, args["selection"])
    before = part_snapshot(doc)
    with dialogs_suppressed():
        feature = feature_manager(doc).InsertSheetMetalHem2(
            HEM_TYPES[kind], HEM_POSITIONS[position], bool(args.get("reverse", False)),
            to_m(args["length_mm"]), to_m(args.get("gap_mm", 0.1)), to_rad(args.get("angle_deg", 180.0)),
            to_m(args.get("radius_mm", 1.0)), to_m(args.get("miter_gap_mm", 0.1)),
            nothing(),  # PCBA
            True, SM_RELIEF_RECTANGULAR, SM_HEM_TEAR_RIP, True, 0.5, 0.0, 0.0,  # relief block
        )
    rename_feature(feature, args.get("name"))
    return measured(doc, feature, f"{kind} hem", before, "volume_up", length_mm=args["length_mm"])


# --------------------------------------------------------------------------
# 2.5 Fold / unfold / flatten
# --------------------------------------------------------------------------


def _flat_pattern(doc: Any) -> Any | None:
    for feature in iter_feature_objects(doc):
        if str(feature_property(feature, "GetTypeName2", "")) == FLAT_PATTERN_TYPE:
            return feature
    return None


@tool(
    "sheet_metal_fold_unfold",
    "Unfold or fold selected bends, or flatten/unflatten the whole part. unfold/fold need "
    "fixed_face (selection.faces) and bends (selection of bend faces or features). flatten "
    "unsuppresses the Flat-Pattern feature (part shows flat); unflatten suppresses it again. "
    "Fails when the bounding box did not change.",
    {
        "action": {"type": "string", "enum": list(SM_ACTIONS)},
        "fixed_face": SELECTION_SCHEMA,
        "bends": SELECTION_SCHEMA,
    },
    ["action"],
)
def sheet_metal_fold_unfold(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    action = str(args["action"])
    if action not in SM_ACTIONS:
        return result(False, f"Unknown action '{action}'. Choose from {list(SM_ACTIONS)}.")
    if action in ("unfold", "fold") and not (args.get("fixed_face") and args.get("bends")):
        return result(False, f"action={action} needs fixed_face and bends.")
    exit_active_sketch(doc)
    before = part_snapshot(doc)
    if action in ("flatten", "unflatten"):
        flat = _flat_pattern(doc)
        if flat is None:
            return result(False, "The part has no Flat-Pattern feature; it is not a sheet-metal part.", before=before)
        clear_selection(doc)
        if not bool(selectable(flat).Select2(False, 0)):
            return result(False, "Could not select the Flat-Pattern feature.", before=before)
        with dialogs_suppressed():
            ok = bool(value(doc, "EditSuppress2" if action == "unflatten" else "EditUnsuppress2"))
    else:
        require_selection(doc, args["fixed_face"], mark=SM_MARK_FIXED_FACE)
        require_selection(doc, args["bends"], mark=SM_MARK_BENDS, append=True)
        with dialogs_suppressed():
            value(doc, "InsertSheetMetalUnfold" if action == "unfold" else "InsertSheetMetalFold")
        ok = True  # both members return void; only the measurement below decides
    rebuild(doc)
    clear_selection(doc)
    after = part_snapshot(doc)
    moved = changed(before, after, "size")
    return result(
        bool(ok and moved),
        f"{action} {'changed' if moved else 'did not change'} the bounding box.",
        before=before, after=after,
    )


# --------------------------------------------------------------------------
# 2.6 Flat-pattern DXF export
# --------------------------------------------------------------------------


@tool(
    "export_flat_pattern",
    "Export the flat pattern of a saved sheet-metal part to a DXF under the server output root. "
    "path is relative to the output root or absolute inside it; overwrite replaces an existing file. "
    "include_bend_lines / include_sketches add those layers. Verified by file size and a DXF "
    "ENTITIES section.",
    {
        "path": {"type": "string", "description": "Output .dxf path under the output root."},
        "include_bend_lines": {"type": "boolean", "default": True},
        "include_sketches": {"type": "boolean", "default": False},
        "overwrite": {"type": "boolean", "default": False},
    },
    ["path"],
)
def export_flat_pattern(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    try:
        output = validated_output_path(str(args["path"]), {".dxf"}, bool(args.get("overwrite", False)))
    except RuntimeError as exc:
        return result(False, str(exc))
    if _flat_pattern(doc) is None:
        return result(False, "The part has no Flat-Pattern feature; it is not a sheet-metal part.")
    model_path = str(safe(doc, "GetPathName", "") or "")
    if not model_path:
        return result(False, "Save the part first: ExportToDWG2 needs the model's file path.")
    options = EXPORT_SM_GEOMETRY
    if bool(args.get("include_bend_lines", True)):
        options |= EXPORT_SM_BEND_LINES
    if bool(args.get("include_sketches", False)):
        options |= EXPORT_SM_SKETCHES
    with dialogs_suppressed():
        ok = bool(doc.ExportToDWG2(
            str(output), model_path, EXPORT_ACTION_SHEET_METAL, True, empty_variant(), False, False,
            options, empty_variant(),
        ))
    size = output.stat().st_size if output.is_file() else 0
    has_entities = False
    if size:
        try:
            has_entities = b"ENTITIES" in output.read_bytes()
        except OSError:
            logger.info("Could not read back %s", output)
    return result(
        bool(size and has_entities),
        f"Wrote {output} ({size} bytes)." if size else f"ExportToDWG2 (returned {ok}) wrote no file at {output}.",
        path=str(output), size_bytes=size, entities_section=has_entities, api_returned=ok,
    )
