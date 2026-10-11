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

"""Solid features: extrude, revolve, fillet, chamfer, shell, sweep, loft, rib,
draft, holes, patterns, and mirror.

Every feature that needs topology takes the same declarative ``selection``
object, so the agent never has to reason about SOLIDWORKS' implicit global
selection set or about which mark a given API expects.
"""

from __future__ import annotations

import math
from typing import Any, Final

from .sw_core import (
    active_document,
    apply_selection,
    call_versioned,
    CHAMFER_ANGLE_DISTANCE,
    CHAMFER_DISTANCE_DISTANCE,
    CHAMFER_EQUAL_DISTANCE,
    CHAMFER_TANGENT_PROPAGATION,
    as_list,
    clear_selection,
    dialogs_suppressed,
    double_array,
    empty_variant,
    END_CONDITIONS,
    exit_active_sketch,
    extension,
    feature_manager,
    feature_property,
    feature_result,
    FILLET_PROPAGATE,
    FILLET_TYPE_SIMPLE,
    FILLET_UNIFORM_RADIUS,
    find_feature,
    get_bodies,
    iter_features,
    iter_feature_objects,
    logger,
    rebuild,
    rename_feature,
    safe,
    select_at_point,
    select_object,
    require_part,
    require_selection,
    result,
    selectable,
    SELECTION_SCHEMA,
    select_sketch_for_feature,
    tool,
    to_m,
    to_rad,
    value,
    whats_wrong,
)


def _feature_names(doc: Any) -> list[str]:
    return [f["name"] for f in iter_features(doc)]


def _feature_created_after(doc: Any, before: list[str]) -> Any | None:
    """Recover the new feature for the SOLIDWORKS APIs that return void."""
    previous = set(before)
    for feature in reversed(iter_feature_objects(doc)):
        name = str(feature_property(feature, "Name", ""))
        if name and name not in previous:
            return feature
    return None


_END_CONDITION_SCHEMA = {
    "type": "string",
    "enum": sorted(END_CONDITIONS),
    "default": "blind",
    "description": "End condition. blind uses depth_mm; through_all/through_next ignore it.",
}

_SKETCH_ARG = {
    "type": "string",
    "description": "Which sketch to use as the profile. Defaults to the most recently created sketch.",
}


def _two_direction_end_conditions(condition: int) -> tuple[bool, int, int]:
    """Translate the public ``through_all_both`` end condition for feature APIs.

    ``FeatureExtrusion3`` and ``FeatureCut4`` do not honour
    ``swEndCondThroughAllBoth`` when it is supplied as the first end condition
    of a single-ended feature.  They create only the forward half of the
    feature, without a rebuild error.  The API represents the intended result
    as a two-direction feature with ``through all`` on both sides instead.
    """
    if condition == END_CONDITIONS["through_all_both"]:
        through_all = END_CONDITIONS["through_all"]
        return False, through_all, through_all
    return True, condition, 0


# --------------------------------------------------------------------------
# Extrude and cut
# --------------------------------------------------------------------------


_END_CONDITION2_SCHEMA = {k: v for k, v in _END_CONDITION_SCHEMA.items() if k != "default"}
_END_CONDITION2_SCHEMA["description"] = "Enables a second direction (not mid_plane / through_all_both)."

_TARGET_SCHEMA = {
    "type": "object",
    "description": (
        "Names the entity an up_to_* / offset_from_surface end condition stops at. Give ONE of: "
        "face (index from list_faces), vertex (index from list_vertices), body (index from "
        "list_bodies), body_name, feature + face_index (n-th face of that feature), or point "
        "{x_mm,y_mm,z_mm,type} (coordinates on a face/vertex)."
    ),
    "properties": {
        "face": {"type": "integer"},
        "vertex": {"type": "integer"},
        "body": {"type": "integer"},
        "body_name": {"type": "string"},
        "feature": {"type": "string"},
        "face_index": {"type": "integer", "default": 0},
        "point": {
            "type": "object",
            "properties": {
                "x_mm": {"type": "number"}, "y_mm": {"type": "number"}, "z_mm": {"type": "number"},
                "type": {"type": "string", "enum": ["FACE", "VERTEX", "EDGE"], "default": "FACE"},
            },
            "required": ["x_mm", "y_mm", "z_mm"],
        },
    },
}

_THIN_SCHEMA = {
    "type": "object",
    "description": "Thin feature. type: one_direction, mid_plane (thickness split evenly) or two_directions.",
    "properties": {
        "thickness_mm": {"type": "number", "exclusiveMinimum": 0},
        "type": {"type": "string", "enum": ["one_direction", "mid_plane", "two_directions"], "default": "one_direction"},
        "thickness2_mm": {"type": "number", "exclusiveMinimum": 0, "description": "Second wall (two_directions)."},
        "reverse": {"type": "boolean", "default": False, "description": "Put the wall on the other side of the profile."},
        "cap_ends": {"type": "boolean", "default": False},
        "cap_thickness_mm": {"type": "number", "exclusiveMinimum": 0},
    },
    "required": ["thickness_mm"],
}

_TARGET_END_CONDITIONS = frozenset(
    {"up_to_vertex", "up_to_surface", "offset_from_surface", "up_to_body"}
)

# Selection marks the extrude/cut APIs read an end-condition entity from
# (direction 1 / direction 2).  Verify the second mark live; see the batch A report.
_mark_end_dir1 = 1
_mark_end_dir2 = 2


def _target_to_selection(doc: Any, target: dict[str, Any]) -> dict[str, Any]:
    """Turn the friendly ``target`` object into an apply_selection spec."""
    if target.get("face") is not None:
        return {"faces": [int(target["face"])]}
    if target.get("vertex") is not None:
        return {"vertices": [int(target["vertex"])]}
    if target.get("body") is not None:
        return {"bodies": [int(target["body"])]}
    if target.get("body_name"):
        wanted = str(target["body_name"]).lower()
        for index, body in enumerate(get_bodies(doc)):
            if str(safe(body, "Name", "")).lower() == wanted:
                return {"bodies": [index]}
        raise RuntimeError(f"No solid body named '{target['body_name']}'. Use list_bodies.")
    if target.get("feature"):
        face_index = int(target.get("face_index", 0))
        feature = find_feature(doc, str(target["feature"]))
        if feature is None:
            raise RuntimeError(f"No feature named '{target['feature']}'.")
        faces = as_list(safe(feature, "GetFaces"))
        if not 0 <= face_index < len(faces):
            raise RuntimeError(
                f"Feature '{target['feature']}' has {len(faces)} faces; face_index {face_index} is out of range."
            )
        return {"_objects": [faces[face_index]]}
    if target.get("point"):
        p = target["point"]
        return {"points": [{
            "x_mm": p["x_mm"], "y_mm": p["y_mm"], "z_mm": p["z_mm"], "type": p.get("type", "FACE"),
        }]}
    raise RuntimeError("target needs one of: face, vertex, body, body_name, feature, point.")


def _select_target(doc: Any, target: dict[str, Any] | None, mark: int) -> None:
    if not target:
        raise RuntimeError("This end condition needs a 'target' naming the face/vertex/body to stop at.")
    spec = _target_to_selection(doc, target)
    if "_objects" in spec:
        if not all(select_object(doc, obj, mark, True) for obj in spec["_objects"]):
            raise RuntimeError("Could not select the end-condition target.")
        return
    require_selection(doc, spec, mark=mark, append=True)


class _ExtrudePlan:
    """Parsed, validated extrude/cut arguments shared by boss and cut."""

    def __init__(self, args: dict[str, Any]) -> None:
        self.args = args
        name1 = str(args.get("end_condition", "blind"))
        if name1 not in END_CONDITIONS:
            raise RuntimeError(f"Unknown end_condition '{name1}'.")
        self.name1 = name1
        raw2 = args.get("end_condition2")
        self.name2 = str(raw2) if raw2 else None
        if self.name2 is not None:
            if self.name2 not in END_CONDITIONS or self.name2 in ("mid_plane", "through_all_both"):
                raise RuntimeError(f"end_condition2 '{self.name2}' is not valid for a second direction.")
            if name1 in ("mid_plane", "through_all_both"):
                raise RuntimeError(f"A second direction cannot be combined with end_condition '{name1}'.")
        cond1 = END_CONDITIONS[name1]
        if self.name2 is None:
            self.single, self.cond1, self.cond2 = _two_direction_end_conditions(cond1)
        else:
            self.single, self.cond1, self.cond2 = False, cond1, END_CONDITIONS[self.name2]
        self.depth1 = to_m(args.get("depth_mm", 10))
        # A blind/offset second direction defaults to the first depth.
        self.depth2 = to_m(args.get("depth2_mm", args.get("depth_mm", 10)))
        self.draft1 = to_rad(args.get("draft_deg", 0))
        self.draft2 = to_rad(args.get("draft2_deg", 0))
        self.thin = args.get("thin") or None
        if name1 == "through_all_both" and self.thin:
            raise RuntimeError("through_all_both cannot be combined with thin; use mid_plane or two directions.")

    @property
    def has_draft1(self) -> bool:
        return abs(self.draft1) > 1e-12

    @property
    def has_draft2(self) -> bool:
        return abs(self.draft2) > 1e-12 and not self.single

    def select_targets(self, doc: Any) -> None:
        """Append end-condition entities after the profile sketch is selected."""
        if self.name1 in _TARGET_END_CONDITIONS:
            _select_target(doc, self.args.get("target"), _mark_end_dir1)
        if self.name2 and self.name2 in _TARGET_END_CONDITIONS:
            _select_target(doc, self.args.get("target2"), _mark_end_dir2)

    def thin_values(self) -> tuple[float, float, float, int, bool]:
        """Return (thk1, thk2, end_thk, thin_type, cap_ends); thicknesses in metres.

        FeatureExtrusionThin2/FeatureCutThin2 have no separate thin-type argument:
        the ``RevThinDir`` integer is a swThinWallType_e (0 one direction, 1 opposite,
        2 mid-plane, 3 two directions).  Thk1 is the total wall for mid-plane.
        """
        thin = self.thin or {}
        t1 = to_m(thin["thickness_mm"])
        kind = str(thin.get("type", "one_direction"))
        if kind == "mid_plane":
            t2, thin_type = 0.0, 2
        elif kind == "two_directions":
            if thin.get("thickness2_mm") is None:
                raise RuntimeError("thin.type two_directions needs thickness2_mm.")
            t2, thin_type = to_m(thin["thickness2_mm"]), 3
        elif kind == "one_direction":
            t2, thin_type = 0.0, (1 if thin.get("reverse") else 0)
        else:
            raise RuntimeError(f"Unknown thin.type '{kind}'.")
        cap = bool(thin.get("cap_ends", False))
        end_thk = to_m(thin["cap_thickness_mm"]) if thin.get("cap_thickness_mm") else (t1 if cap else 0.0)
        return t1, t2, end_thk, thin_type, cap

    def head(self, flip: bool, reverse: bool) -> list[Any]:
        """The 17 leading positional arguments shared by Extrusion3/Thin2/Cut4/CutThin2."""
        return [
            self.single, flip, reverse,
            self.cond1, self.cond2, self.depth1, self.depth2,
            self.has_draft1, self.has_draft2,
            bool(self.args.get("draft_outward", False)), bool(self.args.get("draft2_outward", False)),
            self.draft1, self.draft2,
            bool(self.args.get("offset_reverse", False)), bool(self.args.get("offset2_reverse", False)),
            False, False,
        ]

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"end_condition": self.name1}
        if self.name2:
            info["end_condition2"] = self.name2
        if self.thin:
            info["thin"] = self.thin
        return info


_NO_START_OFFSET = (0, 0.0, False)  # T0 = blind start from the sketch plane


@tool(
    "boss_extrude",
    "Extrude a sketch into a solid boss. Depth is millimetres, draft is degrees. Supports every end "
    "condition (blind, through_all, through_all_both, through_next, up_to_vertex, up_to_surface, "
    "offset_from_surface, up_to_body, mid_plane); name the stop entity with target. Optional second "
    "direction (end_condition2, depth2_mm, draft2_deg, target2) and thin feature.",
    {
        "depth_mm": {"type": "number", "exclusiveMinimum": 0, "default": 10,
                     "description": "Depth; for offset_from_surface this is the offset distance."},
        "sketch_name": _SKETCH_ARG,
        "end_condition": _END_CONDITION_SCHEMA,
        "target": _TARGET_SCHEMA,
        "offset_reverse": {"type": "boolean", "default": False, "description": "Flip the surface offset direction."},
        "reverse": {"type": "boolean", "default": False, "description": "Extrude the other way."},
        "end_condition2": _END_CONDITION2_SCHEMA,
        "depth2_mm": {"type": "number", "exclusiveMinimum": 0},
        "target2": _TARGET_SCHEMA,
        "offset2_reverse": {"type": "boolean", "default": False},
        "draft_deg": {"type": "number", "default": 0},
        "draft_outward": {"type": "boolean", "default": False, "description": "Draft outward instead of inward."},
        "draft2_deg": {"type": "number", "default": 0},
        "draft2_outward": {"type": "boolean", "default": False},
        "thin": _THIN_SCHEMA,
        "merge": {"type": "boolean", "default": True, "description": "Merge with existing solid bodies."},
        "name": {"type": "string", "description": "Rename the resulting feature."},
    },
)
def boss_extrude(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    plan = _ExtrudePlan(args)
    sketch = select_sketch_for_feature(doc, args.get("sketch_name"))
    plan.select_targets(doc)
    merge = bool(args.get("merge", True))
    head = plan.head(False, bool(args.get("reverse", False)))

    with dialogs_suppressed():
        if plan.thin:
            thk1, thk2, end_thk, thin_type, cap = plan.thin_values()
            feature = feature_manager(doc).FeatureExtrusionThin2(
                *head, merge, thk1, thk2, end_thk, thin_type, cap,
                False, 0.0,
                True, True,
                *_NO_START_OFFSET,
            )
        else:
            feature = feature_manager(doc).FeatureExtrusion3(
                *head, merge, True, True,
                *_NO_START_OFFSET,
            )
    rename_feature(feature, args.get("name"))
    return feature_result(
        doc, feature, "boss extrusion", sketch=sketch, depth_mm=args.get("depth_mm", 10), **plan.describe()
    )


@tool(
    "cut_extrude",
    "Cut material using a sketch profile. Depth is millimetres, draft is degrees. Same end conditions, "
    "target, second direction and thin options as boss_extrude; flip_side cuts outside the profile.",
    {
        "depth_mm": {"type": "number", "exclusiveMinimum": 0, "default": 10},
        "sketch_name": _SKETCH_ARG,
        "end_condition": _END_CONDITION_SCHEMA,
        "target": _TARGET_SCHEMA,
        "offset_reverse": {"type": "boolean", "default": False},
        "reverse": {"type": "boolean", "default": False},
        "flip_side": {"type": "boolean", "default": False, "description": "Cut everything outside the profile instead."},
        "end_condition2": _END_CONDITION2_SCHEMA,
        "depth2_mm": {"type": "number", "exclusiveMinimum": 0},
        "target2": _TARGET_SCHEMA,
        "offset2_reverse": {"type": "boolean", "default": False},
        "draft_deg": {"type": "number", "default": 0},
        "draft_outward": {"type": "boolean", "default": False},
        "draft2_deg": {"type": "number", "default": 0},
        "draft2_outward": {"type": "boolean", "default": False},
        "thin": _THIN_SCHEMA,
        "name": {"type": "string"},
    },
)
def cut_extrude(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    plan = _ExtrudePlan(args)
    flip_side = bool(args.get("flip_side", False))
    requested = bool(args.get("reverse", False))

    def attempt(reverse: bool) -> tuple[str, Any]:
        name = select_sketch_for_feature(doc, args.get("sketch_name"))
        plan.select_targets(doc)
        head = plan.head(flip_side, reverse)
        if plan.thin:
            thk1, thk2, end_thk, thin_type, cap = plan.thin_values()
            return name, feature_manager(doc).FeatureCutThin2(
                *head, thk1, thk2, end_thk, thin_type, cap,
                False, 0.0,
                True, True,
                *_NO_START_OFFSET,
            )
        cut_args = (
            *head, False, True, True,
            False, False, False,
            *_NO_START_OFFSET, False,
        )
        # FeatureCut3 (2014-2016 builds) takes the same list without the
        # trailing OptimizeGeometry flag.
        return name, call_versioned(
            feature_manager(doc),
            ("FeatureCut4", cut_args),
            ("FeatureCut3", cut_args[:26]),
        )

    with dialogs_suppressed():
        sketch, feature = attempt(requested)
        reversed_automatically = False
        if feature is None:
            # Which way "forward" points depends on the sketch plane's orientation,
            # and a sketch lying on a boundary face of the body cuts into thin air.
            # A cut that removes nothing is unambiguous, so try the other way.
            sketch, feature = attempt(not requested)
            reversed_automatically = feature is not None

    rename_feature(feature, args.get("name"))
    payload = feature_result(
        doc, feature, "cut", sketch=sketch, depth_mm=args.get("depth_mm", 10), **plan.describe()
    )
    if reversed_automatically:
        payload["data"]["reversed_automatically"] = True
        payload["message"] += " The requested direction removed nothing, so it was cut the other way."
    elif feature is None:
        payload["message"] += (
            " Neither direction removed material: check that the profile actually overlaps the body."
        )
    return payload


@tool(
    "revolve",
    "Revolve a sketch profile about an axis. If the sketch contains exactly one centerline "
    "SOLIDWORKS uses it automatically; otherwise pass axis_selection (a sketch_segments index for "
    "the centerline, or an axes name). Angle is degrees. Optional second direction (angle2_deg), "
    "mid_plane, or a thin wall.",
    {
        "angle_deg": {"type": "number", "default": 360, "exclusiveMinimum": 0, "maximum": 360},
        "angle2_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 360,
                       "description": "Enables a second direction with this angle."},
        "sketch_name": _SKETCH_ARG,
        "axis_selection": SELECTION_SCHEMA,
        "cut": {"type": "boolean", "default": False, "description": "Remove material instead of adding it."},
        "reverse": {"type": "boolean", "default": False},
        "mid_plane": {"type": "boolean", "default": False, "description": "Revolve symmetrically about the sketch plane."},
        "thin": _THIN_SCHEMA,
        "merge": {"type": "boolean", "default": True},
        "name": {"type": "string"},
    },
)
def revolve(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    mid_plane = bool(args.get("mid_plane", False))
    two_directions = bool(args.get("angle2_deg"))
    if mid_plane and two_directions:
        raise RuntimeError("mid_plane and angle2_deg are mutually exclusive.")
    sketch = select_sketch_for_feature(doc, args.get("sketch_name"))
    axis_spec = args.get("axis_selection")
    if axis_spec:
        # Mark 4 is what FeatureRevolve2 reads the axis from; append so the
        # profile selection made above survives.
        require_selection(doc, axis_spec, mark=4, append=True)

    angle = to_rad(args.get("angle_deg", 360))
    angle2 = to_rad(args["angle2_deg"]) if two_directions else 0.0
    single_direction = not (mid_plane or two_directions)
    # FeatureRevolve2.Dir1Type is swEndConditions_e: 6 = swEndCondMidPlane. (4 would be
    # swEndCondUpToSurface; 4 is only mid-plane in swRevolveType_e, a different enum.)
    direction_type = 6 if mid_plane else 0

    thin = args.get("thin") or None
    thin_type, thk1, thk2 = 0, 0.0, 0.0
    if thin:
        kinds = {"one_direction": 0, "mid_plane": 2, "two_directions": 3}  # swThinWallType_e
        kind = str(thin.get("type", "one_direction"))
        if kind not in kinds:
            raise RuntimeError(f"Unknown thin.type '{kind}'.")
        thin_type = kinds[kind]
        thk1 = to_m(thin["thickness_mm"])
        if kind == "two_directions":
            if thin.get("thickness2_mm") is None:
                raise RuntimeError("thin.type two_directions needs thickness2_mm.")
            thk2 = to_m(thin["thickness2_mm"])
        if thin.get("reverse") and kind == "one_direction":
            thin_type = 1  # swThinWallOppDirection

    with dialogs_suppressed():
        feature = feature_manager(doc).FeatureRevolve2(
            single_direction, True, bool(thin), bool(args.get("cut", False)),
            bool(args.get("reverse", False)), False,
            direction_type, 0, angle, angle2,
            False, False, 0.0, 0.0,
            thin_type, thk1, thk2,
            bool(args.get("merge", True)), True, True,
        )
    rename_feature(feature, args.get("name"))
    extra: dict[str, Any] = {}
    if two_directions:
        extra["angle2_deg"] = args["angle2_deg"]
    if thin:
        extra["thin"] = thin
    return feature_result(doc, feature, "revolve", sketch=sketch, angle_deg=args.get("angle_deg", 360), **extra)


# --------------------------------------------------------------------------
# Dress-up features
# --------------------------------------------------------------------------


@tool(
    "fillet",
    "Round the selected edges or faces with a constant radius, in millimetres. "
    "Use list_edges to find the edge indices, or selection.face_edges to fillet every edge of a face.",
    {
        "radius_mm": {"type": "number", "exclusiveMinimum": 0},
        "selection": SELECTION_SCHEMA,
        "propagate": {"type": "boolean", "default": True, "description": "Continue across tangent faces."},
        "keep_features": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["radius_mm", "selection"],
)
def fillet(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    count = require_selection(doc, args["selection"])
    options = FILLET_UNIFORM_RADIUS
    if bool(args.get("propagate", True)):
        options |= FILLET_PROPAGATE

    feature = feature_manager(doc).FeatureFillet3(
        options, to_m(args["radius_mm"]), 0.0, 0.0,
        FILLET_TYPE_SIMPLE, 0, 0,
        empty_variant(), empty_variant(), empty_variant(),
        empty_variant(), empty_variant(), empty_variant(), empty_variant(),
    )
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "fillet", radius_mm=args["radius_mm"], entities=count)


@tool(
    "chamfer",
    "Chamfer the selected edges or faces. equal_distance uses distance_mm on both sides; "
    "angle_distance uses distance_mm and angle_deg; distance_distance uses both distances. "
    "SOLIDWORKS 2017 builds nothing for the native equal-distance type, so equal_distance is "
    "substituted with angle_distance at 45 degrees and the same distance (identical geometry); "
    "the result reports data.substituted.",
    {
        "distance_mm": {"type": "number", "exclusiveMinimum": 0},
        "selection": SELECTION_SCHEMA,
        "mode": {
            "type": "string",
            "enum": ["equal_distance", "angle_distance", "distance_distance"],
            "default": "equal_distance",
        },
        "angle_deg": {"type": "number", "default": 45},
        "other_distance_mm": {"type": "number", "description": "Second distance for distance_distance."},
        "propagate": {"type": "boolean", "default": True},
        "flip": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["distance_mm", "selection"],
)
def chamfer(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    count = require_selection(doc, args["selection"])
    mode = str(args.get("mode", "equal_distance"))
    angle_deg = args.get("angle_deg", 45)
    substituted: str | None = None
    if mode == "equal_distance":
        # 2017's InsertFeatureChamfer silently builds nothing for type 16
        # (equal distance): the feature appears but the geometry is unchanged.
        # A 45 degree angle-distance chamfer is the same shape, so use that.
        mode, angle_deg, substituted = "angle_distance", 45, "angle_distance 45°"
    chamfer_type = {
        "equal_distance": CHAMFER_EQUAL_DISTANCE,
        "angle_distance": CHAMFER_ANGLE_DISTANCE,
        "distance_distance": CHAMFER_DISTANCE_DISTANCE,
    }[mode]
    options = CHAMFER_TANGENT_PROPAGATION if bool(args.get("propagate", True)) else 0
    if bool(args.get("flip", False)):
        options |= 1  # swFeatureChamferFlipDirection
    other = to_m(args.get("other_distance_mm", args["distance_mm"]))

    feature = feature_manager(doc).InsertFeatureChamfer(
        options, chamfer_type, to_m(args["distance_mm"]),
        to_rad(angle_deg), other,
        0.0, 0.0, 0.0,
    )
    rename_feature(feature, args.get("name"))
    payload = feature_result(doc, feature, "chamfer", distance_mm=args["distance_mm"], entities=count)
    if substituted:
        payload.setdefault("data", {})["substituted"] = substituted
        payload["message"] += f" (equal_distance is not built by SOLIDWORKS 2017; used {substituted}.)"
    return payload


@tool(
    "shell",
    "Hollow the part to a wall thickness in millimetres. Pass selection with the faces to remove; "
    "omit it to hollow the body with no opening.",
    {
        "thickness_mm": {"type": "number", "exclusiveMinimum": 0},
        "selection": SELECTION_SCHEMA,
        "outward": {"type": "boolean", "default": False, "description": "Thicken outward instead of inward."},
        "name": {"type": "string"},
    },
    ["thickness_mm"],
)
def shell(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    before = _feature_names(doc)
    removed = 0
    if args.get("selection"):
        removed = apply_selection(doc, args["selection"])
    else:
        clear_selection(doc)

    doc.InsertFeatureShell(to_m(args["thickness_mm"]), bool(args.get("outward", False)))
    feature = _feature_created_after(doc, before)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "shell", thickness_mm=args["thickness_mm"], removed_faces=removed)


@tool(
    "draft",
    "Apply draft to the selected faces about a neutral plane or face. Angle is degrees. "
    "Put the faces to draft in selection and the neutral reference in neutral_selection.",
    {
        "angle_deg": {"type": "number", "exclusiveMinimum": 0, "default": 3},
        "selection": SELECTION_SCHEMA,
        "neutral_selection": SELECTION_SCHEMA,
        "reverse": {
            "type": "boolean",
            "default": False,
            "description": "False tapers the face outward, adding material below the neutral plane; "
                           "True tapers it inward and removes material. For a moulded part you "
                           "normally want True.",
        },
        "name": {"type": "string"},
    },
    ["angle_deg", "selection", "neutral_selection"],
)
def draft(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    # Mark 1 is the neutral plane, mark 2 the faces being drafted.
    require_selection(doc, args["neutral_selection"], mark=1)
    faces = require_selection(doc, args["selection"], mark=2, append=True)

    feature = feature_manager(doc).InsertMultiFaceDraft(
        to_rad(args["angle_deg"]), bool(args.get("reverse", False)), False, 0, False, False
    )
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "draft", angle_deg=args["angle_deg"], faces=faces)


@tool(
    "rib",
    "Turn an open sketch profile into a rib of the given thickness in millimetres. The usual setup "
    "is a single line drawn on the cross-section plane, bridging two existing faces — the profile "
    "must reach material at both ends or SOLIDWORKS creates nothing.",
    {
        "thickness_mm": {"type": "number", "exclusiveMinimum": 0},
        "sketch_name": _SKETCH_ARG,
        "two_sided": {"type": "boolean", "default": True, "description": "Thicken symmetrically about the sketch."},
        "reverse_material": {"type": "boolean", "default": False, "description": "Flip which way the rib grows."},
        "extrude_direction": {
            "type": "string",
            "enum": ["parallel_to_sketch", "normal_to_sketch"],
            "default": "parallel_to_sketch",
            "description": "How the profile reaches the material. A cross-section profile wants "
                           "parallel_to_sketch; the other is tried automatically if this one builds nothing.",
        },
        "draft_deg": {"type": "number", "default": 0},
        "name": {"type": "string"},
    },
    ["thickness_mm"],
)
def rib(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    draft_deg = float(args.get("draft_deg", 0))
    requested = str(args.get("extrude_direction", "parallel_to_sketch")) == "normal_to_sketch"

    requested_reverse = bool(args.get("reverse_material", False))

    def attempt(normal_to_sketch: bool, reverse_material: bool) -> tuple[str, Any]:
        name = select_sketch_for_feature(doc, args.get("sketch_name"))
        before = _feature_names(doc)
        feature_manager(doc).InsertRib(
            bool(args.get("two_sided", True)), False, to_m(args["thickness_mm"]), 0,
            reverse_material,
            abs(draft_deg) > 1e-12, False, to_rad(draft_deg),
            normal_to_sketch, False,
        )
        return name, _feature_created_after(doc, before)

    # InsertRib returns void and simply builds nothing when either the extrusion
    # direction or the material side is wrong, so try all four combinations
    # (requested one first, then flipping direction, then material side, then
    # both).  A corner gusset whose material side is the non-default one never
    # built when only the direction was retried.  Bounded at four attempts.
    combos = [
        (requested, requested_reverse),
        (not requested, requested_reverse),
        (requested, not requested_reverse),
        (not requested, not requested_reverse),
    ]
    sketch, feature, used_combo = "", None, combos[0]
    for combo in combos:
        sketch, feature = attempt(*combo)
        used_combo = combo
        if feature is not None:
            break

    rename_feature(feature, args.get("name"))
    payload = feature_result(doc, feature, "rib", sketch=sketch, thickness_mm=args["thickness_mm"])
    if feature is not None:
        direction = "normal_to_sketch" if used_combo[0] else "parallel_to_sketch"
        payload["data"]["extrude_direction"] = direction
        payload["data"]["reverse_material"] = used_combo[1]
        if used_combo != combos[0]:
            payload["data"]["retried"] = True
            payload["message"] += (
                f" The requested settings built nothing, so extrude_direction={direction}, "
                f"reverse_material={used_combo[1]} was used."
            )
    else:
        payload["message"] += (
            " No combination of extrusion direction and material side reached material: check that "
            "the profile spans between two existing faces."
        )
    return payload


@tool(
    "simple_hole",
    "Cut a straight hole of a given diameter into a face. Put the face and the hole centre in "
    "selection, most simply as a points entry with type FACE at the hole location.",
    {
        "diameter_mm": {"type": "number", "exclusiveMinimum": 0},
        "selection": SELECTION_SCHEMA,
        "depth_mm": {"type": "number", "exclusiveMinimum": 0, "default": 10},
        "end_condition": _END_CONDITION_SCHEMA,
        "reverse": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["diameter_mm", "selection"],
)
def simple_hole(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    require_selection(doc, args["selection"])
    condition = END_CONDITIONS[str(args.get("end_condition", "blind"))]
    depth = to_m(args.get("depth_mm", 10))

    feature = feature_manager(doc).SimpleHole2(
        to_m(args["diameter_mm"]), True, False, bool(args.get("reverse", False)),
        condition, 0, depth, 0.0,
        False, False, False, False, 0.0, 0.0,
        False, False, False, False,
        True, True, False, False, False,
    )
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "hole", diameter_mm=args["diameter_mm"])


# --------------------------------------------------------------------------
# Swept and lofted features
# --------------------------------------------------------------------------


@tool(
    "sweep",
    "Sweep a closed profile sketch along a path sketch.",
    {
        "profile_sketch": {"type": "string", "description": "Sketch feature name of the closed profile."},
        "path_sketch": {"type": "string", "description": "Sketch feature name of the path."},
        "cut": {"type": "boolean", "default": False},
        "merge": {"type": "boolean", "default": True},
        "keep_tangency": {"type": "boolean", "default": False},
        "twist_angle_deg": {"type": "number", "default": 0},
        "name": {"type": "string"},
    },
    ["profile_sketch", "path_sketch"],
)
def sweep(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    # The sweep APIs read the profile from mark 1 and the path from mark 4.
    require_selection(doc, {"sketches": [str(args["profile_sketch"])]}, mark=1)
    require_selection(doc, {"sketches": [str(args["path_sketch"])]}, mark=4, append=True)

    manager = feature_manager(doc)
    keep_tangency = bool(args.get("keep_tangency", False))
    twist = to_rad(args.get("twist_angle_deg", 0))
    if bool(args.get("cut", False)):
        # InsertCutSwept5 has no Merge flag but does carry assembly scope flags.
        # InsertCutSwept4 (2016) is the same list without the last three.
        cut_args = (
            False, True, 0, keep_tangency, False,
            0, 0, False, 0.0, 0.0, 0, 0,
            True, True, twist, False,
            False, False, False,
            False, 0.0, 0,
        )
        feature = call_versioned(
            manager,
            ("InsertCutSwept5", cut_args),
            ("InsertCutSwept4", cut_args[:19]),
        )
    else:
        # InsertProtrusionSwept3 (2016) stops after BMergeSmoothFaces.
        boss_args = (
            False, True, 0, keep_tangency, False,
            0, 0, False, 0.0, 0.0, 0, 0,
            bool(args.get("merge", True)), True, True,
            twist, False, False, 0.0, 0,
        )
        feature = call_versioned(
            manager,
            ("InsertProtrusionSwept4", boss_args),
            ("InsertProtrusionSwept3", boss_args[:17]),
        )
    rename_feature(feature, args.get("name"))
    return feature_result(
        doc, feature, "sweep",
        profile=str(args["profile_sketch"]), path=str(args["path_sketch"]),
    )


@tool(
    "loft",
    "Loft a solid through two or more profile sketches, in the order given.",
    {
        "profile_sketches": {
            "type": "array",
            "minItems": 2,
            "items": {"type": "string"},
            "description": "Sketch feature names, ordered from one end of the loft to the other.",
        },
        "cut": {"type": "boolean", "default": False},
        "closed": {"type": "boolean", "default": False},
        "keep_tangency": {"type": "boolean", "default": False},
        "merge": {"type": "boolean", "default": True},
        "name": {"type": "string"},
    },
    ["profile_sketches"],
)
def loft(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    profiles = [str(name) for name in args["profile_sketches"]]
    clear_selection(doc)
    for index, name in enumerate(profiles):
        require_selection(doc, {"sketches": [name]}, mark=1, append=index > 0)

    manager = feature_manager(doc)
    closed = bool(args.get("closed", False))
    keep_tangency = bool(args.get("keep_tangency", False))
    if bool(args.get("cut", False)):
        # InsertCutBlend takes neither tangent-length nor merge arguments.
        feature = manager.InsertCutBlend(
            closed, keep_tangency, False, 1.0,
            0, 0, False, 0.0, 0.0, 0, True, True,
        )
    else:
        feature = manager.InsertProtrusionBlend2(
            closed, keep_tangency, False, 1.0,
            0, 0, 0.0, 0.0, True, True,
            False, 0.0, 0.0, 0,
            bool(args.get("merge", True)), True, True, 0,
        )
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "loft", profiles=profiles)


# --------------------------------------------------------------------------
# Patterns and mirror
# --------------------------------------------------------------------------


@tool(
    "linear_pattern",
    "Repeat features along one or two directions. Put the features to repeat in selection and the "
    "direction reference (an edge, axis, or plane) in direction1_selection. Spacing is millimetres.",
    {
        "selection": SELECTION_SCHEMA,
        "direction1_selection": SELECTION_SCHEMA,
        "count1": {"type": "integer", "minimum": 2, "default": 2},
        "spacing1_mm": {"type": "number", "exclusiveMinimum": 0},
        "reverse1": {"type": "boolean", "default": False},
        "direction2_selection": SELECTION_SCHEMA,
        "count2": {"type": "integer", "minimum": 1, "default": 1},
        "spacing2_mm": {"type": "number", "default": 0},
        "reverse2": {"type": "boolean", "default": False},
        "geometry_pattern": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["selection", "direction1_selection", "spacing1_mm"],
)
def linear_pattern(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    # Marks: 1 = direction 1, 2 = direction 2, 4 = the features being patterned.
    require_selection(doc, args["direction1_selection"], mark=1)
    has_second = bool(args.get("direction2_selection")) and int(args.get("count2", 1)) > 1
    if has_second:
        require_selection(doc, args["direction2_selection"], mark=2, append=True)
    require_selection(doc, args["selection"], mark=4, append=True)

    pattern_args = (
        int(args.get("count1", 2)), to_m(args["spacing1_mm"]),
        int(args.get("count2", 1)) if has_second else 1,
        to_m(args.get("spacing2_mm", 0)) if has_second else 0.0,
        bool(args.get("reverse1", False)), bool(args.get("reverse2", False)),
        "", "",
        bool(args.get("geometry_pattern", False)), False,
        False, False, True, True, False, False, False, False, 0.0, 0.0,
        False, False,
    )
    # FeatureLinearPattern4 (2016) ends at Offset2, i.e. the first 20 arguments.
    feature = call_versioned(
        feature_manager(doc),
        ("FeatureLinearPattern5", pattern_args),
        ("FeatureLinearPattern4", pattern_args[:20]),
    )
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "linear pattern", count1=int(args.get("count1", 2)))


@tool(
    "circular_pattern",
    "Repeat features around an axis. Put the features in selection and the axis (a reference axis, "
    "a cylindrical face, or a straight edge) in axis_selection. Angle is degrees.",
    {
        "selection": SELECTION_SCHEMA,
        "axis_selection": SELECTION_SCHEMA,
        "count": {"type": "integer", "minimum": 2, "default": 4},
        "angle_deg": {"type": "number", "default": 360, "description": "Total spread when equal_spacing is true, otherwise the step angle."},
        "equal_spacing": {"type": "boolean", "default": True},
        "reverse": {"type": "boolean", "default": False},
        "geometry_pattern": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["selection", "axis_selection"],
)
def circular_pattern(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    # Marks: 1 = the pattern axis, 4 = the features being patterned.
    require_selection(doc, args["axis_selection"], mark=1)
    require_selection(doc, args["selection"], mark=4, append=True)

    # SOLIDWORKS always stores a per-instance step; for equal spacing it wants
    # the full spread, which it then divides internally.
    spacing = to_rad(args.get("angle_deg", 360))
    pattern_args = (
        int(args.get("count", 4)), spacing,
        bool(args.get("reverse", False)), "",
        bool(args.get("geometry_pattern", False)),
        bool(args.get("equal_spacing", True)), False, False,
        False, False, 1, 0.0, "", False,
    )
    # FeatureCircularPattern4 (2016) ends at VaryInstance, the first 7 arguments.
    feature = call_versioned(
        feature_manager(doc),
        ("FeatureCircularPattern5", pattern_args),
        ("FeatureCircularPattern4", pattern_args[:7]),
    )
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "circular pattern", count=int(args.get("count", 4)))


@tool(
    "mirror_feature",
    "Mirror features (or whole bodies) about a plane or planar face. Put the features in selection "
    "and the mirror plane in plane_selection.",
    {
        "selection": SELECTION_SCHEMA,
        "plane_selection": SELECTION_SCHEMA,
        "mirror_body": {"type": "boolean", "default": False, "description": "Mirror the whole body instead of features."},
        "merge": {"type": "boolean", "default": True},
        "geometry_pattern": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["selection", "plane_selection"],
)
def mirror_feature(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    # Marks: 2 = the mirror plane, 1 = the features being mirrored.
    require_selection(doc, args["plane_selection"], mark=2)
    require_selection(doc, args["selection"], mark=1, append=True)

    feature = feature_manager(doc).InsertMirrorFeature2(
        bool(args.get("mirror_body", False)),
        bool(args.get("geometry_pattern", False)),
        bool(args.get("merge", True)),
        False, 0,
    )
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "mirror")


# --------------------------------------------------------------------------
# Feature-tree maintenance
# --------------------------------------------------------------------------


@tool(
    "delete_feature",
    "Delete named features from the feature tree, together with anything that depends on them.",
    {"feature_names": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
    ["feature_names"],
)
def delete_feature(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    exit_active_sketch(doc)
    clear_selection(doc)
    names = [str(name) for name in args["feature_names"]]
    selected: list[str] = []
    for name in names:
        feature = find_feature(doc, name)
        if feature is None:
            return result(False, f"No feature named '{name}' exists in this document.")
        if bool(selectable(feature).Select2(True, 0)):
            selected.append(name)
    if not selected:
        return result(False, "Could not select any of the named features.")
    deleted = bool(extension(doc).DeleteSelection2(0))
    rebuild(doc)
    clear_selection(doc)
    return result(
        deleted,
        f"Deleted {len(selected)} features." if deleted else "SOLIDWORKS refused to delete the selection.",
        deleted=selected,
    )


@tool(
    "rename_feature",
    "Rename a feature so later tool calls can refer to it stably.",
    {"feature_name": {"type": "string"}, "new_name": {"type": "string"}},
    ["feature_name", "new_name"],
)
def rename_feature_tool(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    feature = find_feature(doc, str(args["feature_name"]))
    if feature is None:
        return result(False, f"No feature named '{args['feature_name']}' exists in this document.")
    feature.Name = str(args["new_name"])
    return result(True, f"Renamed to '{args['new_name']}'.", feature=str(args["new_name"]))


@tool(
    "set_feature_suppression",
    "Suppress or unsuppress named features.",
    {
        "feature_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "suppressed": {"type": "boolean", "default": True},
    },
    ["feature_names"],
)
def set_feature_suppression(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    exit_active_sketch(doc)
    suppressed = bool(args.get("suppressed", True))
    changed: list[str] = []
    for name in args["feature_names"]:
        feature = find_feature(doc, str(name))
        if feature is None:
            return result(False, f"No feature named '{name}' exists in this document.")
        clear_selection(doc)
        if not bool(selectable(feature).Select2(False, 0)):
            return result(False, f"Could not select feature '{name}'.")
        # These take no arguments, and pywin32 may already have evaluated them
        # on attribute access, so go through value() rather than calling.
        ok = bool(value(doc, "EditSuppress2" if suppressed else "EditUnsuppress2"))
        if ok:
            changed.append(str(name))
    rebuild(doc)
    clear_selection(doc)
    return result(
        bool(changed),
        f"{'Suppressed' if suppressed else 'Unsuppressed'} {len(changed)} features.",
        changed=changed,
        problems=whats_wrong(doc),
    )


# --------------------------------------------------------------------------
# Batch B: Hole Wizard, cosmetic thread, fillet variants, vertex chamfer.
# Constants carry a Final annotation (not a bare assignment) on purpose: they
# are checked against sw2017_enums.txt by tests/test_sw2017_batchB_geometry.py,
# and test_sw2017_enums only audits bare module-level assignments.
# --------------------------------------------------------------------------

# swWzdGeneralHoleTypes_e
HOLE_KINDS: Final = {"counterbore": 0, "countersink": 1, "hole": 2, "pipe_tap": 3, "tap": 4}
# swWzdHoleStandards_e
HOLE_STANDARDS: Final = {
    "ansi_inch": 0, "ansi_metric": 1, "bsi": 2, "din": 4, "iso": 8, "jis": 9, "gb": 13,
}
# swWzdHoleStandardFastenerTypes_e, per standard, by what the hole is for.  Only the
# standards that are complete on 2017 are tabulated; any other passes
# fastener_type_index straight through.
HOLE_FASTENERS: Final = {
    "ansi_inch": {"tapped": 27, "drill": 19, "clearance": 22, "tap_drill": 23, "socket_head": 9, "flat_head": 15},
    "ansi_metric": {"tapped": 43, "drill": 39, "clearance": 40, "tap_drill": 41, "socket_head": 33, "flat_head": 36},
    "iso": {"tapped": 147, "drill": 143, "clearance": 144, "tap_drill": 145, "socket_head": 139, "flat_head": 140},
}
# What a kind of hole defaults to when fastener is not given.
HOLE_DEFAULT_FASTENER: Final = {
    "counterbore": "socket_head", "countersink": "flat_head", "hole": "clearance",
    "tap": "tapped", "pipe_tap": "tapped",
}
# swEndConditions_e subset the wizard honours
HOLE_END: Final = {"blind": 0, "through_all": 1, "through_next": 2}
# swFeatureFilletType_e / swFeatureFilletOptions_e
FILLET_TYPE_VARIABLE: Final = 1
FILLET_TYPE_FACE: Final = 2
FILLET_TYPE_FULL_ROUND: Final = 3
FILLET_OPT_VARIABLE_RADIUS: Final = 4
# Selection marks for face and full-round fillets (swSimpleFilletWhichFaces_e)
FILLET_MARK_FACE_SET1: Final = 1
# Live 2017: mark 2 builds nothing for set 2; mark 4 does (set 1 = mark 1 confirmed by geometry)
FILLET_MARK_FACE_SET2: Final = 4
FILLET_MARK_ROUND_SET1: Final = 3
FILLET_MARK_ROUND_CENTER: Final = 4
FILLET_MARK_ROUND_SET2: Final = 5
# swChamferType_e
CHAMFER_VERTEX: Final = 3
# swCosmeticThreadType_e
COSMETIC_END: Final = {"blind": 0, "up_to_next": 1, "through": 2}


def _hole_values(kind: str, args: dict[str, Any]) -> list[float]:
    """Value1..Value12 for HoleWizard5.

    Slot mapping verified live on 2017 by reading the feature definition back:
    counterbore = Value1 diameter, Value2 depth; countersink = Value1 diameter,
    Value2 angle (radians); tapped = Value1 thread depth.  ``raw_values_mm``
    overrides everything.
    """
    raw = args.get("raw_values_mm")
    if raw:
        values = [to_m(float(v)) for v in raw][:12]
        return values + [0.0] * (12 - len(values))
    values = [0.0] * 12
    if kind == "counterbore":
        values[0] = to_m(args.get("cbore_diameter_mm", 0.0))
        values[1] = to_m(args.get("cbore_depth_mm", 0.0))
    elif kind == "countersink":
        values[0] = to_m(args.get("csink_diameter_mm", 0.0))
        values[1] = to_rad(args.get("csink_angle_deg", 90.0))
    if kind in ("tap", "pipe_tap"):
        # Live 2017 (read back through IWizardHoleFeatureData2): Value1 is the thread depth for a
        # tapped hole; Value2 is the near-side countersink diameter. A zero thread depth makes the
        # wizard fall back to a bogus 2 in thread, so default it to the drill depth.
        thread = args.get("thread_depth_mm") or args.get("depth_mm") or 0.0
        values[0] = to_m(thread)
        # Value6 must be non-zero (any value works, probed 0.001 to 2.0): with 0 the wizard
        # ignores the size string and builds a 2 in thread.  Treated as an on/off flag.
        values[5] = 1.0
    return values


@tool(
    "hole_wizard",
    "Insert a Hole Wizard hole (counterbore, countersink, straight hole, tapped hole) on a planar "
    "face at one or more points, one feature per point. Each point (x_mm,y_mm,z_mm) must lie ON "
    "the target face; the tool selects the face there. standard is ansi_inch, ansi_metric, iso, "
    "din, jis, bsi or gb; fastener picks the wizard's fastener table (tapped, drill, clearance, "
    "tap_drill, socket_head, flat_head; tabulated for ansi_inch/ansi_metric/iso, otherwise give "
    "fastener_type_index). size is the wizard size string such as 'M6x1'. diameter_mm is the hole "
    "(or tap drill) diameter. Value1/2 mapping is verified on 2017 (cbore/csink); raw_values_mm overrides. "
    "Tapped sizes are the wizard strings ('M6x1.0', '1/4-20'). The wizard adds no cosmetic thread through the "
    "API (IWizardHoleFeatureData2.CosmeticThreadType is read-only): call cosmetic_thread on the hole edge.",
    {
        "kind": {"type": "string", "enum": sorted(HOLE_KINDS), "default": "hole"},
        "standard": {"type": "string", "enum": sorted(HOLE_STANDARDS), "default": "iso"},
        "fastener": {"type": "string", "enum": ["tapped", "drill", "clearance", "tap_drill", "socket_head", "flat_head"]},
        "fastener_type_index": {"type": "integer", "description": "Raw swWzdHoleStandardFastenerTypes_e value; overrides fastener."},
        "size": {"type": "string", "description": "Wizard size string, e.g. 'M6x1'."},
        "points": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {"x_mm": {"type": "number"}, "y_mm": {"type": "number"}, "z_mm": {"type": "number"}},
                "required": ["x_mm", "y_mm", "z_mm"],
            },
        },
        "diameter_mm": {"type": "number", "exclusiveMinimum": 0},
        "end_condition": {"type": "string", "enum": sorted(HOLE_END), "default": "blind"},
        "depth_mm": {"type": "number", "exclusiveMinimum": 0},
        "cbore_diameter_mm": {"type": "number"},
        "cbore_depth_mm": {"type": "number"},
        "csink_diameter_mm": {"type": "number"},
        "csink_angle_deg": {"type": "number", "default": 90},
        "thread_depth_mm": {"type": "number"},
        "thread_class": {"type": "string", "default": ""},
        "reverse": {"type": "boolean", "default": False},
        "raw_values_mm": {"type": "array", "items": {"type": "number"}, "maxItems": 12},
        "name": {"type": "string"},
    },
    ["points", "size", "diameter_mm"],
)
def hole_wizard(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    kind = str(args.get("kind", "hole"))
    standard = str(args.get("standard", "iso"))
    if kind not in HOLE_KINDS or standard not in HOLE_STANDARDS:
        return result(False, f"Unknown kind '{kind}' or standard '{standard}'.")
    if args.get("fastener_type_index") is not None:
        fastener_index = int(args["fastener_type_index"])
    else:
        table = HOLE_FASTENERS.get(standard)
        if table is None:
            return result(False, f"Standard '{standard}' has no fastener table here; pass fastener_type_index.")
        fastener = str(args.get("fastener") or HOLE_DEFAULT_FASTENER[kind])
        if fastener not in table:
            return result(False, f"Unknown fastener '{fastener}'. Choose from {sorted(table)}.")
        fastener_index = table[fastener]
    end_name = str(args.get("end_condition", "blind"))
    if end_name == "blind" and args.get("depth_mm") is None:
        return result(False, "end_condition=blind needs depth_mm.")
    depth = to_m(args.get("depth_mm") or 0.0)
    values = _hole_values(kind, args)

    created: list[str] = []
    feature: Any = None
    for point in args["points"]:
        clear_selection(doc)
        coords = [to_m(point["x_mm"]), to_m(point["y_mm"]), to_m(point["z_mm"])]
        if not select_at_point(doc, "FACE", coords, 0, False):
            return result(False, f"No face at point {point}; hole not created.", created=created)
        with dialogs_suppressed():
            feature = feature_manager(doc).HoleWizard5(
                HOLE_KINDS[kind], HOLE_STANDARDS[standard], fastener_index, str(args["size"]),
                HOLE_END[end_name], to_m(args["diameter_mm"]), depth, depth,
                *values,
                str(args.get("thread_class", "")), bool(args.get("reverse", False)),
                True, True, True, True, False,
            )
        if feature is None:
            return feature_result(doc, None, "Hole Wizard hole", point=point, created=created)
        if len(args["points"]) == 1:
            rename_feature(feature, args.get("name"))
        created.append(str(feature_property(feature, "Name", "")))
    return feature_result(doc, feature, "Hole Wizard hole", kind=kind, standard=standard,
                          size=args["size"], created=created)


@tool(
    "cosmetic_thread",
    "Add a cosmetic thread to a circular edge (selection.edges=[i]). standard is the integer "
    "thread-standard index (live 2017: 0 ANSI Inch, 1 ANSI Metric, 2 ISO, 4 another metric table); "
    "standard_type and size are the strings the UI shows ('Machine threads', 'M6x1.0'). Unrecognised strings "
    "silently fall back to the first table entry (size '2-4.5'), so verify the readback. diameter_mm is the thread diameter.",
    {
        "selection": SELECTION_SCHEMA,
        "standard": {"type": "integer", "default": 0},
        "standard_type": {"type": "string"},
        "size": {"type": "string"},
        "diameter_mm": {"type": "number", "exclusiveMinimum": 0},
        "end_condition": {"type": "string", "enum": sorted(COSMETIC_END), "default": "blind"},
        "depth_mm": {"type": "number", "default": 0},
        "note": {"type": "string", "default": ""},
        "name": {"type": "string"},
    },
    ["selection", "standard_type", "size", "diameter_mm"],
)
def cosmetic_thread(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    require_selection(doc, args["selection"])
    with dialogs_suppressed():
        feature = feature_manager(doc).InsertCosmeticThread3(
            int(args.get("standard", 0)), str(args["standard_type"]), str(args["size"]),
            to_m(args["diameter_mm"]), COSMETIC_END[str(args.get("end_condition", "blind"))],
            to_m(args.get("depth_mm", 0.0)), str(args.get("note", "")),
        )
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "cosmetic thread", size=args["size"])


@tool(
    "fillet_variant",
    "Fillet types beyond the constant-radius edge fillet. variable: selection.edges plus "
    "radius_mm (start) and end_radius_mm. face: face_set_1 and face_set_2 (selection specs with "
    "faces) plus radius_mm. full_round is not supported on 2017 and is refused.",
    {
        "type": {"type": "string", "enum": ["variable", "face", "full_round"]},
        "selection": SELECTION_SCHEMA,
        "radius_mm": {"type": "number", "exclusiveMinimum": 0},
        "end_radius_mm": {"type": "number", "exclusiveMinimum": 0},
        "face_set_1": SELECTION_SCHEMA,
        "face_set_2": SELECTION_SCHEMA,
        "side_set_1": SELECTION_SCHEMA,
        "center": SELECTION_SCHEMA,
        "side_set_2": SELECTION_SCHEMA,
        "propagate": {"type": "boolean", "default": True},
        "name": {"type": "string"},
    },
    ["type"],
)
def fillet_variant(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    kind = str(args["type"])
    radius = args.get("radius_mm")
    options = FILLET_PROPAGATE if bool(args.get("propagate", True)) else 0
    point_radii: Any = empty_variant()
    edge_radii: Any = empty_variant()

    if kind == "variable":
        if radius is None or args.get("end_radius_mm") is None or not args.get("selection"):
            return result(False, "type=variable needs selection (edges), radius_mm and end_radius_mm.")
        require_selection(doc, args["selection"])
        options |= FILLET_OPT_VARIABLE_RADIUS
        ftype = FILLET_TYPE_VARIABLE
        # Live 2017: the start/end radii go in the Radii argument (PointRadiusArray built nothing).
        edge_radii = double_array([to_m(radius), to_m(args["end_radius_mm"])])
    elif kind == "face":
        if radius is None or not (args.get("face_set_1") and args.get("face_set_2")):
            return result(False, "type=face needs radius_mm, face_set_1 and face_set_2.")
        require_selection(doc, args["face_set_1"], mark=FILLET_MARK_FACE_SET1)
        require_selection(doc, args["face_set_2"], mark=FILLET_MARK_FACE_SET2, append=True)
        # Live 2017: UniformRadius (2) in the options builds nothing for a face fillet.
        ftype = FILLET_TYPE_FACE
    elif kind == "full_round":
        # Live 2017: FeatureFillet3 with type 3 never builds a full-round fillet; whatever the marks
        # (1/2/4, 3/4/5, 2/4/1), options (0..16384) or radius, it makes one plain edge fillet of
        # radius_mm instead.  Refused rather than returning the wrong geometry.
        return result(False, "Not supported on SOLIDWORKS 2017: full_round fillets are not built by FeatureFillet3 "
                      "(it makes a single constant-radius edge fillet); fillet each edge with the fillet tool instead.",
                      fenced=True)
    else:
        return result(False, f"Unknown fillet type '{kind}'.")

    with dialogs_suppressed():
        feature = feature_manager(doc).FeatureFillet3(
            options, to_m(radius or 0.0), 0.0, 0.0, ftype, 0, 0,
            edge_radii, empty_variant(), empty_variant(),
            empty_variant(), point_radii, empty_variant(), empty_variant(),
        )
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, f"{kind} fillet")


@tool(
    "chamfer_vertex",
    "Chamfer the selected vertex (selection.vertices=[i]) with three distances along its edges. "
    "distance_mm applies to all three unless distance2_mm/distance3_mm are given.",
    {
        "selection": SELECTION_SCHEMA,
        "distance_mm": {"type": "number", "exclusiveMinimum": 0},
        "distance2_mm": {"type": "number", "exclusiveMinimum": 0},
        "distance3_mm": {"type": "number", "exclusiveMinimum": 0},
        "name": {"type": "string"},
    },
    ["selection", "distance_mm"],
)
def chamfer_vertex(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    exit_active_sketch(doc)
    require_selection(doc, args["selection"])
    d1 = to_m(args["distance_mm"])
    d2 = to_m(args.get("distance2_mm", args["distance_mm"]))
    d3 = to_m(args.get("distance3_mm", args["distance_mm"]))
    with dialogs_suppressed():
        feature = feature_manager(doc).InsertFeatureChamfer(0, CHAMFER_VERTEX, d1, 0.0, 0.0, d1, d2, d3)
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, "vertex chamfer", distance_mm=args["distance_mm"])
