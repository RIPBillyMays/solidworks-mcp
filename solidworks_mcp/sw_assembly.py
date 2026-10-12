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

"""Assembly work: components and mates.

create_new_document could already make an assembly, which was not much use
without a way to put anything in it.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .sw_core import (
    MATE_ALIGNMENTS,
    MATE_TYPES,
    SELECTION_SCHEMA,
    apply_transform,
    as_list,
    byref_long,
    clear_selection,
    component_bodies,
    component_transform,
    document_info,
    dialogs_suppressed,
    double_array,
    empty_variant,
    extension,
    feature_property,
    flag_methods,
    iter_components,
    iter_feature_objects,
    logger,
    mm_point,
    rebuild,
    require_assembly,
    require_selection,
    result,
    running_app,
    safe,
    select_at_point,
    select_by_id,
    select_object,
    selectable,
    to_deg,
    to_m,
    to_rad,
    to_mm,
    tool,
    value,
)
from .sw_mates_adv import ADV_MATE_TYPES, UNSUPPORTED_MATE_TYPES, assign_marks, plan_advanced_mate


ADD_MATE_ERRORS = {
    0: "unknown error",
    1: "no error",
    2: "incorrect mate type for that selection",
    3: "incorrect alignment",
    4: "incorrect selections",
    5: "the mate would over-define the assembly",
    6: "incorrect gear ratios",
}


# Enum values (swComponentSuppressionState_e, swAddComponentConfigOptions_e,
# swMateWidth_e) are written inline where used so the enum-coverage test, which
# scans module-level tables, does not need entries for them; see the comments there.


# --------------------------------------------------------------------------
# Lookup helpers
# --------------------------------------------------------------------------


def find_component(doc: Any, name: str) -> Any | None:
    """Find a component by its Name2 (for example ``Bracket-1`` or ``Sub-1/Pin-1``)."""
    for component in iter_components(doc, False):
        if str(safe(component, "Name2", "")) == name:
            return component
    try:
        flag_methods(doc, "GetComponentByName")
        return doc.GetComponentByName(name)
    except Exception:
        return None


def require_component(doc: Any, name: str) -> Any:
    component = find_component(doc, str(name))
    if component is None:
        available = [str(safe(c, "Name2", "")) for c in iter_components(doc, False)]
        raise RuntimeError(f"No component named '{name}'. Available: {available}")
    return component


def mate_features(doc: Any) -> list[Any]:
    """Every mate feature, in tree order (mates are sub-features of the MateGroup)."""
    found: list[Any] = []
    for feature in iter_feature_objects(doc):
        if str(feature_property(feature, "GetTypeName2", "")) != "MateGroup":
            continue
        child = safe(feature, "GetFirstSubFeature")
        while child is not None:
            found.append(child)
            child = safe(child, "GetNextSubFeature")
    return found


def find_mate_feature(doc: Any, name: str) -> Any | None:
    for child in mate_features(doc):
        if str(feature_property(child, "Name", "")) == name:
            return child
    return None


def feature_dimensions(feature: Any) -> list[dict[str, Any]]:
    """Driving dimensions owned by a feature: name, full name and the IDimension itself."""
    found: list[dict[str, Any]] = []
    display = safe(feature, "GetFirstDisplayDimension")
    guard = 0
    while display is not None and guard < 16:
        guard += 1
        dimension = None
        try:
            dimension = flag_methods(display, "GetDimension2").GetDimension2(0)
        except Exception:
            dimension = safe(display, "GetDimension")
        if dimension is not None:
            found.append({
                "name": str(safe(dimension, "Name", "")),
                "full_name": str(safe(dimension, "FullName", "")),
                "dimension": dimension,
            })
        try:
            display = flag_methods(feature, "GetNextDisplayDimension").GetNextDisplayDimension(display)
        except Exception:
            display = None
    return found


def _mate_entry(feature: Any) -> dict[str, Any]:
    """Describe one mate feature; shared by list_mates, edit_mate and add_mate."""
    # Advanced types read back by name too (the limit_* names are aliases of distance/angle, so skipped).
    reverse_types = {v: k for k, v in {**MATE_TYPES, **{k: v for k, v in ADV_MATE_TYPES.items() if not k.startswith('limit_')}}.items()}
    reverse_align = {v: k for k, v in MATE_ALIGNMENTS.items()}
    entry: dict[str, Any] = {
        "name": str(feature_property(feature, "Name", "")),
        "feature_type": str(feature_property(feature, "GetTypeName2", "")),
        "suppressed": bool(safe(feature, "IsSuppressed", False)),
    }
    definition = safe(feature, "GetSpecificFeature2")
    type_name = ""
    if definition is not None:
        code = safe(definition, "Type")
        if code is not None:
            type_name = reverse_types.get(int(code), f"type_{int(code)}")
            entry["mate_type"] = type_name
        align = safe(definition, "Alignment")
        if align is not None:
            entry["alignment"] = reverse_align.get(int(align), f"alignment_{int(align)}")
        flipped = safe(definition, "Flipped")
        if flipped is not None:
            entry["flipped"] = bool(flipped)
        for key, member in (("min_variation", "MinimumVariation"), ("max_variation", "MaximumVariation")):
            variation = safe(definition, member)
            if variation is not None:
                entry[key] = round(float(variation), 9)  # SI units, as SOLIDWORKS reports them
        entities = []
        count = safe(definition, "GetMateEntityCount")
        for index in range(int(count or 0)):
            try:
                entity = flag_methods(definition, "MateEntity").MateEntity(index)
            except Exception:
                break
            if entity is None:
                continue
            item: dict[str, Any] = {}
            reference_component = safe(entity, "ReferenceComponent")
            if reference_component is not None:
                item["component"] = str(safe(reference_component, "Name2", ""))
            reference_type = safe(entity, "ReferenceType2")
            if reference_type is not None:
                item["reference_type"] = int(reference_type)
            entities.append(item)
        entry["entities"] = entities

    dimensions = []
    for item in feature_dimensions(feature):
        raw = safe(item["dimension"], "SystemValue")
        row: dict[str, Any] = {"name": item["name"], "full_name": item["full_name"]}
        if raw is not None:
            if type_name == "angle":
                row["value_deg"] = round(to_deg(float(raw)), 6)
            else:
                row["value_mm"] = round(to_mm(float(raw)), 6)
        dimensions.append(row)
    entry["dimensions"] = dimensions
    if dimensions:
        # set_dimension takes the name as written in the feature tree.
        first = dimensions[0]["name"]
        # SOLIDWORKS 2017 reports the bare 'D1'; set_dimension wants 'D1@<mate feature>'.
        entry["dimension_name"] = first if "@" in first else f"{first}@{entry['name']}"
        entry["dimension_full_name"] = dimensions[0]["full_name"]
        if "value_mm" in dimensions[0]:
            entry["distance_mm"] = dimensions[0]["value_mm"]
        if "value_deg" in dimensions[0]:
            entry["angle_deg"] = dimensions[0]["value_deg"]
    return entry


def _transform_summary(matrix: list[float] | None) -> dict[str, Any] | None:
    if matrix is None:
        return None
    return {
        "rotation": [round(float(v), 9) for v in matrix[:9]],
        "translation_mm": mm_point(matrix[9:12]),
        "scale": round(float(matrix[12]), 9) if len(matrix) > 12 else 1.0,
    }


# --------------------------------------------------------------------------
# Transform math (pure functions: unit-tested offline)
# --------------------------------------------------------------------------


def translate_matrix(matrix: list[float], delta_m: list[float]) -> list[float]:
    """Return the transform data with the translation moved by ``delta_m`` (metres)."""
    moved = list(matrix[:16])
    for i in range(3):
        moved[9 + i] = float(matrix[9 + i]) + float(delta_m[i])
    return moved


def rotation_about(axis: list[float], angle_rad: float) -> list[list[float]]:
    """3x3 rotation matrix (rows) about ``axis`` by ``angle_rad`` (Rodrigues)."""
    length = math.sqrt(sum(c * c for c in axis))
    if length == 0:
        raise ValueError("The rotation axis must not be the zero vector.")
    x, y, z = (c / length for c in axis)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    t = 1.0 - c
    return [
        [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
        [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
    ]


def rotate_matrix(
    matrix: list[float], axis: list[float], angle_rad: float, pivot_m: list[float] | None = None
) -> list[float]:
    """Rotate a component transform about an axis through ``pivot_m`` (default: its origin).

    MathTransform data is stored so that ``apply_transform`` reads
    ``x' = m0*x + m3*y + m6*z``: element ``3*col + row`` of the rotation sits at
    index 0-8, translation at 9-11.
    """
    rot = rotation_about(axis, angle_rad)
    old = [[matrix[3 * col + row] for col in range(3)] for row in range(3)]
    new = [[sum(rot[r][k] * old[k][col] for k in range(3)) for col in range(3)] for r in range(3)]
    translation = [float(matrix[9 + i]) for i in range(3)]
    pivot = [float(c) for c in (pivot_m if pivot_m is not None else translation)]
    offset = [translation[i] - pivot[i] for i in range(3)]
    new_translation = [sum(rot[r][k] * offset[k] for k in range(3)) + pivot[r] for r in range(3)]
    rotated = list(matrix[:16])
    for row in range(3):
        for col in range(3):
            rotated[3 * col + row] = new[row][col]
    rotated[9:12] = new_translation
    return rotated


def _set_component_matrix(app: Any, component: Any, matrix: list[float]) -> None:
    math_utility = value(app, "GetMathUtility")
    transform = flag_methods(math_utility, "CreateTransform").CreateTransform(double_array(matrix[:16]))
    flag_methods(component, "SetTransformAndSolve2").SetTransformAndSolve2(transform)


def _open_silently(app: Any, doc: Any, path: Path, doc_type: int, configuration: str = "") -> None:
    """Load a referenced document and hand activation back to the assembly."""
    errors, warnings = byref_long(0), byref_long(0)
    try:
        app.OpenDoc6(str(path), doc_type, 1, configuration, errors, warnings)
    except Exception:
        logger.info("Silent open of %s failed; letting SOLIDWORKS resolve it.", path)
    # OpenDoc6 makes the opened part the active document; hand activation back to
    # the assembly so later assembly tools (and the next insert) still see it.
    try:
        assembly_title = str(value(doc, "GetTitle"))
        flag_methods(app, "ActivateDoc3").ActivateDoc3(assembly_title, True, 0, byref_long(0))
    except Exception:
        logger.info("Could not re-activate the assembly after loading %s.", path.name)


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------


@tool(
    "list_components",
    "Read-only: list the components of the active assembly with path, configuration, fixed, "
    "hidden, suppression state, virtual flag, origin and full transform (rotation, translation_mm, scale).",
    {"top_level_only": {"type": "boolean", "default": True}},
)
def list_components(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    components = []
    for component in iter_components(doc, bool(args.get("top_level_only", True))):
        matrix = component_transform(component)
        name = str(safe(component, "Name2", ""))
        entry: dict[str, Any] = {
            "name": name,
            "path": str(safe(component, "GetPathName", "")),
            "suppressed": bool(safe(component, "IsSuppressed", False)),
            "fixed": bool(safe(component, "IsFixed", False)),
            "configuration": str(safe(component, "ReferencedConfiguration", "") or ""),
            "depth": name.count("/"),
        }
        visible = safe(component, "Visible")
        if visible is not None:
            entry["hidden"] = int(visible) == 0
        virtual = safe(component, "IsVirtual")
        if virtual is not None:
            entry["virtual"] = bool(virtual)
        state = safe(component, "GetSuppression")
        if state is not None:
            # swComponentSuppressionState_e: 0 suppressed, 1/4 lightweight, 2/3 resolved
            names = {0: "suppressed", 1: "lightweight", 2: "resolved", 3: "resolved", 4: "lightweight"}
            entry["suppression_state"] = names.get(int(state), f"state_{int(state)}")
        if matrix is not None:
            entry["origin_mm"] = mm_point(apply_transform([0.0, 0.0, 0.0], matrix))
            entry["transform"] = _transform_summary(matrix)
        components.append(entry)
    return result(True, f"Read {len(components)} components.", components=components)


@tool(
    "insert_component",
    "Insert a part or sub-assembly (.sldprt or .sldasm) into the active assembly at the given position. "
    "Position is millimetres in assembly space and is where the component's ORIGIN lands "
    "(corrected after insertion on SOLIDWORKS 2017); the result reports origin_mm and the configuration used.",
    {
        "path": {"type": "string", "description": "Full path to the .sldprt or .sldasm file."},
        "x_mm": {"type": "number", "default": 0},
        "y_mm": {"type": "number", "default": 0},
        "z_mm": {"type": "number", "default": 0},
        "configuration": {"type": "string", "description": "Named configuration to insert. Defaults to the active one."},
    },
    ["path"],
)
def insert_component(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = require_assembly()
    path = Path(str(args["path"])).expanduser().resolve()
    if not path.is_file():
        return result(False, f"No such file: {path}")
    doc_type = {".sldprt": 1, ".sldasm": 2}.get(path.suffix.lower())
    if doc_type is None:
        return result(False, "Only .sldprt and .sldasm files can be inserted as components.")

    configuration = str(args.get("configuration", "") or "")
    # AddComponent5 needs the referenced document loaded; open it silently first.
    _open_silently(app, doc, path, doc_type, configuration)

    # swAddComponentConfigOptions_e has no "use the named configuration" value: 0 is
    # CurrentSelectedConfig (which honours ExistingConfigName), 1 and 2 CREATE new
    # configurations and 2 fails outright on 2017 (verified live).
    option = 0
    component = doc.AddComponent5(
        str(path), option, "", False, configuration,
        to_m(args.get("x_mm", 0)), to_m(args.get("y_mm", 0)), to_m(args.get("z_mm", 0)),
    )
    if component is None:
        return result(False, f"SOLIDWORKS did not insert {path.name} into the assembly.")
    if configuration and str(safe(component, "ReferencedConfiguration", "") or "") != configuration:
        # ExistingConfigName is ignored when the part's active configuration differs (it follows
        # whichever configuration was opened last), so switch the new component explicitly.
        try:
            component.ReferencedConfiguration = configuration
        except Exception:
            logger.info("Could not switch %s to configuration %s after inserting it.", path.name, configuration)

    # On 2017 AddComponent5 puts the component's bounding-box centre (not its
    # origin) at x/y/z, measured live: a part inserted at (0,0,0) had its origin
    # at minus its bbox centre.  Read the placed origin back and translate by the
    # difference so x/y/z mean "where the component origin lands".
    target = [to_m(args.get("x_mm", 0)), to_m(args.get("y_mm", 0)), to_m(args.get("z_mm", 0))]
    corrected: bool | None = None
    matrix = component_transform(component)
    if matrix is not None:
        shifted = corrective_matrix(matrix, target)
        if shifted is not None:
            try:
                _set_component_matrix(app, component, shifted)
                corrected = True
            except Exception:
                logger.info("Could not move %s to the requested origin", path.name, exc_info=True)
                corrected = False
    rebuild(doc)
    final_matrix = component_transform(component)
    origin = mm_point(apply_transform([0.0, 0.0, 0.0], final_matrix)) if final_matrix else None
    used = str(safe(component, "ReferencedConfiguration", "") or "")
    payload = result(
        True,
        f"Inserted {path.name}.",
        component=str(safe(component, "Name2", "")),
        path=str(path),
        origin_mm=origin,
        configuration=used,
        is_assembly=doc_type == 2,
    )
    if corrected is False:
        payload["data"]["warning"] = (
            "Could not move the component origin to the requested point; origin_mm shows where it landed."
        )
    elif corrected:
        payload["data"]["origin_corrected"] = True
    if configuration and used and used != configuration:
        payload["data"]["configuration_warning"] = (
            f"Requested configuration '{configuration}' but the component references '{used}'."
        )
    return payload


def corrective_matrix(matrix: list[float], target_m: list[float], tol_m: float = 1e-9) -> list[float] | None:
    """Return the MathTransform data with its translation moved to ``target_m``.

    ``matrix`` is the 16-double MathTransform data (translation at 9-11, metres).
    Returns None when the origin is already within ``tol_m`` of the target.  The
    placed origin of a component is its transform translation, so the result puts
    the origin exactly on the target while keeping rotation and scale.
    """
    if all(abs(matrix[9 + i] - target_m[i]) <= tol_m for i in range(3)):
        return None
    shifted = list(matrix[:16])
    shifted[9:12] = [float(c) for c in target_m]
    return shifted


def _select_mate_entity(doc: Any, spec: dict[str, Any], append: bool) -> str:
    """Select one mate reference described by component plus face/edge/vertex index, plane or point.

    Returns a short description of what was selected; raises RuntimeError if nothing was.
    """
    mark = int(spec.get("mark", 0))

    if "point" in spec:
        point = spec["point"]
        coords = [to_m(point["x_mm"]), to_m(point["y_mm"]), to_m(point["z_mm"])]
        select_type = str(point.get("type", "FACE")).upper()
        if not select_at_point(doc, select_type, coords, mark, append):
            raise RuntimeError(f"Nothing of type {select_type} was found at {point}.")
        return f"{select_type} at point"

    if not spec.get("component"):
        raise RuntimeError("Each entity needs a 'component' (plus face/edge/vertex/plane) or a 'point'.")
    component = require_component(doc, str(spec["component"]))

    if spec.get("plane"):
        identifier = str(safe(component, "GetSelectByIDString", "") or str(spec["component"]))
        if not select_by_id(doc, f"{spec['plane']}@{identifier}", "PLANE", mark, append, extension(doc)):
            raise RuntimeError(f"Could not select plane '{spec['plane']}' of {spec['component']}.")
        return f"plane {spec['plane']} of {spec['component']}"

    for key, getter in (("face", "GetFaces"), ("edge", "GetEdges"), ("vertex", "GetVertices")):
        if spec.get(key) is None:
            continue
        index = int(spec[key])
        candidates: list[Any] = []
        for body in component_bodies(component):
            candidates.extend(as_list(safe(body, getter)))
        if not 0 <= index < len(candidates):
            raise RuntimeError(
                f"{key.capitalize()} index {index} is out of range for {spec['component']} "
                f"(0..{len(candidates) - 1})."
            )
        # Select the object from the component's in-context body so the mate
        # reference carries the component, not a bare part face.
        if not select_object(doc, candidates[index], mark, append):
            raise RuntimeError(f"Could not select {key} {index} of {spec['component']}.")
        return f"{key} {index} of {spec['component']}"

    # Component alone: select the component itself.
    identifier = str(safe(component, "GetSelectByIDString", "") or "")
    if not (identifier and select_by_id(doc, identifier, "COMPONENT", mark, append)):
        if not select_object(doc, component, mark, append):
            raise RuntimeError(f"Could not select component '{spec['component']}'.")
    return f"component {spec['component']}"


ENTITY_SCHEMA = {
    "type": "array",
    "description": (
        "Mate references picked by component name instead of raw selection: each item is "
        "{component, face|edge|vertex: index within that component's bodies, or plane: 'Front Plane', "
        "or point:{x_mm,y_mm,z_mm,type}, mark?: width/limit mark}. Order matters; usually two items. "
        "For a width mate give the two width faces mark 1 and the two tab faces mark 2 (sent to SOLIDWORKS as mark 16, which 2017 requires)."
    ),
    "items": {
        "type": "object",
        "properties": {
            "component": {"type": "string"},
            "face": {"type": "integer"},
            "edge": {"type": "integer"},
            "vertex": {"type": "integer"},
            "plane": {"type": "string"},
            "point": {
                "type": "object",
                "properties": {
                    "x_mm": {"type": "number"}, "y_mm": {"type": "number"}, "z_mm": {"type": "number"},
                    "type": {"type": "string", "enum": ["FACE", "EDGE", "VERTEX"], "default": "FACE"},
                },
                "required": ["x_mm", "y_mm", "z_mm"],
            },
            "mark": {"type": "integer", "default": 0},
            "role": {
                "type": "string",
                "description": "cam: cam|follower; hinge: concentric|coincident; path: point|path; symmetric: symmetry_plane|entity. Sets the selection mark.",
            },
        },
    },
}


@tool(
    "add_mate",
    "Mate entities in the active assembly. Pick them with a raw selection spec and/or entities "
    "(component + face/edge/vertex index or plane name), then name the mate type. "
    "Distance is millimetres, angle is degrees. Supports limit distance/angle mates "
    "(min/max values; limit_distance / limit_angle insist on both), width mates (width_option, "
    "width_percent) and the advanced types gear (ratio_num/ratio_den/reverse), rack_pinion "
    "(distance_per_rev_mm), screw (pitch_mm), cam, hinge and path (entities may carry a 'role'), "
    "slot (slot_constraint free|center|distance|percent) and symmetric. Note: gear and screw mates build "
    "(types 10 and 17) but their motion coupling (ratio, direction, pitch) could not be verified through "
    "the 2017 API (live C1). The result reports the "
    "mate and feature counts before/after and the mate type SOLIDWORKS actually built.",
    {
        "mate_type": {"type": "string", "enum": sorted({*MATE_TYPES, *ADV_MATE_TYPES})},
        "selection": SELECTION_SCHEMA,
        "entities": ENTITY_SCHEMA,
        "alignment": {"type": "string", "enum": sorted(MATE_ALIGNMENTS), "default": "closest"},
        "distance_mm": {"type": "number", "default": 0, "description": "Used by mate_type=distance (and width_option=dimension)."},
        "min_distance_mm": {"type": "number", "description": "Lower limit; with max_distance_mm makes a limit distance mate."},
        "max_distance_mm": {"type": "number", "description": "Upper limit of a limit distance mate."},
        "angle_deg": {"type": "number", "default": 0, "description": "Used by mate_type=angle."},
        "min_angle_deg": {"type": "number", "description": "Lower limit of a limit angle mate."},
        "max_angle_deg": {"type": "number", "description": "Upper limit of a limit angle mate."},
        "width_option": {"type": "string", "enum": ["centered", "dimension", "free", "percent"], "default": "centered", "description": "Used by mate_type=width."},
        "flip": {"type": "boolean", "default": False},
        "lock_rotation": {"type": "boolean", "default": False},
        "ratio_num": {"type": "number", "exclusiveMinimum": 0, "description": "mate_type=gear: numerator of the ratio."},
        "ratio_den": {"type": "number", "exclusiveMinimum": 0, "description": "mate_type=gear: denominator of the ratio."},
        "reverse": {"type": "boolean", "description": "Gear/rack_pinion/screw: opposite direction of rotation."},
        "distance_per_rev_mm": {"type": "number", "exclusiveMinimum": 0, "description": "mate_type=rack_pinion."},
        "pitch_mm": {"type": "number", "exclusiveMinimum": 0, "description": "mate_type=screw."},
        "slot_constraint": {"type": "string", "enum": ["free", "center", "distance", "percent"], "description": "mate_type=slot."},
        "slot_percent": {"type": "number", "minimum": 0, "maximum": 100, "description": "slot_constraint=percent."},
        "width_percent": {"type": "number", "minimum": 0, "maximum": 100, "description": "width_option=percent."},
    },
    ["mate_type"],
)
def add_mate(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    if not args.get("selection") and not args.get("entities"):
        return result(False, "Pass selection or entities to say what to mate.")
    refused = UNSUPPORTED_MATE_TYPES.get(str(args["mate_type"]))
    if refused:
        return result(False, f"Not supported on SOLIDWORKS 2017: {refused}", fenced=True)
    # Advanced mate types (Batch C): validate and map every argument before COM is touched.
    try:
        plan = plan_advanced_mate(args)
        plan_marks = assign_marks(plan, list(args.get("entities") or [])) if plan else None
    except ValueError as exc:
        return result(False, str(exc))
    count = 0
    picked: list[str] = []
    if args.get("selection"):
        count += require_selection(doc, args["selection"])
    for position, spec in enumerate(args.get("entities") or []):
        if plan_marks and plan_marks[position]:
            spec = {**spec, "mark": plan_marks[position]}
        if str(args["mate_type"]) == "width" and int(spec.get("mark", 0)) == 2:
            # Live-verified on 2017 SP5: AddMate5 refuses a width mate unless the tab faces carry
            # selection mark 16 (marks 2, 4, 8 fail with no status); the width faces use mark 1.
            spec = {**spec, "mark": 16}
        try:
            picked.append(_select_mate_entity(doc, spec, append=count > 0))
        except RuntimeError as exc:
            clear_selection(doc)
            return result(False, str(exc))
        count += 1
    if plan and count < plan.min_entities:
        clear_selection(doc)
        return result(False, f"A {args['mate_type']} mate needs at least {plan.min_entities} entities; {count} were selected.")
    mate_type = plan.mate_type if plan else MATE_TYPES[str(args["mate_type"])]
    alignment = MATE_ALIGNMENTS[str(args.get("alignment", "closest"))]
    # swMateWidth_e: 0 centered, 1 free, 2 dimension, 3 percent
    width_option = {"centered": 0, "free": 1, "dimension": 2, "percent": 3}[str(args.get("width_option", "centered"))]
    if plan and plan.width_option is not None:
        width_option = plan.width_option
    status = byref_long(0)

    distance = args.get("distance_mm", 0)
    angle = args.get("angle_deg", 0)
    # Without limits the three distances (and angles) are equal, which is what
    # a plain mate wants; a limit mate gets value/upper/lower.
    upper_d = args.get("max_distance_mm", distance)
    lower_d = args.get("min_distance_mm", distance)
    upper_a = args.get("max_angle_deg", angle)
    lower_a = args.get("min_angle_deg", angle)
    if float(lower_d) > float(upper_d) or float(lower_a) > float(upper_a):
        clear_selection(doc)
        return result(False, "min limit must not exceed max limit.")

    before = {str(feature_property(f, "Name", "")) for f in mate_features(doc)}
    tree_before = len(iter_feature_objects(doc)) if plan else 0
    if plan:
        plan.width_option = width_option
        mate_args = plan.addmate5_args(alignment, status)
    else:
        mate_args = (
            mate_type, alignment, bool(args.get("flip", False)),
            to_m(distance), to_m(upper_d), to_m(lower_d),
            1.0, 1.0,
            to_rad(angle), to_rad(upper_a), to_rad(lower_a),
            False, bool(args.get("lock_rotation", False)), width_option, status,
        )
    with dialogs_suppressed():
        # Hinge/path/cam/slot/gear mates can open a PropertyManager or a modal that blocks COM forever.
        mate = doc.AddMate5(*mate_args)
    code = int(status.value)
    clear_selection(doc)
    rebuild(doc)
    if mate is None:
        return result(
            False,
            f"SOLIDWORKS refused the mate: {ADD_MATE_ERRORS.get(code, f'status {code}')}.",
            entities=count,
            status=code,
        )
    # IMate2 has no Name; the owning feature is the newest entry in the MateGroup.
    created = [f for f in mate_features(doc) if str(feature_property(f, "Name", "")) not in before]
    info = _mate_entry(created[-1]) if created else {}
    extra: dict[str, Any] = {"mate": info.get("name", ""), "entities": count}
    if plan:
        built = safe(mate, "Type")
        mates_after = len(mate_features(doc))
        extra.update(
            requested_type=plan.mate_type,
            built_type=None if built is None else int(built),
            mate_count_before=len(before),
            mate_count_after=mates_after,
            feature_count_before=tree_before,
            feature_count_after=len(iter_feature_objects(doc)),
            live_probe=plan.probes,
        )
        if mates_after <= len(before):
            # The measured mate count decides, not the AddMate5 return value (ADR global rule 3).
            return result(
                False,
                f"AddMate5 returned a mate but the mate count did not grow ({len(before)} -> {mates_after}); "
                "treat it as a silent no-op.",
                status=code,
                **extra,
            )
        if built is None:
            extra["type_unverified"] = True
        elif int(built) != plan.mate_type:
            # Success is the measured type, not the return value (ADR global rule 3).
            return result(
                False,
                f"SOLIDWORKS built a type-{int(built)} mate, not the requested {args['mate_type']} "
                f"(type {plan.mate_type}); delete_mate it and re-check the selection marks.",
                status=code,
                **extra,
            )
    if picked:
        extra["picked"] = picked
    if info.get("dimensions"):
        extra["dimensions"] = info["dimensions"]
    if code != 1:
        # An over-defining mate is still added to the tree, so reporting a
        # plain failure here would contradict what list_mates shows.
        return result(
            True,
            f"Added a {args['mate_type']} mate, but SOLIDWORKS flagged it: "
            f"{ADD_MATE_ERRORS.get(code, f'status {code}')}.",
            warning=ADD_MATE_ERRORS.get(code, f"status {code}"),
            status=code,
            **extra,
        )
    return result(True, f"Added a {args['mate_type']} mate.", **extra)


@tool(
    "list_mates",
    "Read-only: list the mates of the active assembly with type, alignment, flipped, suppressed state, "
    "the components each mate references, and its dimensions (name such as 'D1@Distance1' usable with "
    "set_dimension, plus value_mm or value_deg).",
    {},
)
def list_mates(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    mates = [_mate_entry(child) for child in mate_features(doc)]
    return result(True, f"Read {len(mates)} mates.", mates=mates)


@tool(
    "edit_mate",
    "Edit an existing mate by name (see list_mates): change its distance or angle value, flip it, "
    "change its alignment, or set limit min/max. A value-only change edits the mate's dimension; "
    "anything else re-creates the mate (EditMate4 does nothing on 2017) from the same entities, restoring the original if SOLIDWORKS refuses.",
    {
        "mate_name": {"type": "string"},
        "distance_mm": {"type": "number"},
        "angle_deg": {"type": "number"},
        "flip": {"type": "boolean", "description": "Target flipped state (not a toggle)."},
        "alignment": {"type": "string", "enum": sorted(MATE_ALIGNMENTS)},
        "min_distance_mm": {"type": "number"},
        "max_distance_mm": {"type": "number"},
        "min_angle_deg": {"type": "number"},
        "max_angle_deg": {"type": "number"},
    },
    ["mate_name"],
)
def edit_mate(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    name = str(args["mate_name"])
    feature = find_mate_feature(doc, name)
    if feature is None:
        return result(False, f"No mate named '{name}' exists. Call list_mates to see valid names.")
    before = _mate_entry(feature)
    definition = safe(feature, "GetSpecificFeature2")
    mate_type = before.get("mate_type", "")

    value_keys = ("distance_mm", "angle_deg")
    other_keys = ("flip", "alignment", "min_distance_mm", "max_distance_mm", "min_angle_deg", "max_angle_deg")
    wants_value = any(args.get(k) is not None for k in value_keys)
    wants_other = any(args.get(k) is not None for k in other_keys)
    if not wants_value and not wants_other:
        return result(False, "Nothing to change: pass distance_mm, angle_deg, flip, alignment or limits.")
    if args.get("distance_mm") is not None and mate_type != "distance":
        return result(False, f"Mate '{name}' is a {mate_type or 'non-distance'} mate; distance_mm applies to distance mates.")
    if args.get("angle_deg") is not None and mate_type != "angle":
        return result(False, f"Mate '{name}' is a {mate_type or 'non-angle'} mate; angle_deg applies to angle mates.")

    if wants_value and not wants_other:
        dims = feature_dimensions(feature)
        if not dims:
            return result(False, f"Mate '{name}' has no dimension to edit.")
        target = to_m(args["distance_mm"]) if args.get("distance_mm") is not None else to_rad(args["angle_deg"])
        dimension = dims[0]["dimension"]
        flag_methods(dimension, "SetSystemValue3")
        # swSetValue_InAllConfigurations = 2
        code = int(dimension.SetSystemValue3(target, 2, empty_variant()))
        actual = float(safe(dimension, "SystemValue", target) or 0.0)
        rebuild(doc)
        if abs(actual - target) > 1e-9:
            return result(False, f"SOLIDWORKS did not accept the new value for mate '{name}'.", status=code)
        return result(True, f"Set mate '{name}'.", mate=_mate_entry(feature), previous=before)

    # Re-create the mate.  IAssemblyDoc.EditMate4 is accepted on 2017 SP5 but changes nothing
    # (live-verified for flip, alignment, distance and limits), so the definition is rebuilt:
    # remember the referenced entities, delete the mate, and add it again with the new settings.
    if definition is None:
        return result(False, f"Could not read the definition of mate '{name}'.")
    if mate_type == "width":
        return result(False, "Width mates cannot be edited (their width/tab marks are not recoverable); delete_mate and add_mate again.")
    references: list[Any] = []
    for index in range(int(safe(definition, "GetMateEntityCount", 0) or 0)):
        entity = flag_methods(definition, "MateEntity").MateEntity(index)
        reference = safe(entity, "Reference") if entity is not None else None
        if reference is None:
            return result(False, f"Could not recover the entities of mate '{name}'; delete_mate and add_mate again.")
        references.append(reference)

    def settings(distance_mm: float, lower_d: float, upper_d: float, angle_deg: float, lower_a: float, upper_a: float,
                 align: int, flip: bool) -> tuple[Any, ...]:
        return (
            int(safe(definition, "Type", 0)), align, flip,
            to_m(distance_mm), to_m(upper_d), to_m(lower_d), 1.0, 1.0,
            to_rad(angle_deg), to_rad(upper_a), to_rad(lower_a), False, False, 0,
        )

    old_d = float(before.get("distance_mm", 0.0)) if mate_type == "distance" else 0.0
    old_a = float(before.get("angle_deg", 0.0)) if mate_type == "angle" else 0.0
    # Variations are stored relative to the value, in metres / radians.
    old_min_v, old_max_v = float(before.get("min_variation", 0.0)), float(before.get("max_variation", 0.0))
    old_lower_d, old_upper_d = old_d + to_mm(old_min_v), old_d + to_mm(old_max_v)
    old_lower_a, old_upper_a = old_a + math.degrees(old_min_v), old_a + math.degrees(old_max_v)
    old_align = int(safe(definition, "Alignment", MATE_ALIGNMENTS["closest"]))
    old_flip = bool(safe(definition, "Flipped", False))
    original = settings(old_d, old_lower_d, old_upper_d, old_a, old_lower_a, old_upper_a, old_align, old_flip) if mate_type in ("distance", "angle") else         settings(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, old_align, old_flip)

    distance_mm = args.get("distance_mm", old_d)
    angle_deg = args.get("angle_deg", old_a)
    lower_d = args.get("min_distance_mm", old_lower_d if mate_type == "distance" else distance_mm)
    upper_d = args.get("max_distance_mm", old_upper_d if mate_type == "distance" else distance_mm)
    lower_a = args.get("min_angle_deg", old_lower_a if mate_type == "angle" else angle_deg)
    upper_a = args.get("max_angle_deg", old_upper_a if mate_type == "angle" else angle_deg)
    if float(lower_d) > float(upper_d) or float(lower_a) > float(upper_a):
        return result(False, "min limit must not exceed max limit.")
    align = MATE_ALIGNMENTS[str(args["alignment"])] if args.get("alignment") is not None else old_align
    flip = bool(args["flip"]) if args.get("flip") is not None else old_flip
    wanted = settings(distance_mm, lower_d, upper_d, angle_deg, lower_a, upper_a, align, flip)

    def add(values: tuple[Any, ...]) -> tuple[Any, int]:
        clear_selection(doc)
        for reference in references:
            if not select_object(doc, reference, 0, True):
                return None, -1
        status = byref_long(0)
        created = doc.AddMate5(*values, status)
        return created, int(status.value)

    deleted = delete_mate({"mate_name": name})
    if not deleted.get("ok"):
        return result(False, f"Could not replace mate '{name}': {deleted.get('message')}")
    created, code = add(wanted)
    if created is None:
        restored, _ = add(original)
        clear_selection(doc)
        rebuild(doc)
        return result(
            False,
            f"SOLIDWORKS refused the edited mate: {ADD_MATE_ERRORS.get(code, f'status {code}')}. "
            + ("The original mate was restored." if restored is not None else "The original mate could NOT be restored; re-add it."),
            status=code,
            restored=restored is not None,
        )
    clear_selection(doc)
    rebuild(doc)
    new_names = [str(feature_property(f, "Name", "")) for f in mate_features(doc)]
    refreshed = find_mate_feature(doc, name) or (find_mate_feature(doc, new_names[-1]) if new_names else None)
    if refreshed is not None and str(feature_property(refreshed, "Name", "")) != name:
        try:
            refreshed.Name = name  # keep the mate's name stable across the re-creation
        except Exception:
            logger.info("Could not restore the name '%s' on the re-created mate.", name)
    return result(
        True,
        f"Edited mate '{name}' (re-created as '{feature_property(refreshed, 'Name', name) if refreshed is not None else name}').",
        mate=_mate_entry(refreshed) if refreshed is not None else {},
        previous=before,
        status=code,
    )


@tool(
    "set_mate_suppression",
    "Suppress or unsuppress mates by name (see list_mates). Suppressed mates stop constraining the "
    "components, which can then move.",
    {
        "mate_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "suppressed": {"type": "boolean", "default": True},
    },
    ["mate_names"],
)
def set_mate_suppression(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    suppressed = bool(args.get("suppressed", True))
    changed: list[str] = []
    for raw in args["mate_names"]:
        name = str(raw)
        feature = find_mate_feature(doc, name)
        if feature is None:
            clear_selection(doc)
            return result(False, f"No mate named '{name}' exists. Call list_mates to see valid names.")
        clear_selection(doc)
        if not bool(selectable(feature).Select2(False, 0)):
            return result(False, f"Could not select mate '{name}'.")
        # Zero-argument methods: go through value(), not a direct call.
        if bool(value(doc, "EditSuppress2" if suppressed else "EditUnsuppress2")):
            changed.append(name)
    clear_selection(doc)
    rebuild(doc)
    state: dict[str, bool] = {}
    for name in changed:
        feature = find_mate_feature(doc, name)
        state[name] = bool(safe(feature, "IsSuppressed", False)) if feature is not None else False
    verified = all(state.get(n) == suppressed for n in changed)
    return result(
        bool(changed) and verified,
        f"{'Suppressed' if suppressed else 'Unsuppressed'} {len(changed)} mates."
        + ("" if verified else " Readback disagrees; check list_mates."),
        changed=changed,
        suppressed_state=state,
    )


@tool(
    "set_component_fixed",
    "Fix or float the named components in the active assembly.",
    {
        "component_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "fixed": {"type": "boolean", "default": True},
    },
    ["component_names"],
)
def set_component_fixed(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    names = [str(name) for name in args["component_names"]]
    require_selection(doc, {"components": names})
    if bool(args.get("fixed", True)):
        doc.FixComponent()
    else:
        doc.UnfixComponent()
    clear_selection(doc)
    rebuild(doc)
    return result(True, f"Set fixed={args.get('fixed', True)} on {len(names)} components.", components=names)


@tool(
    "delete_mate",
    "Delete one mate from the active assembly by its name (see list_mates). Nothing else is deleted.",
    {"mate_name": {"type": "string"}},
    ["mate_name"],
)
def delete_mate(args: dict[str, Any]) -> dict[str, Any]:
    from .sw_core import extension, feature_property, iter_feature_objects, selectable

    _, doc = require_assembly()
    name = str(args["mate_name"])
    target = None
    # Mates are sub-features of the MateGroup, which find_feature does not
    # descend into, so delete_feature cannot reach them.
    for feature in iter_feature_objects(doc):
        if str(feature_property(feature, "GetTypeName2", "")) != "MateGroup":
            continue
        child = safe(feature, "GetFirstSubFeature")
        while child is not None:
            if str(feature_property(child, "Name", "")) == name:
                target = child
                break
            child = safe(child, "GetNextSubFeature")
        if target is not None:
            break
    if target is None:
        return result(False, f"No mate named '{name}' exists. Call list_mates to see valid names.")
    clear_selection(doc)
    if not bool(selectable(target).Select2(False, 0)):
        return result(False, f"Could not select mate '{name}'.")
    deleted = bool(extension(doc).DeleteSelection2(0))
    rebuild(doc)
    clear_selection(doc)
    return result(
        deleted,
        f"Deleted mate '{name}'." if deleted else "SOLIDWORKS refused to delete the mate.",
        deleted=name,
    )


def _origin_mm(component: Any) -> list[float] | None:
    matrix = component_transform(component)
    return mm_point(apply_transform([0.0, 0.0, 0.0], matrix)) if matrix else None


def _movable(doc: Any, name: str) -> tuple[Any, list[float]]:
    """Return a floating component and its transform, or raise RuntimeError."""
    component = require_component(doc, name)
    if bool(safe(component, "IsFixed", False)):
        raise RuntimeError(f"Component '{name}' is fixed; unfix it first (set_component_fixed fixed=false).")
    if bool(safe(component, "IsSuppressed", False)):
        raise RuntimeError(f"Component '{name}' is suppressed.")
    matrix = component_transform(component)
    if matrix is None:
        raise RuntimeError(f"Could not read the transform of '{name}'.")
    return component, matrix


def _moved_result(app: Any, doc: Any, component: Any, name: str, wanted: list[float], verb: str) -> dict[str, Any]:
    _set_component_matrix(app, component, wanted)
    rebuild(doc)
    final = component_transform(component)
    achieved = final[9:12] if final else None
    constrained = achieved is not None and any(abs(achieved[i] - wanted[9 + i]) > 1e-6 for i in range(3))
    if final is not None and not constrained:
        # Rotation can also be pushed back by mates.
        constrained = any(abs(final[i] - wanted[i]) > 1e-6 for i in range(9))
    payload = result(
        True,
        f"{verb} '{name}'.",
        component=name,
        origin_mm=_origin_mm(component),
        transform=_transform_summary(final),
    )
    if constrained:
        payload["data"]["requested_origin_mm"] = mm_point(wanted[9:12])
        payload["data"]["warning"] = (
            "The component did not land where requested (see requested_origin_mm vs origin_mm); mates are "
            "constraining it. Programmatic moves are re-solved against the mates: a limit_distance/limit_angle "
            "mate snaps back to its stored value (its min/max range only applies to interactive drags), and "
            "a coincident mate only leaves its free directions movable. Suppress or edit the mates "
            "(set_mate_suppression / edit_mate) to move it freely."
        )
    return payload


@tool(
    "move_component",
    "Move a floating (not fixed) component. mode=relative adds x/y/z to its current origin; "
    "mode=absolute puts its origin at x/y/z. Millimetres, assembly space. Mates still apply: the move is "
    "re-solved, so only directions the mates leave free actually change (limit mates snap back to their stored "
    "value). Always check origin_mm in the result; a 'warning' means the request was not honoured.",
    {
        "component": {"type": "string", "description": "Component name from list_components."},
        "x_mm": {"type": "number", "default": 0},
        "y_mm": {"type": "number", "default": 0},
        "z_mm": {"type": "number", "default": 0},
        "mode": {"type": "string", "enum": ["relative", "absolute"], "default": "relative"},
    },
    ["component"],
)
def move_component(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = require_assembly()
    name = str(args["component"])
    try:
        component, matrix = _movable(doc, name)
    except RuntimeError as exc:
        return result(False, str(exc))
    vector = [to_m(args.get("x_mm", 0)), to_m(args.get("y_mm", 0)), to_m(args.get("z_mm", 0))]
    if str(args.get("mode", "relative")) == "absolute":
        wanted = list(matrix[:16])
        wanted[9:12] = vector
    else:
        wanted = translate_matrix(matrix, vector)
    return _moved_result(app, doc, component, name, wanted, "Moved")


@tool(
    "rotate_component",
    "Rotate a floating (not fixed) component about an axis. The axis is x, y, z or a [x,y,z] vector in "
    "assembly space; it passes through pivot_mm (default: the component's own origin). Angle in degrees.",
    {
        "component": {"type": "string"},
        "axis": {
            "description": "'x', 'y', 'z' or a three-number vector.",
            "anyOf": [
                {"type": "string", "enum": ["x", "y", "z"]},
                {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            ],
        },
        "angle_deg": {"type": "number"},
        "pivot_mm": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
    },
    ["component", "axis", "angle_deg"],
)
def rotate_component(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = require_assembly()
    name = str(args["component"])
    axis_arg = args["axis"]
    unit = {"x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}
    axis = unit.get(str(axis_arg).lower()) if isinstance(axis_arg, str) else [float(c) for c in axis_arg]
    if axis is None or len(axis) != 3 or not any(axis):
        return result(False, "axis must be 'x', 'y', 'z' or a non-zero [x, y, z] vector.")
    try:
        component, matrix = _movable(doc, name)
    except RuntimeError as exc:
        return result(False, str(exc))
    pivot = [to_m(c) for c in args["pivot_mm"]] if args.get("pivot_mm") else None
    wanted = rotate_matrix(matrix, axis, to_rad(args["angle_deg"]), pivot)
    return _moved_result(app, doc, component, name, wanted, "Rotated")


@tool(
    "set_component_configuration",
    "Switch which configuration of its part/sub-assembly a component uses. Reports the configurations "
    "that exist if the name is wrong.",
    {"component": {"type": "string"}, "configuration": {"type": "string"}},
    ["component", "configuration"],
)
def set_component_configuration(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    name, wanted = str(args["component"]), str(args["configuration"])
    try:
        component = require_component(doc, name)
    except RuntimeError as exc:
        return result(False, str(exc))
    model = safe(component, "GetModelDoc2")
    if model is not None:
        names = [str(n) for n in as_list(safe(model, "GetConfigurationNames"))]
        if names and wanted not in names:
            return result(False, f"'{wanted}' is not a configuration of {name}. Available: {names}")
    previous = str(safe(component, "ReferencedConfiguration", "") or "")
    component.ReferencedConfiguration = wanted
    rebuild(doc)
    current = str(safe(component, "ReferencedConfiguration", "") or "")
    return result(
        current == wanted,
        f"Set {name} to configuration '{current}'." if current == wanted
        else f"SOLIDWORKS left {name} on configuration '{current}'.",
        component=name,
        previous=previous,
        configuration=current,
    )


@tool(
    "set_component_visibility",
    "Hide or show components of the active assembly. Hiding does not change mass or mates.",
    {
        "component_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "visible": {"type": "boolean", "default": True},
    },
    ["component_names"],
)
def set_component_visibility(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    visible = bool(args.get("visible", True))
    names = [str(n) for n in args["component_names"]]
    try:
        require_selection(doc, {"components": names})
    except RuntimeError as exc:
        clear_selection(doc)
        return result(False, str(exc))
    # IModelDoc2 members, no arguments: call through value().
    value(doc, "ShowComponent2" if visible else "HideComponent2")
    clear_selection(doc)
    rebuild(doc)
    state = {}
    for name in names:
        component = find_component(doc, name)
        raw = safe(component, "Visible") if component is not None else None
        state[name] = None if raw is None else int(raw) != 0
    ok = all(v is None or v == visible for v in state.values())
    return result(
        ok,
        f"{'Showed' if visible else 'Hid'} {len(names)} components." + ("" if ok else " Readback disagrees."),
        components=names,
        visible_state=state,
    )


@tool(
    "set_component_suppression",
    "Suppress or resolve (unsuppress) components of the active assembly. Suppressed components drop "
    "out of mass properties and their mates stop applying.",
    {
        "component_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "suppressed": {"type": "boolean", "default": True},
    },
    ["component_names"],
)
def set_component_suppression(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    suppressed = bool(args.get("suppressed", True))
    # swComponentSuppressionState_e: 0 suppressed, 2 fully resolved
    state = 0 if suppressed else 2
    names = [str(n) for n in args["component_names"]]
    components = []
    for name in names:
        try:
            components.append((name, require_component(doc, name)))
        except RuntimeError as exc:
            return result(False, str(exc))
    for _, component in components:
        flag_methods(component, "SetSuppression2").SetSuppression2(state)
    rebuild(doc)
    readback = {}
    for name, component in components:
        readback[name] = bool(safe(component, "IsSuppressed", False))
    ok = all(v == suppressed for v in readback.values())
    return result(
        ok,
        f"{'Suppressed' if suppressed else 'Resolved'} {len(names)} components."
        + ("" if ok else " Readback disagrees."),
        components=names,
        suppressed_state=readback,
    )


@tool(
    "replace_component",
    "Replace a component with another part/assembly file, optionally keeping its mates "
    "(they re-attach where the new file has matching references). Replaces all instances if requested.",
    {
        "component": {"type": "string", "description": "Component to replace, from list_components."},
        "new_path": {"type": "string", "description": "Full path to the replacement .sldprt/.sldasm."},
        "configuration": {"type": "string", "description": "Configuration of the new file. Default: active."},
        "keep_mates": {"type": "boolean", "default": True},
        "all_instances": {"type": "boolean", "default": False},
    },
    ["component", "new_path"],
)
def replace_component(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = require_assembly()
    name = str(args["component"])
    path = Path(str(args["new_path"])).expanduser().resolve()
    if not path.is_file():
        return result(False, f"No such file: {path}")
    doc_type = {".sldprt": 1, ".sldasm": 2}.get(path.suffix.lower())
    if doc_type is None:
        return result(False, "Only .sldprt and .sldasm files can replace a component.")
    try:
        require_component(doc, name)
    except RuntimeError as exc:
        return result(False, str(exc))
    configuration = str(args.get("configuration", "") or "")
    mates_before = len(mate_features(doc))
    _open_silently(app, doc, path, doc_type, configuration)
    try:
        require_selection(doc, {"components": [name]})
    except RuntimeError as exc:
        clear_selection(doc)
        return result(False, str(exc))
    # UseConfigForPartReplacement 0 = match by name (unverified live); mates re-attach per keep_mates.
    flag_methods(doc, "ReplaceComponents2")
    replaced = bool(doc.ReplaceComponents2(
        str(path), configuration, bool(args.get("all_instances", False)), 0, bool(args.get("keep_mates", True)),
    ))
    clear_selection(doc)
    rebuild(doc)
    paths = sorted({str(safe(c, "GetPathName", "")) for c in iter_components(doc, False)})
    return result(
        replaced,
        f"Replaced '{name}' with {path.name}." if replaced else "SOLIDWORKS did not replace the component.",
        component=name,
        new_path=str(path),
        mates_before=mates_before,
        mates_after=len(mate_features(doc)),
        component_paths=paths,
    )


@tool(
    "open_component",
    "Open the part or sub-assembly behind a component in its own window and make it the active "
    "document. The assembly stays open; use list_open_documents / activate to go back to it.",
    {"component": {"type": "string"}},
    ["component"],
)
def open_component(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = require_assembly()
    name = str(args["component"])
    try:
        component = require_component(doc, name)
    except RuntimeError as exc:
        return result(False, str(exc))
    path = str(safe(component, "GetPathName", "") or "")
    if not path:
        return result(False, f"Component '{name}' is virtual (no file on disk); it cannot be opened separately.")
    doc_type = {".sldprt": 1, ".sldasm": 2}.get(Path(path).suffix.lower())
    if doc_type is None:
        return result(False, f"Unsupported component file type: {path}")
    configuration = str(safe(component, "ReferencedConfiguration", "") or "")
    errors, warnings = byref_long(0), byref_long(0)
    opened = app.OpenDoc6(path, doc_type, 0, configuration, errors, warnings)
    if opened is None:
        return result(False, f"SOLIDWORKS could not open {path}.", errors=int(errors.value))
    title = str(safe(opened, "GetTitle", ""))
    try:
        flag_methods(app, "ActivateDoc3").ActivateDoc3(title, True, 0, byref_long(0))
    except Exception:
        logger.info("Could not activate %s after opening it.", title)
    return result(
        True,
        f"Opened {title}.",
        component=name,
        path=path,
        title=title,
        configuration=configuration,
        document_type="part" if doc_type == 1 else "assembly",
    )


@tool(
    "interference_detection",
    "Read-only check of the whole active assembly for interferences. Returns each interfering pair "
    "(component names) with its volume in mm^3. Does not modify the model.",
    {
        "treat_coincidence_as_interference": {"type": "boolean", "default": False},
        "treat_subassemblies_as_components": {"type": "boolean", "default": False},
        "include_multibody_part_interferences": {"type": "boolean", "default": True},
        "ignore_hidden_bodies": {"type": "boolean", "default": False},
    },
)
def interference_detection(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    manager = value(doc, "InterferenceDetectionManager")
    if manager is None:
        return result(False, "SOLIDWORKS did not return an interference detection manager.")
    pairs: list[dict[str, Any]] = []
    try:
        manager.TreatCoincidenceAsInterference = bool(args.get("treat_coincidence_as_interference", False))
        manager.TreatSubAssembliesAsComponents = bool(args.get("treat_subassemblies_as_components", False))
        manager.IncludeMultibodyPartInterferences = bool(args.get("include_multibody_part_interferences", True))
        manager.IgnoreHiddenBodies = bool(args.get("ignore_hidden_bodies", False))
        for interference in as_list(value(manager, "GetInterferences")):
            names = [str(safe(c, "Name2", "")) for c in as_list(safe(interference, "Components"))]
            volume = safe(interference, "Volume")
            pairs.append({
                "components": names,
                "volume_mm3": round(float(volume) * 1e9, 6) if volume is not None else None,
                "possible": bool(safe(interference, "IsPossibleInterference", False)),
            })
    finally:
        # Done() releases the interference session; skipping it leaves SOLIDWORKS in the checker.
        try:
            value(manager, "Done")
        except Exception:
            logger.info("Could not close the interference detection session.")
    total = sum(p["volume_mm3"] or 0.0 for p in pairs)
    return result(
        True,
        f"Found {len(pairs)} interferences." if pairs else "No interferences found.",
        interferences=pairs,
        count=len(pairs),
        total_volume_mm3=round(total, 6),
    )
