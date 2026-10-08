# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Native dome creation, geometry inspection and definition edits."""
import math
from .sw_core import (
    SELECTION_SCHEMA, apply_transform, as_list, clear_selection, dispatch_array,
    exit_active_sketch, find_feature, flag_methods, nothing, rebuild, require_part,
    require_selection, result, safe, tool, value, whats_wrong,
)
from .sw_feature import _feature_names, _feature_created_after
from .sw_multibody import _finish
from .sw_wrap import _geometry, _indices, _reference_id, _target_details

HEIGHT = {"type": "number", "exclusiveMinimum": 0}
FACES = {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1, "uniqueItems": True}
CONSTRAINT = {"type": "object", "properties": {k: SELECTION_SCHEMA["properties"][k] for k in ("sketch_name", "sketch_points")},
              "required": ["sketch_name", "sketch_points"], "additionalProperties": False}


def _validate(args, creating=False):
    if creating or "height_mm" in args:
        height = float(args["height_mm"])
        if not math.isfinite(height) or height <= 0:
            raise RuntimeError("Dome height_mm must be finite and positive.")
    for k in ("reverse_direction", "elliptical"):
        if k in args and not isinstance(args[k], bool):
            raise RuntimeError(f"{k} must be boolean.")
    if creating or "face_index" in args or "face_indices" in args:
        _indices(args)
    if "direction_edge_index" in args:
        index = args["direction_edge_index"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise RuntimeError("direction_edge_index must be a nonnegative solid-edge index.")
    if "constraint_selection" in args:
        spec = args["constraint_selection"]
        if (not isinstance(spec, dict) or set(spec) != {"sketch_name", "sketch_points"}
                or not isinstance(spec["sketch_name"], str) or not spec["sketch_name"].strip()
                or not isinstance(spec["sketch_points"], list) or len(spec["sketch_points"]) != 1
                or isinstance(spec["sketch_points"][0], bool) or not isinstance(spec["sketch_points"][0], int)
                or spec["sketch_points"][0] < 0):
            raise RuntimeError("Select exactly one point from a named sketch as the dome constraint.")
        if "height_mm" in args:
            raise RuntimeError("The constraint point controls height; do not supply height_mm with constraint_selection.")


def _selected(doc, spec):
    count = require_selection(doc, spec, mark=1)
    manager = flag_methods(value(doc, "SelectionManager"), "GetSelectedObject6")
    return [manager.GetSelectedObject6(i, 1) for i in range(1, count + 1)]


def _point_position(point):
    sketch = value(point, "GetSketch")
    inverse = value(value(sketch, "ModelToSketchTransform"), "Inverse")
    return apply_transform([float(value(point, k)) for k in ("X", "Y", "Z")], value(inverse, "ArrayData"))


def _ellipsoid_queries(face, height, reverse):
    edges = as_list(value(face, "GetEdges"))
    if len(edges) != 1:
        return None
    curve = value(edges[0], "GetCurve")
    normal = [float(c) for c in value(face, "Normal")]
    if bool(value(curve, "IsCircle")):
        params = value(curve, "CircleParams")
        center, major, minor = list(params[:3]), float(params[6]), float(params[6])
        seed = [1, 0, 0] if abs(normal[0]) < .9 else [0, 1, 0]
        a = [normal[1] * seed[2] - normal[2] * seed[1], normal[2] * seed[0] - normal[0] * seed[2], normal[0] * seed[1] - normal[1] * seed[0]]
        length = math.sqrt(sum(c * c for c in a)); a = [c / length for c in a]
        b = [normal[1] * a[2] - normal[2] * a[1], normal[2] * a[0] - normal[0] * a[2], normal[0] * a[1] - normal[1] * a[0]]
    elif bool(value(curve, "IsEllipse")):
        params = value(curve, "GetEllipseParams")
        center, major, minor = list(params[:3]), float(params[3]), float(params[7])
        a, b = list(params[4:7]), list(params[8:11])
    else:
        return None
    signed_height = height / 1000 * (-1 if reverse else 1)
    return [[center[i] + a[i] * major * rho * math.cos(angle) + b[i] * minor * rho * math.sin(angle)
             + normal[i] * signed_height * math.sqrt(1 - rho * rho) for i in range(3)]
            for rho in (.25, .5, .75) for angle in [k * math.pi / 4 for k in range(8)]]


def _dome_info(doc, feature, expected=None):
    if feature is None or safe(feature, "GetTypeName2") != "Dome":
        raise RuntimeError("Specify an existing native dome feature.")
    data = flag_methods(value(feature, "GetDefinition"), "AccessSelections", "GetFaceCount")
    if not data.AccessSelections(doc, nothing()):
        raise RuntimeError("Cannot access dome selections.")
    probes, ellipsoid_queries = [], []
    try:
        faces = as_list(value(data, "Faces"))
        count = int(data.GetFaceCount())
        if len(faces) != count:
            raise RuntimeError("Native dome face count and references differ.")
        direction = value(data, "Direction")
        constraint = value(data, "ConstraintPointOrSketch")
        height, reverse = float(value(data, "Height")) * 1000, bool(value(data, "ReverseDir"))
        info = {"height_mm": height, "reverse_direction": reverse, "elliptical": bool(value(data, "Elliptical")),
                "input_face_count": count, "input_faces": [_target_details(f) for f in faces],
                "has_direction": direction is not None, "has_constraint": constraint is not None,
                "input_geometry": _geometry(doc)}
        for face, meta in zip(faces, info["input_faces"]):
            if meta["surface_type"] == "plane":
                normal = [float(c) for c in value(face, "Normal")]
                box = meta["box_mm"]
                center = [(box[i] + box[i + 3]) / 2000 for i in range(3)]
                probes.append((center, [center[i] + normal[i] * height / 1000 * (-1 if reverse else 1) for i in range(3)], normal))
            if info["elliptical"] and constraint is None:
                ellipsoid_queries.append(_ellipsoid_queries(face, height, reverse) if meta["surface_type"] == "plane" else None)
        if expected:
            for key, obj in (("direction", direction), ("constraint", constraint)):
                if key in expected:
                    info[f"{key}_reference_confirmed"] = obj is not None and bool(expected[key]) and _reference_id(doc, obj) == expected[key]
            if "faces" in expected:
                actual = [_reference_id(doc, f) for f in faces]
                info["face_references_confirmed"] = bool(actual) and len(actual) == len(expected["faces"]) and set(actual) == set(expected["faces"])
        point = None
        if constraint is not None and safe(constraint, "GetSketch") is not None:
            point = _point_position(constraint)
            info["constraint_point_mm"] = [c * 1000 for c in point]
    finally:
        value(data, "ReleaseSelectionAccess")
    output = as_list(value(feature, "GetFaces"))
    info.update(_geometry(doc), feature_faces=[_target_details(f) for f in output])
    samples = []
    for center, query, normal in probes:
        candidates = [list(flag_methods(f, "GetClosestPointOn").GetClosestPointOn(*query)[:3]) for f in output]
        if not candidates:
            continue
        closest = min(candidates, key=lambda q: sum((a - b) ** 2 for a, b in zip(q, query)))
        samples.append({"point_mm": [c * 1000 for c in closest],
                        "normal_displacement_mm": sum((closest[i] - center[i]) * normal[i] for i in range(3)) * 1000})
    info["center_probes"] = samples
    if point is not None:
        distances = [math.dist(point, flag_methods(f, "GetClosestPointOn").GetClosestPointOn(*point)[:3]) * 1000 for f in output]
        info["constraint_surface_gap_mm"] = min(distances) if distances else None
    if info["elliptical"] and not info["has_constraint"]:
        gaps = []
        supported = bool(ellipsoid_queries) and all(q is not None for q in ellipsoid_queries) and bool(output)
        if supported:
            for queries in ellipsoid_queries:
                for query in queries:
                    gaps.append(min(math.dist(query, flag_methods(f, "GetClosestPointOn").GetClosestPointOn(*query)[:3]) * 1000 for f in output))
        info["ellipsoid_check"] = {"confirmed": supported and max(gaps) <= .01,
                                   "maximum_surface_gap_mm": max(gaps) if gaps else None,
                                   "sample_count": len(gaps)}
    return info


def _geometry_confirmed(info):
    before = info["input_geometry"]["solid_volume_mm3"]
    delta = info["solid_volume_mm3"] - before
    tolerance = max(1e-6, abs(before) * 1e-9)
    signed = delta < -tolerance if info["reverse_direction"] else delta > tolerance
    if info["has_constraint"]:
        # A constrained point drives the shape, and native Height becomes zero.
        height = info.get("constraint_surface_gap_mm") is not None and info["constraint_surface_gap_mm"] <= .01
    else:
        sign = -1 if info["reverse_direction"] else 1
        height = bool(info["center_probes"]) and all(abs(p["normal_displacement_mm"] - sign * info["height_mm"]) <= .01 for p in info["center_probes"])
    return delta, signed and height and info.get("ellipsoid_check", {"confirmed": True})["confirmed"]


@tool("get_dome_data", "Read native dome height (mm), convex/concave and elliptical state, input faces, constraint/direction presence, input/current solid geometry and closest-point center probes. Native B-spline boxes are approximate and do not prove height. Point-constrained domes report native height zero and actual constraint position/gap.",
      {"name": {"type": "string", "minLength": 1}}, ["name"])
def get_dome_data(args):
    _, doc = require_part()
    return result(True, "Read dome definition and geometry.", dome=_dome_info(doc, find_feature(doc, args["name"])))


@tool("dome", "Create a native dome on selected solid faces using mark 1. Height is mm; reverse_direction creates a concave dome, elliptical requests a half ellipsoid. Use face_index or face_indices. Checks native face count, parameters, actual signed volume, planar-face center height and 24-point half-ellipsoid surface gaps for conic boundaries. Native creation can reject disconnected multiple faces; no fallback drops faces. More complex/non-planar height verification remains pending and returns unconfirmed with the feature retained.",
      {"face_index": {"type": "integer", "minimum": 0}, "face_indices": FACES, "height_mm": HEIGHT,
       "reverse_direction": {"type": "boolean", "default": False}, "elliptical": {"type": "boolean", "default": False},
       "name": {"type": "string"}}, ["height_mm"])
def dome(args):
    _validate(args, creating=True)
    _, doc = require_part()
    exit_active_sketch(doc)
    indices = _indices(args)
    before = _feature_names(doc)
    try:
        require_selection(doc, {"faces": indices}, mark=1)
        flag_methods(doc, "InsertDome").InsertDome(float(args["height_mm"]) / 1000, args.get("reverse_direction", False), args.get("elliptical", False))
        feature = _feature_created_after(doc, before)
        payload = _finish(doc, feature, args, "dome")
        if feature is None or not payload["ok"]:
            return payload
        info = _dome_info(doc, feature)
        delta, geometry = _geometry_confirmed(info)
        correct = (info["input_face_count"] == len(indices) and math.isclose(info["height_mm"], float(args["height_mm"]), abs_tol=1e-7)
                   and info["reverse_direction"] == args.get("reverse_direction", False) and info["elliptical"] == args.get("elliptical", False))
        payload["data"].update(dome=info, volume_change_mm3=delta, geometry_confirmed=geometry)
        if not correct or not geometry:
            payload.update(ok=False, message="Dome created, but native parameters or geometric effect could not be confirmed. Feature retained.")
        return payload
    finally:
        clear_selection(doc)


@tool("set_dome_parameters", "Modify dome height, convex/concave state, elliptical state, target faces, a constraint sketch point or direction edge. Constraint and height are mutually exclusive: the point drives shape and native Height becomes zero. Checks frozen references, readback, signed volume and height/constraint geometry. On the tested build a direction edge can flatten the dome despite successful native readback; zero-effect edits return failure with the feature retained. Whole-sketch constraints and clearing controls are not implemented yet.",
      {"name": {"type": "string", "minLength": 1}, "height_mm": HEIGHT, "reverse_direction": {"type": "boolean"},
       "elliptical": {"type": "boolean"}, "face_index": {"type": "integer", "minimum": 0}, "face_indices": FACES,
       "constraint_selection": CONSTRAINT, "direction_edge_index": {"type": "integer", "minimum": 0}}, ["name"])
def set_dome_parameters(args):
    if not any(k in args for k in ("height_mm", "reverse_direction", "elliptical", "face_index", "face_indices", "constraint_selection", "direction_edge_index")):
        raise RuntimeError("Specify at least one dome parameter to change.")
    _validate(args)
    _, doc = require_part()
    exit_active_sketch(doc)
    feature = find_feature(doc, args["name"])
    _dome_info(doc, feature)
    references, expected = {}, {}
    try:
        if "face_index" in args or "face_indices" in args:
            faces = _selected(doc, {"faces": _indices(args)})
            references["Faces"] = dispatch_array(faces)
            expected["faces"] = [_reference_id(doc, f) for f in faces]
        if "constraint_selection" in args:
            point = _selected(doc, args["constraint_selection"])[0]
            references["ConstraintPointOrSketch"] = point
            expected["constraint"] = _reference_id(doc, point)
        if "direction_edge_index" in args:
            edge = _selected(doc, {"edges": [args["direction_edge_index"]]})[0]
            if not bool(value(value(edge, "GetCurve"), "IsLine")):
                raise RuntimeError("The dome direction edge must be linear.")
            references["Direction"] = edge
            expected["direction"] = _reference_id(doc, edge)
        if any(not ref for refs in expected.values() for ref in (refs if isinstance(refs, list) else [refs])):
            raise RuntimeError("Cannot snapshot dome reference identities.")
    finally:
        clear_selection(doc)
    data = flag_methods(value(feature, "GetDefinition"), "AccessSelections")
    if not data.AccessSelections(doc, nothing()):
        return result(False, "Cannot access dome selections.")
    accepted = False
    try:
        for member, obj in references.items():
            setattr(data, member, obj)
        for key, member in (("height_mm", "Height"), ("reverse_direction", "ReverseDir"), ("elliptical", "Elliptical")):
            if key in args:
                setattr(data, member, float(args[key]) / 1000 if key == "height_mm" else args[key])
        accepted = bool(flag_methods(feature, "ModifyDefinition").ModifyDefinition(data, doc, nothing()))
    finally:
        if not accepted:
            value(data, "ReleaseSelectionAccess")
        clear_selection(doc)
    rebuild(doc)
    info = _dome_info(doc, feature, expected)
    delta, geometry = _geometry_confirmed(info)
    correct = all((math.isclose(info[k], float(args[k]), abs_tol=1e-7) if k == "height_mm" else info[k] == args[k])
                  for k in ("height_mm", "reverse_direction", "elliptical") if k in args)
    correct = correct and all(info["face_references_confirmed" if k == "faces" else f"{k}_reference_confirmed"] for k in expected)
    problems = whats_wrong(doc)
    return result(accepted and correct and geometry and not problems,
                  "Updated dome parameters and verified geometry." if accepted and correct and geometry and not problems else
                  "Dome modification or geometric effect could not be confirmed. Feature retained.",
                  feature=args["name"], dome=info, parameters_confirmed=correct, geometry_confirmed=geometry,
                  volume_change_from_input_mm3=delta, problems=problems)
