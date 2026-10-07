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

"""Multibody editing, surface construction and helix curves."""

import math
from .sw_core import (
    BODY_SHEET, SELECTION_SCHEMA, dispatch_array,
    feature_manager, feature_result, flag_methods, get_bodies, nothing,
    rename_feature, require_part, require_selection, result,
    select_sketch_for_feature, to_m, to_rad, tool, as_list, value,
)
from .sw_feature import _feature_created_after, _feature_names

BODY_SELECTION = {"type": "object", "properties": {"bodies": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1, "uniqueItems": True}}, "required": ["bodies"], "additionalProperties": False}
NAME = {"type": "string"}
NUM = {"type": "number", "default": 0}


def _positive(raw, label):
    number = float(raw)
    if not math.isfinite(number) or number <= 0:
        raise RuntimeError(f"{label} must be finite and positive.")
    return number


def _selected_bodies(doc, selection, minimum=1, mark=0):
    indices = selection.get("bodies", [])
    if len(indices) < minimum or len(set(indices)) != len(indices):
        raise RuntimeError(f"Select at least {minimum} distinct solid bodies from list_bodies.")
    if set(selection) != {"bodies"}:
        raise RuntimeError("This tool accepts only selection.bodies.")
    bodies = get_bodies(doc)
    if any(not isinstance(i, int) or i < 0 or i >= len(bodies) for i in indices):
        raise RuntimeError("Body index is out of range. Use list_bodies again.")
    require_selection(doc, selection, mark=mark)
    return [bodies[i] for i in indices]


def _finish(doc, feature, args, action, **data):
    rename_feature(feature, args.get("name"))
    return feature_result(doc, feature, action, **data)


@tool("scale_bodies", "Scale selected solid bodies uniformly or along X/Y/Z about their centroid or the model origin. Re-list topology afterwards.",
      {"selection": BODY_SELECTION, "factor": {"type": "number", "exclusiveMinimum": 0, "default": 1},
       "uniform": {"type": "boolean", "default": True}, "y_factor": {"type": "number", "exclusiveMinimum": 0, "default": 1},
       "z_factor": {"type": "number", "exclusiveMinimum": 0, "default": 1}, "about": {"type": "string", "enum": ["centroid", "origin"], "default": "centroid"}, "name": NAME}, ["selection"])
def scale_bodies(args):
    x = _positive(args.get("factor", 1), "factor")
    uniform = bool(args.get("uniform", True))
    y = x if uniform else _positive(args.get("y_factor", 1), "y_factor")
    z = x if uniform else _positive(args.get("z_factor", 1), "z_factor")
    about = {"centroid": 0, "origin": 1}[args.get("about", "centroid")]
    _, doc = require_part()
    _selected_bodies(doc, args["selection"])
    manager = flag_methods(feature_manager(doc), "InsertScale")
    return _finish(doc, manager.InsertScale(about, uniform, x, y, z), args, "body scale", factors=[x, y, z])


@tool("move_copy_bodies", "Translate OR rotate selected solid bodies, optionally copying them. Use separate calls for translation and rotation. Lengths in mm, rotations in degrees around the supplied point. Copies must be >=1 when copy=true.",
      {"selection": BODY_SELECTION, "x_mm": NUM, "y_mm": NUM, "z_mm": NUM,
       "rotation_x_deg": NUM, "rotation_y_deg": NUM, "rotation_z_deg": NUM,
       "rotation_point_x_mm": NUM, "rotation_point_y_mm": NUM, "rotation_point_z_mm": NUM,
       "copy": {"type": "boolean", "default": False}, "copies": {"type": "integer", "minimum": 1, "maximum": 100, "default": 1}, "name": NAME}, ["selection"])
def move_copy_bodies(args):
    copies = int(args.get("copies", 1))
    if not 1 <= copies <= 100:
        raise RuntimeError("copies must be between 1 and 100.")
    translations = [float(args.get(k, 0)) for k in ("x_mm", "y_mm", "z_mm")]
    angles = [float(args.get(k, 0)) for k in ("rotation_x_deg", "rotation_y_deg", "rotation_z_deg")]
    point = [float(args.get(k, 0)) for k in ("rotation_point_x_mm", "rotation_point_y_mm", "rotation_point_z_mm")]
    if not all(math.isfinite(v) for v in translations + angles + point):
        raise RuntimeError("Translations, rotation angles and rotation points must be finite.")
    if any(translations) and any(angles):
        raise RuntimeError("Use separate calls for translation and rotation; SOLIDWORKS ignores rotation when translation is also specified.")
    _, doc = require_part()
    selected = _selected_bodies(doc, args["selection"], mark=1)
    before = len(get_bodies(doc))
    manager = flag_methods(feature_manager(doc), "InsertMoveCopyBody2")
    feature = manager.InsertMoveCopyBody2(*(to_m(v) for v in translations), 0.0,
                                        *(to_m(v) for v in point), *(to_rad(v) for v in angles), bool(args.get("copy", False)), copies)
    if feature is not None and any(angles):
        # SW2026 maps the InsertMoveCopyBody2 angle arguments to different
        # axes than their typelib names. Set the definition's explicit XYZ
        # properties instead of relying on the positional angle mapping.
        definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
        if not definition.AccessSelections(doc, nothing()):
            return result(False, "Cannot access move/copy definition to verify rotation.")
        modified = False
        try:
            definition.TransformX, definition.TransformY, definition.TransformZ = [to_rad(v) for v in angles]
            definition.RotationOriginX, definition.RotationOriginY, definition.RotationOriginZ = [to_m(v) for v in point]
            modified = bool(flag_methods(feature, "ModifyDefinition").ModifyDefinition(definition, doc, nothing()))
        finally:
            if not modified:
                value(definition, "ReleaseSelectionAccess")
        if not modified:
            return result(False, "SOLIDWORKS did not accept the requested rotation definition.")
        actual = value(feature, "GetDefinition")
        readback = [float(value(actual, name)) for name in ("TransformX", "TransformY", "TransformZ")]
        if not all(math.isclose(a, to_rad(b), abs_tol=1e-9) for a, b in zip(readback, angles)):
            return result(False, "Rotation definition readback differs from the requested axes.")
    payload = _finish(doc, feature, args, "body move/copy")
    after = len(get_bodies(doc))
    payload.setdefault("data", {}).update(body_count=after)
    expected = before + len(selected) * copies if args.get("copy", False) else before
    if payload["ok"] and after != expected:
        payload.update(ok=False, message="Body move/copy feature exists, but body count differs from the requested result.")
    return payload


@tool("combine_bodies", "Boolean add, subtract or intersect at least two solid bodies. For subtract, the first body is the main body and the rest are tools.",
      {"selection": BODY_SELECTION, "operation": {"type": "string", "enum": ["add", "subtract", "intersect"]}, "name": NAME}, ["selection", "operation"])
def combine_bodies(args):
    _, doc = require_part()
    bodies = _selected_bodies(doc, args["selection"], 2)
    operation = str(args["operation"])
    code = {"add": 15903, "subtract": 15902, "intersect": 15901}[operation]
    main = bodies[0] if operation == "subtract" else nothing()
    tools = bodies[1:] if operation == "subtract" else bodies
    manager = flag_methods(feature_manager(doc), "InsertCombineFeature")
    return _finish(doc, manager.InsertCombineFeature(code, main, dispatch_array(tools)), args, "body combination", operation=operation)


@tool("delete_bodies", "Create a Delete/Keep Body feature using solid body indices. keep_selected=true retains only selected bodies; otherwise deletes them.",
      {"selection": BODY_SELECTION, "keep_selected": {"type": "boolean", "default": False}, "name": NAME}, ["selection"])
def delete_bodies(args):
    _, doc = require_part()
    selected = _selected_bodies(doc, args["selection"])
    before = len(get_bodies(doc))
    keep = bool(args.get("keep_selected", False))
    manager = flag_methods(feature_manager(doc), "InsertDeleteBody2")
    payload = _finish(doc, manager.InsertDeleteBody2(keep), args, "delete/keep body")
    expected = len(selected) if keep else before - len(selected)
    if payload["ok"] and len(get_bodies(doc)) != expected:
        payload.update(ok=False, message="Delete/keep body count differs from the requested result.")
    return payload


@tool("surface_extrude", "Extrude an open or closed sketch into a surface body (no solid volume). Blind depth in mm; reverse flips direction.",
      {"depth_mm": {"type": "number", "exclusiveMinimum": 0}, "sketch_name": NAME, "reverse": {"type": "boolean", "default": False}, "name": NAME}, ["depth_mm"])
def surface_extrude(args):
    depth = to_m(_positive(args["depth_mm"], "depth_mm"))
    _, doc = require_part()
    sketch = select_sketch_for_feature(doc, args.get("sketch_name"))
    before = len(get_bodies(doc, BODY_SHEET))
    previous_features = _feature_names(doc)
    manager = flag_methods(feature_manager(doc), "FeatureExtruRefSurface3")
    manager.FeatureExtruRefSurface3(True, bool(args.get("reverse", False)), 0, 0.0,
        0, 0, depth, depth, False, False, False, False, 0.0, 0.0,
        False, False, False, False, False, False, False, False)
    feature = _feature_created_after(doc, previous_features)
    payload = _finish(doc, feature, args, "extruded surface", sketch=sketch)
    if payload["ok"] and len(get_bodies(doc, BODY_SHEET)) <= before:
        payload.update(ok=False, message="Extruded surface feature did not add a surface body.")
    return payload


@tool("list_surface_bodies", "Read-only: list surface bodies of the active part with names, face counts and areas in square millimetres. Solid-body indices are separate.")
def list_surface_bodies(args):
    _, doc = require_part()
    entries = []
    for index, body in enumerate(get_bodies(doc, BODY_SHEET)):
        faces = as_list(value(body, "GetFaces"))
        entries.append({"index": index, "name": str(value(body, "Name")), "face_count": len(faces),
                        "area_mm2": sum(float(value(face, "GetArea")) for face in faces) * 1e6})
    return result(True, "Read surface bodies.", surface_bodies=entries)


@tool("planar_surface", "Create a planar surface from a closed planar sketch. Produces a surface body rather than a solid.",
      {"sketch_name": NAME, "name": NAME})
def planar_surface(args):
    _, doc = require_part()
    sketch = select_sketch_for_feature(doc, args.get("sketch_name"))
    before = _feature_names(doc)
    count = len(get_bodies(doc, BODY_SHEET))
    flag_methods(doc, "InsertPlanarRefSurface").InsertPlanarRefSurface()
    feature = _feature_created_after(doc, before)
    payload = _finish(doc, feature, args, "planar surface", sketch=sketch)
    if payload["ok"] and len(get_bodies(doc, BODY_SHEET)) <= count:
        payload.update(ok=False, message="Planar surface feature did not add a surface body.")
    return payload


@tool("create_helix", "Create a constant-pitch helix from a sketch containing one circle. Defined by pitch in mm and revolutions; angles are degrees.",
      {"sketch_name": NAME, "pitch_mm": {"type": "number", "exclusiveMinimum": 0}, "revolutions": {"type": "number", "exclusiveMinimum": 0},
       "start_angle_deg": NUM, "clockwise": {"type": "boolean", "default": True}, "reverse": {"type": "boolean", "default": False}, "name": NAME}, ["pitch_mm", "revolutions"])
def create_helix(args):
    pitch = _positive(args["pitch_mm"], "pitch_mm")
    turns = _positive(args["revolutions"], "revolutions")
    _, doc = require_part()
    select_sketch_for_feature(doc, args.get("sketch_name"))
    before = _feature_names(doc)
    flag_methods(doc, "InsertHelix").InsertHelix(bool(args.get("reverse", False)), bool(args.get("clockwise", True)), False, False,
        0, to_m(pitch * turns), to_m(pitch), turns, 0.0, to_rad(args.get("start_angle_deg", 0)))
    feature = _feature_created_after(doc, before)
    payload = _finish(doc, feature, args, "helix")
    if payload["ok"]:
        definition = value(feature, "GetDefinition")
        actual_pitch = float(value(definition, "Pitch")) * 1000
        actual_turns = float(value(definition, "Revolution"))
        height = float(value(definition, "Height")) * 1000
        payload["data"].update(pitch_mm=actual_pitch, revolutions=actual_turns, height_mm=height)
        if not (math.isclose(actual_pitch, pitch, rel_tol=1e-6) and math.isclose(actual_turns, turns, rel_tol=1e-6)):
            payload.update(ok=False, message="Helix feature exists, but pitch/revolution readback differs.")
    return payload


@tool("offset_surface", "Create an offset surface from selected solid-model faces; distance=0 copies the selected faces. Distance is mm.",
      {"selection": SELECTION_SCHEMA, "distance_mm": {"type": "number", "minimum": 0}, "reverse": {"type": "boolean", "default": False}, "name": NAME}, ["selection", "distance_mm"])
def offset_surface(args):
    distance = float(args["distance_mm"])
    if not math.isfinite(distance) or distance < 0:
        raise RuntimeError("distance_mm must be finite and nonnegative.")
    _, doc = require_part()
    require_selection(doc, args["selection"])
    before = _feature_names(doc)
    sheets = len(get_bodies(doc, BODY_SHEET))
    flag_methods(doc, "InsertOffsetSurface").InsertOffsetSurface(to_m(distance), bool(args.get("reverse", False)))
    payload = _finish(doc, _feature_created_after(doc, before), args, "offset surface")
    if payload["ok"] and len(get_bodies(doc, BODY_SHEET)) <= sheets:
        payload.update(ok=False, message="Offset surface feature did not produce a surface body.")
    return payload


@tool("thicken_surface", "Thicken one surface into a solid. Select surface_bodies from list_surface_bodies or its feature; lengths are mm. both applies thickness on each side.",
      {"selection": SELECTION_SCHEMA, "thickness_mm": {"type": "number", "exclusiveMinimum": 0},
       "direction": {"type": "string", "enum": ["side_one", "side_two", "both"], "default": "side_one"},
       "merge": {"type": "boolean", "default": True}, "name": NAME}, ["selection", "thickness_mm"])
def thicken_surface(args):
    thickness = _positive(args["thickness_mm"], "thickness_mm")
    _, doc = require_part()
    count = require_selection(doc, args["selection"], mark=1)
    if count != 1:
        raise RuntimeError("Select exactly one surface body or surface feature.")
    before = len(get_bodies(doc))
    manager = flag_methods(feature_manager(doc), "FeatureBossThicken")
    feature = manager.FeatureBossThicken(to_m(thickness), {"side_one": 0, "side_two": 1, "both": 2}[args.get("direction", "side_one")],
                                        0, False, bool(args.get("merge", True)), True, True)
    payload = _finish(doc, feature, args, "surface thickening")
    if payload["ok"] and len(get_bodies(doc)) <= before and not args.get("merge", True):
        payload.update(ok=False, message="Thickening did not create a separate solid body.")
    return payload


@tool("knit_surfaces", "Knit at least two selected surface bodies/features, optionally forming a closed solid. Tolerance is mm; re-list surfaces after changes.",
      {"selection": SELECTION_SCHEMA, "form_solid": {"type": "boolean", "default": False}, "merge_entities": {"type": "boolean", "default": True},
       "tolerance_mm": {"type": "number", "minimum": 0.0001, "maximum": 0.1, "default": 0.001}, "name": NAME}, ["selection"])
def knit_surfaces(args):
    tolerance = float(args.get("tolerance_mm", 0.001))
    if not math.isfinite(tolerance) or not 0.0001 <= tolerance <= 0.1:
        raise RuntimeError("Knit tolerance must be between 0.0001 and 0.1 mm.")
    _, doc = require_part()
    count = require_selection(doc, args["selection"], mark=1)
    if count < 2:
        raise RuntimeError("Select at least two surface bodies or surface features.")
    before = len(get_bodies(doc))
    manager = flag_methods(feature_manager(doc), "InsertSewRefSurface")
    feature = manager.InsertSewRefSurface(False, bool(args.get("form_solid", False)), bool(args.get("merge_entities", True)), to_m(tolerance), to_m(tolerance))
    payload = _finish(doc, feature, args, "surface knit")
    if payload["ok"] and args.get("form_solid", False) and len(get_bodies(doc)) <= before:
        payload.update(ok=False, message="Knit feature did not form a closed solid.")
    return payload
