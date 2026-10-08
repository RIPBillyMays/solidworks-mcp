# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Native wrap creation, definition inspection and parameter modification."""
import math
from .sw_core import (
    as_list, clear_selection, exit_active_sketch, feature_manager, find_feature,
    flag_methods, get_bodies, nothing, require_part, require_selection,
    result, safe, tool, value, SELECTION_SCHEMA, rebuild, whats_wrong,
)
from .sw_feature import _feature_names, _feature_created_after
from .sw_multibody import _finish

MODES = {"emboss": 0, "engrave": 1, "scribe": 2}
METHODS = {"analytical": 0, "spline": 1}
PULL_SCHEMA = {"type": "object", "properties": {
    k: SELECTION_SCHEMA["properties"][k] for k in ("planes", "edges", "sketch_segments", "sketch_name")},
    "additionalProperties": False,
    "description": "Exactly one reference plane, linear solid edge or line sketch segment. The plane normal or line direction defines pull."}


def _pull_selection(spec):
    if not isinstance(spec, dict) or any(k not in PULL_SCHEMA["properties"] for k in spec):
        raise RuntimeError("Pull selection must name one plane, linear edge or sketch line.")
    if sum(len(spec.get(k, [])) for k in ("planes", "edges", "sketch_segments")) != 1:
        raise RuntimeError("Pull selection must resolve to exactly one direction entity.")
    return spec


def _selected_pull(doc, spec, append=False):
    if require_selection(doc, spec, mark=2, append=append) != 1:
        raise RuntimeError("Pull selection did not resolve to one entity.")
    manager = flag_methods(value(doc, "SelectionManager"), "GetSelectedObject6")
    obj = manager.GetSelectedObject6(1, 2)
    if spec.get("edges"):
        curve = value(obj, "GetCurve")
        if not bool(value(curve, "IsLine")):
            raise RuntimeError("The pull edge must be linear.")
    if spec.get("sketch_segments") and int(value(obj, "GetType")) != 0:
        raise RuntimeError("The pull sketch segment must be a line.")
    return obj


def _indices(args):
    if "face_index" in args and "face_indices" in args:
        raise RuntimeError("Use face_index or face_indices, not both.")
    indices = args.get("face_indices", [args["face_index"]] if "face_index" in args else [])
    if (not isinstance(indices, list) or not indices or any(isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in indices)
            or len(set(indices)) != len(indices)):
        raise RuntimeError("Specify distinct nonnegative solid-face indices.")
    return indices


def _arguments(args):
    mode, method = args.get("mode", "emboss"), args.get("method", "analytical")
    if mode not in MODES or method not in METHODS:
        raise RuntimeError("Unknown wrap mode or method.")
    thickness = float(args.get("thickness_mm", 1.))
    if not math.isfinite(thickness) or not .01 <= thickness <= 1e7:
        raise RuntimeError("Wrap thickness_mm must be between 0.01 and 10000000.")
    mesh = args.get("mesh_factor", 5)
    if isinstance(mesh, bool) or not isinstance(mesh, int) or not 1 <= mesh <= 10:
        raise RuntimeError("mesh_factor must be an integer from 1 to 10.")
    _indices(args)
    if not isinstance(args.get("reverse_direction", False), bool):
        raise RuntimeError("reverse_direction must be boolean.")
    if "pull_selection" in args:
        _pull_selection(args["pull_selection"])
        if mode == "scribe":
            raise RuntimeError("A pull direction is only applicable to emboss or engrave.")
    if not isinstance(args["sketch_name"], str) or not args["sketch_name"].strip():
        raise RuntimeError("A closed 2D sketch_name is required.")
    return mode, method, thickness, mesh


def _geometry(doc):
    bodies = get_bodies(doc)
    return {"solid_body_count": len(bodies),
            "solid_volume_mm3": sum(float(flag_methods(b, "GetMassProperties").GetMassProperties(1.)[3]) * 1e9 for b in bodies),
            "solid_face_count": sum(len(as_list(value(b, "GetFaces"))) for b in bodies)}


def _reference_id(doc, obj):
    return tuple(as_list(flag_methods(value(doc, "Extension"), "GetPersistReference3").GetPersistReference3(obj)))


def _wrap_info(doc, feature, expected_pull=None):
    if feature is None or safe(feature, "GetTypeName2") != "Emboss":
        raise RuntimeError("Specify an existing native wrap feature.")
    definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
    if not definition.AccessSelections(doc, nothing()):
        raise RuntimeError("Cannot access wrap feature selections.")
    try:
        source = value(definition, "SourceSketch")
        mode = int(value(definition, "Type"))
        pull = value(definition, "PullDirection")
        info = {"mode": next((k for k, v in MODES.items() if v == mode), "unknown"), "native_type": mode,
                "thickness_mm": float(value(definition, "Thickness")) * 1000,
                "reverse_direction": bool(value(definition, "ReverseDirection")),
                "source_sketch": str(value(source, "Name")) if source is not None else None,
                "has_target_face": value(definition, "Face") is not None,
                "has_pull_direction": pull is not None,
                "unreadable_parameters": ["method", "mesh_factor", "all_target_faces"]}
        if expected_pull is not None:
            expected_id = _reference_id(doc, expected_pull)
            info["pull_reference_confirmed"] = bool(expected_id) and pull is not None and _reference_id(doc, pull) == expected_id
    finally:
        value(definition, "ReleaseSelectionAccess")
    # AccessSelections rolls back the feature. Read geometry only after releasing it.
    faces = as_list(value(feature, "GetFaces"))
    info.update(_geometry(doc), feature_face_count=len(faces),
                feature_face_area_mm2=sum(float(value(f, "GetArea")) for f in faces) * 1e6)
    return info


def _effect(info, before):
    delta = info["solid_volume_mm3"] - before["solid_volume_mm3"]
    tol = max(1e-6, before["solid_volume_mm3"] * 1e-9)
    mode = info["mode"]
    return delta, (delta > tol if mode == "emboss" else delta < -tol if mode == "engrave" else
                   abs(delta) <= tol and info["solid_face_count"] > before["solid_face_count"])


@tool("get_wrap_data", "Read native wrap mode, thickness in mm, reverse state, source sketch, target/pull presence and current solid geometry. Native IWrapSketchFeatureData cannot expose method, mesh factor or all target faces; these are explicitly listed as unreadable.",
      {"name": {"type": "string", "minLength": 1}}, ["name"])
def get_wrap_data(args):
    _, doc = require_part()
    return result(True, "Read wrap definition and geometry.", wrap=_wrap_info(doc, find_feature(doc, args["name"])))


@tool("wrap_sketch", "Wrap a closed 2D sketch on solid faces: emboss adds material, engrave removes it, scribe splits faces. Use face_index or face_indices. Multiple faces require InsertWrapFeature2; analytical and spline methods are supported. Thickness is mm (unused by scribe). Optional pull_selection selects one plane, linear edge or sketch line (mark 2). Checks pull reference identity, native definition, rebuild, volume and face splitting. reverse_direction is forwarded and read back, but its geometric effect remains unconfirmed and returns failure with the created feature retained.",
      {"sketch_name": {"type": "string", "minLength": 1}, "face_index": {"type": "integer", "minimum": 0},
       "face_indices": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1, "uniqueItems": True},
       "mode": {"type": "string", "enum": list(MODES), "default": "emboss"},
       "method": {"type": "string", "enum": list(METHODS), "default": "analytical"},
       "thickness_mm": {"type": "number", "minimum": .01, "maximum": 1e7, "default": 1},
       "mesh_factor": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
       "pull_selection": PULL_SCHEMA, "reverse_direction": {"type": "boolean", "default": False},
       "name": {"type": "string"}}, ["sketch_name"])
def wrap_sketch(args):
    mode, method, thickness, mesh = _arguments(args)
    indices = _indices(args)
    reverse = args.get("reverse_direction", False)
    _, doc = require_part()
    exit_active_sketch(doc)
    manager = flag_methods(feature_manager(doc), "InsertWrapFeature2", "InsertWrapFeature")
    modern = getattr(manager, "InsertWrapFeature2", None)
    if modern is None and (method != "analytical" or len(indices) > 1):
        raise RuntimeError("Spline or multiple-face wrap requires InsertWrapFeature2; the older method cannot preserve this option.")
    before = _geometry(doc)
    names = _feature_names(doc)
    try:
        require_selection(doc, {"sketches": [args["sketch_name"]]}, mark=4)
        require_selection(doc, {"faces": indices}, mark=1, append=True)
        pull = _selected_pull(doc, args["pull_selection"], append=True) if "pull_selection" in args else None
        feature = (modern(MODES[mode], thickness / 1000, reverse, METHODS[method], mesh) if modern is not None
                   else manager.InsertWrapFeature(MODES[mode], thickness / 1000, reverse))
        if feature is None:
            feature = _feature_created_after(doc, names)
        payload = _finish(doc, feature, args, "wrap feature")
        if feature is None or not payload["ok"]:
            return payload
        info = _wrap_info(doc, feature, expected_pull=pull)
        delta, geometric = _effect(info, before)
        confirmed = (info["mode"] == mode and info["source_sketch"] == args["sketch_name"] and info["has_target_face"]
                     and info["reverse_direction"] == reverse and info["has_pull_direction"] == (pull is not None)
                     and (pull is None or info["pull_reference_confirmed"])
                     and math.isclose(info["thickness_mm"], thickness, abs_tol=1e-7) and geometric)
        payload["data"].update(wrap=info, volume_change_mm3=delta,
                                requested_parameters={"method": method, "mesh_factor": mesh, "face_indices": indices},
                                geometry_confirmed=geometric)
        if reverse:
            confirmed = False
            payload["data"]["reverse_geometry_confirmed"] = False
        if not confirmed:
            payload["ok"] = False
            payload["message"] = "Wrap was created, but native definition or geometric effect could not be confirmed. Feature retained."
        return payload
    finally:
        clear_selection(doc)


@tool("set_wrap_parameters", "Modify native wrap mode, thickness in mm, reverse state or pull direction and rebuild dependent features. clear_pull_direction attempts to clear the reference, but this native option remained unchanged on the tested build and readback reports failure. Reference identity and readable parameters are checked; geometric effect is checked against the model rolled back before the wrap. Method, mesh, source sketch and target faces are not modified. Reverse-direction geometry remains unconfirmed: requesting true reports failure and retains the modified feature.",
      {"name": {"type": "string", "minLength": 1}, "mode": {"type": "string", "enum": list(MODES)},
       "thickness_mm": {"type": "number", "minimum": .01, "maximum": 1e7},
       "reverse_direction": {"type": "boolean"}, "pull_selection": PULL_SCHEMA,
       "clear_pull_direction": {"type": "boolean"}}, ["name"])
def set_wrap_parameters(args):
    keys = ("mode", "thickness_mm", "reverse_direction", "pull_selection", "clear_pull_direction")
    if not any(k in args for k in keys) or args.get("clear_pull_direction") is False and not any(k in args for k in keys[:-1]):
        raise RuntimeError("Specify at least one wrap parameter to change.")
    if "mode" in args and args["mode"] not in MODES:
        raise RuntimeError("Unknown wrap mode.")
    if "thickness_mm" in args and (not math.isfinite(float(args["thickness_mm"])) or not .01 <= float(args["thickness_mm"]) <= 1e7):
        raise RuntimeError("Invalid wrap thickness_mm.")
    for k in ("reverse_direction", "clear_pull_direction"):
        if k in args and not isinstance(args[k], bool):
            raise RuntimeError(f"{k} must be boolean.")
    if "pull_selection" in args:
        _pull_selection(args["pull_selection"])
        if args.get("clear_pull_direction"):
            raise RuntimeError("Do not specify pull_selection together with clear_pull_direction.")
        if args.get("mode") == "scribe":
            raise RuntimeError("Pull direction is not applicable to scribe.")
    _, doc = require_part()
    exit_active_sketch(doc)
    feature = find_feature(doc, args["name"])
    previous = _wrap_info(doc, feature)
    if "pull_selection" in args and args.get("mode", previous["mode"]) == "scribe":
        raise RuntimeError("Pull direction is not applicable to scribe.")
    definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
    if not definition.AccessSelections(doc, nothing()):
        return result(False, "Could not access wrap selections.")
    accepted = False
    pull = None
    try:
        baseline = _geometry(doc)
        for key, member in (("mode", "Type"), ("thickness_mm", "Thickness"), ("reverse_direction", "ReverseDirection")):
            if key in args:
                raw = MODES[args[key]] if key == "mode" else float(args[key]) / 1000 if key == "thickness_mm" else args[key]
                setattr(definition, member, raw)
        if "pull_selection" in args:
            pull = _selected_pull(doc, args["pull_selection"])
            definition.PullDirection = pull
        elif args.get("clear_pull_direction"):
            clear_selection(doc)
            definition.PullDirection = nothing()
        accepted = bool(flag_methods(feature, "ModifyDefinition").ModifyDefinition(definition, doc, nothing()))
    finally:
        if not accepted:
            value(definition, "ReleaseSelectionAccess")
        clear_selection(doc)
    rebuild(doc)
    problems = whats_wrong(doc)
    info = _wrap_info(doc, feature, expected_pull=pull)
    correct = all((math.isclose(info[k], float(args[k]), abs_tol=1e-7) if k == "thickness_mm" else info[k] == args[k])
                  for k in ("mode", "thickness_mm", "reverse_direction") if k in args)
    correct = correct and (pull is None or info["pull_reference_confirmed"]) and (not args.get("clear_pull_direction") or not info["has_pull_direction"])
    delta, geometry = _effect(info, baseline)
    reverse_confirmed = not info["reverse_direction"]
    ok = accepted and correct and geometry and reverse_confirmed and not problems
    return result(ok, "Updated wrap parameters and verified geometry." if ok else
                  "Wrap modification or geometric effect could not be confirmed. Feature retained.",
                  feature=args["name"], wrap=info, parameters_confirmed=correct, geometry_confirmed=geometry,
                  reverse_geometry_confirmed=reverse_confirmed, volume_change_from_input_mm3=delta, problems=problems)
