# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Native single-face wrap creation and definition/geometry inspection."""
import math
from .sw_core import (
    as_list, clear_selection, exit_active_sketch, feature_manager, find_feature,
    flag_methods, get_bodies, nothing, require_part, require_selection,
    result, safe, tool, value,
)
from .sw_feature import _feature_names, _feature_created_after
from .sw_multibody import _finish

MODES = {"emboss": 0, "engrave": 1, "scribe": 2}
METHODS = {"analytical": 0, "spline": 1}


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
    index = args["face_index"]
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise RuntimeError("face_index must be a nonnegative solid-face index.")
    if not isinstance(args["sketch_name"], str) or not args["sketch_name"].strip():
        raise RuntimeError("A closed 2D sketch_name is required.")
    return mode, method, thickness, mesh


def _geometry(doc):
    bodies = get_bodies(doc)
    return {"solid_body_count": len(bodies),
            "solid_volume_mm3": sum(float(flag_methods(b, "GetMassProperties").GetMassProperties(1.)[3]) * 1e9 for b in bodies),
            "solid_face_count": sum(len(as_list(value(b, "GetFaces"))) for b in bodies)}


def _wrap_info(doc, feature):
    if feature is None or safe(feature, "GetTypeName2") != "Emboss":
        raise RuntimeError("Specify an existing native wrap feature.")
    definition = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "ReleaseSelectionAccess")
    if not definition.AccessSelections(doc, nothing()):
        raise RuntimeError("Cannot access wrap feature selections.")
    try:
        source = value(definition, "SourceSketch")
        mode = int(value(definition, "Type"))
        info = {"mode": next((k for k, v in MODES.items() if v == mode), "unknown"), "native_type": mode,
                "thickness_mm": float(value(definition, "Thickness")) * 1000,
                "reverse_direction": bool(value(definition, "ReverseDirection")),
                "source_sketch": str(value(source, "Name")) if source is not None else None,
                "has_target_face": value(definition, "Face") is not None,
                "has_pull_direction": value(definition, "PullDirection") is not None,
                "unreadable_parameters": ["method", "mesh_factor", "all_target_faces"]}
    finally:
        value(definition, "ReleaseSelectionAccess")
    # AccessSelections rolls back the feature. Read geometry only after releasing it.
    faces = as_list(value(feature, "GetFaces"))
    info.update(_geometry(doc), feature_face_count=len(faces),
                feature_face_area_mm2=sum(float(value(f, "GetArea")) for f in faces) * 1e6)
    return info


@tool("get_wrap_data", "Read native wrap mode, thickness in mm, reverse state, source sketch, target/pull presence and current solid geometry. Native IWrapSketchFeatureData cannot expose method, mesh factor or all target faces; these are explicitly listed as unreadable.",
      {"name": {"type": "string", "minLength": 1}}, ["name"])
def get_wrap_data(args):
    _, doc = require_part()
    return result(True, "Read wrap definition and geometry.", wrap=_wrap_info(doc, find_feature(doc, args["name"])))


@tool("wrap_sketch", "Wrap a closed 2D sketch on one solid face: emboss adds material, engrave removes it, scribe splits the face. Thickness is mm (unused by scribe). Supports analytical or spline method and spline mesh factor 1..10. Uses normal pull direction. Multiple target faces, custom pull and reverse direction are not implemented. Checks native definition, rebuild, volume change and face splitting; failed verification retains the feature.",
      {"sketch_name": {"type": "string", "minLength": 1}, "face_index": {"type": "integer", "minimum": 0},
       "mode": {"type": "string", "enum": list(MODES), "default": "emboss"},
       "method": {"type": "string", "enum": list(METHODS), "default": "analytical"},
       "thickness_mm": {"type": "number", "minimum": .01, "maximum": 1e7, "default": 1},
       "mesh_factor": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
       "name": {"type": "string"}}, ["sketch_name", "face_index"])
def wrap_sketch(args):
    mode, method, thickness, mesh = _arguments(args)
    _, doc = require_part()
    exit_active_sketch(doc)
    manager = flag_methods(feature_manager(doc), "InsertWrapFeature2", "InsertWrapFeature")
    modern = getattr(manager, "InsertWrapFeature2", None)
    if modern is None and method != "analytical":
        raise RuntimeError("Spline wrap requires InsertWrapFeature2; the older method cannot preserve this option.")
    before = _geometry(doc)
    names = _feature_names(doc)
    try:
        require_selection(doc, {"sketches": [args["sketch_name"]]}, mark=4)
        require_selection(doc, {"faces": [args["face_index"]]}, mark=1, append=True)
        feature = (modern(MODES[mode], thickness / 1000, False, METHODS[method], mesh) if modern is not None
                   else manager.InsertWrapFeature(MODES[mode], thickness / 1000, False))
        if feature is None:
            feature = _feature_created_after(doc, names)
        payload = _finish(doc, feature, args, "wrap feature")
        if feature is None or not payload["ok"]:
            return payload
        info = _wrap_info(doc, feature)
        delta = info["solid_volume_mm3"] - before["solid_volume_mm3"]
        volume_tol = max(1e-6, before["solid_volume_mm3"] * 1e-9)
        geometric = (delta > volume_tol if mode == "emboss" else delta < -volume_tol if mode == "engrave"
                     else abs(delta) <= volume_tol and info["solid_face_count"] > before["solid_face_count"])
        confirmed = (info["mode"] == mode and info["source_sketch"] == args["sketch_name"] and info["has_target_face"]
                     and not info["reverse_direction"] and not info["has_pull_direction"]
                     and math.isclose(info["thickness_mm"], thickness, abs_tol=1e-7) and geometric)
        payload["data"].update(wrap=info, volume_change_mm3=delta,
                                requested_parameters={"method": method, "mesh_factor": mesh},
                                geometry_confirmed=geometric)
        if not confirmed:
            payload["ok"] = False
            payload["message"] = "Wrap was created, but native definition or geometric effect could not be confirmed. Feature retained."
        return payload
    finally:
        clear_selection(doc)
