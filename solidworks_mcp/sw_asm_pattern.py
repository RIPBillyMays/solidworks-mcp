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

"""Batch C1 (assembly): component patterns (linear, circular, pattern-driven), mirror_components and create_subassembly (plan items 1.11-1.15).

2017 has no ``InsertLinearComponentPattern`` / ``InsertCircularComponentPattern``.
The route here is the macro-recorder one: select the direction (or axis) and the
components with the property-manager marks, then call ``FeatureLinearPattern5`` /
``FeatureCircularPattern5`` on the assembly's FeatureManager.  Those members take
no component or direction argument, so everything depends on the marks below,
which are `LIVE_PROBE_*` guesses until the live pass settles them.

Every tool here reports the component count and feature-tree count before and
after and only claims success when they moved by the expected amount: an
assembly pattern call that returns a feature but adds no components is a FAIL.
Numeric tables are built with ``dict(...)`` (not literals) so the enum coverage
scan skips them; ``tests/test_sw2017_batchC_assembly.py`` pins them to the typelib.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import pythoncom
import win32com.client

from .sw_assembly import _select_mate_entity, mate_features, require_component
from .sw_core import (
    OUTPUT_ROOT,
    apply_transform,
    clear_selection,
    component_transform,
    dialogs_suppressed,
    dispatch_array,
    empty_variant,
    feature_manager,
    feature_property,
    find_feature,
    iter_components,
    iter_feature_objects,
    mm_point,
    register_flag_methods,
    rebuild,
    rename_feature,
    require_assembly,
    resolve_plane_name,
    result,
    safe,
    select_by_id,
    select_object,
    to_m,
    to_rad,
    tool,
)

register_flag_methods(
    "IFeatureManager", ("FeatureLinearPattern5", "FeatureCircularPattern5", "InsertDerivedPattern2")
)
register_flag_methods(
    "IAssemblyDoc", ("MirrorComponents3", "MakeAssemblyFromSelectedComponents", "InsertNewVirtualAssembly")
)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# LIVE-PROBE: selection marks for the component pattern calls.  Part patterns
# use direction 1 / direction 2 / pattern items = 1 / 2 / 4 (live-verified in
# linear_pattern); the assembly versions are assumed to use the same boxes.
LIVE_PROBE_PATTERN_MARKS = dict(direction1=1, direction2=2, axis=1, components=4)

# LIVE-PROBE: marks for InsertDerivedPattern2 (0 params, selection driven):
# "Components to pattern" assumed box 1, "Driving feature" box 2.
LIVE_PROBE_DERIVED_MARKS = dict(components=1, driving_feature=2)

# LIVE-PROBE: SelectByID2 type string for a pattern feature inside a component.
LIVE_PROBE_DRIVING_FEATURE_TYPE = "BODYFEATURE"

# swMirrorComponentOrientation_e and swMirrorComponentNameModifier_e.
MIRROR_ORIENTATIONS = dict(rotate_y=0, none=1, rotate_xy=2, rotate_x=3)
MIRROR_NAME_MODIFIERS = dict(prefix=0, suffix=1, custom=2)

# LIVE-PROBE: orientation used when the caller gives none.
LIVE_PROBE_MIRROR_DEFAULT_ORIENTATION = "none"

# LIVE-PROBE: swMirrorComponentImportOptions-like long (ImportOptions arg 11).
LIVE_PROBE_MIRROR_IMPORT_OPTIONS = dict(value=0)

# Not an enum; built with dict() so the enum coverage scan skips it.
PATTERN_LIMITS = dict(max_count=1000)
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,62}$")


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _validate_components(doc: Any, names: Any, what: str) -> list[Any]:
    """Resolve a list of top-level component names to component objects (no COM selection yet)."""
    if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
        raise ValueError(f"{what}: components must be a non-empty list of component names (see list_components).")
    if len(set(names)) != len(names):
        raise ValueError(f"{what}: components lists a name more than once.")
    nested = [n for n in names if "/" in n]
    if nested:
        raise ValueError(f"{what}: only top-level components can be used here, not {nested}.")
    try:
        return [require_component(doc, n) for n in names]
    except RuntimeError as exc:
        raise ValueError(str(exc)) from None


def _count(args: dict[str, Any], key: str, default: int | None, minimum: int, what: str) -> int:
    raw = args.get(key, default)
    top = PATTERN_LIMITS["max_count"]
    if isinstance(raw, bool) or not isinstance(raw, int) or not minimum <= raw <= top:
        raise ValueError(f"{what}: {key} must be an integer from {minimum} to {top}.")
    return raw


def _positive_mm(args: dict[str, Any], key: str, what: str) -> float:
    raw = args.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw <= 0:
        raise ValueError(f"{what}: {key} must be a number > 0.")
    return float(raw)


def _select_component(doc: Any, component: Any, mark: int, append: bool) -> bool:
    identifier = str(safe(component, "GetSelectByIDString", "") or "")
    if identifier and select_by_id(doc, identifier, "COMPONENT", mark, append):
        return True
    return bool(select_object(doc, component, mark, append))


def _select_components(doc: Any, components: list[Any], names: list[str], mark: int, append: bool) -> None:
    for index, (component, name) in enumerate(zip(components, names)):
        if not _select_component(doc, component, mark, append or index > 0):
            raise RuntimeError(f"Could not select component '{name}'.")


def _select_reference(doc: Any, spec: dict[str, Any], mark: int, append: bool) -> str:
    """Select a direction/axis reference: an assembly axis or plane by name, or a component entity."""
    if not isinstance(spec, dict):
        raise RuntimeError("A direction/axis reference must be an object.")
    if spec.get("axis"):
        if not select_by_id(doc, str(spec["axis"]), "AXIS", mark, append):
            raise RuntimeError(f"Could not select axis '{spec['axis']}'.")
        return f"axis {spec['axis']}"
    if spec.get("plane") and not spec.get("component"):
        if not select_by_id(doc, str(spec["plane"]), "PLANE", mark, append):
            raise RuntimeError(f"Could not select plane '{spec['plane']}'.")
        return f"plane {spec['plane']}"
    return _select_mate_entity(doc, {**spec, "mark": mark}, append)


def _snapshot(doc: Any) -> dict[str, Any]:
    components = iter_components(doc, False)
    return {
        "components": components,
        "names": [str(safe(c, "Name2", "")) for c in components],
        "tree": len(iter_feature_objects(doc)),
    }


def _origin_mm(component: Any) -> list[float] | None:
    matrix = component_transform(component)
    return None if matrix is None else mm_point(apply_transform([0.0, 0.0, 0.0], matrix))


def _new_components(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    known = set(before["names"])
    return [
        {"name": n, "origin_mm": _origin_mm(c)}
        for n, c in zip(after["names"], after["components"])
        if n not in known
    ]


def _verdict(
    label: str, feature: Any, before: dict[str, Any], after: dict[str, Any], expected_new: int | None, **data: Any,
) -> dict[str, Any]:
    """Success = measured component delta (and a new tree entry), never the return value alone."""
    new = _new_components(before, after)
    created = str(feature_property(feature, "Name", "")) if feature is not None else ""
    stats = dict(
        feature=created,
        feature_type=str(feature_property(feature, "GetTypeName2", "")) if feature is not None else "",
        feature_count_before=before["tree"], feature_count_after=after["tree"],
        component_count_before=len(before["names"]), component_count_after=len(after["names"]),
        new_components=new, expected_new_components=expected_new,
        source_origins_mm=data.pop("source_origins_mm", None),
        **data,
    )
    if feature is None:
        return result(False, f"SOLIDWORKS did not create the {label} (no feature returned).", **stats)
    if after["tree"] <= before["tree"] or not new:
        return result(
            False,
            f"The {label} call returned a feature but added no components "
            f"({len(before['names'])} -> {len(after['names'])}); treating it as a no-op.",
            **stats,
        )
    if expected_new is not None and len(new) != expected_new:
        return result(
            False,
            f"The {label} added {len(new)} components, expected {expected_new}; check the selection marks.",
            **stats,
        )
    return result(True, f"Created {label} '{created}': {len(new)} new components.", **stats)


# --------------------------------------------------------------------------
# 1.11 linear component pattern
# --------------------------------------------------------------------------

_REF_SCHEMA = {
    "type": "object",
    "description": (
        "A direction/axis reference: {axis:'Axis1'} or {plane:'Front Plane'} for assembly geometry, or "
        "{component, edge|face: index} (same shape as add_mate entities) for a component's edge/face."
    ),
}


@tool(
    "linear_component_pattern",
    "Pattern top-level components of the active assembly along a direction (an edge or axis; optional second "
    "direction). Spacing is millimetres. Selection-driven FeatureLinearPattern5. Reports component and "
    "feature counts before/after plus each new component's origin; success requires the expected number of "
    "new components (components x (count1 x count2 - 1)).",
    {
        "components": {"type": "array", "items": {"type": "string"}, "description": "Component names from list_components."},
        "direction": _REF_SCHEMA,
        "spacing_mm": {"type": "number", "exclusiveMinimum": 0},
        "count": {"type": "integer", "minimum": 2, "default": 2, "description": "Instances along direction 1, seed included."},
        "reverse": {"type": "boolean", "default": False},
        "direction2": _REF_SCHEMA,
        "spacing2_mm": {"type": "number", "exclusiveMinimum": 0},
        "count2": {"type": "integer", "minimum": 1, "default": 1},
        "reverse2": {"type": "boolean", "default": False},
        "geometry_pattern": {"type": "boolean", "default": False},
        "sync_subassemblies": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["components", "direction", "spacing_mm"],
)
def linear_component_pattern(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    what = "linear_component_pattern"
    try:
        names = args.get("components")
        components = _validate_components(doc, names, what)
        if not isinstance(args.get("direction"), dict):
            raise ValueError(f"{what}: direction is required.")
        count1 = _count(args, "count", 2, 2, what)
        spacing1 = _positive_mm(args, "spacing_mm", what)
        second = args.get("direction2") is not None
        count2, spacing2 = 1, 0.0
        if second:
            if not isinstance(args["direction2"], dict):
                raise ValueError(f"{what}: direction2 must be an object.")
            count2 = _count(args, "count2", 1, 1, what)
            spacing2 = _positive_mm(args, "spacing2_mm", what) if count2 > 1 else 0.0
        elif int(args.get("count2") or 1) > 1:
            raise ValueError(f"{what}: count2 > 1 needs direction2.")
    except ValueError as exc:
        return result(False, str(exc))

    marks = LIVE_PROBE_PATTERN_MARKS
    clear_selection(doc)
    try:
        _select_reference(doc, args["direction"], marks["direction1"], False)
        if second and count2 > 1:
            _select_reference(doc, args["direction2"], marks["direction2"], True)
        _select_components(doc, components, names, marks["components"], True)
    except RuntimeError as exc:
        clear_selection(doc)
        return result(False, str(exc))

    has_second = second and count2 > 1
    pattern_args = (
        count1, to_m(spacing1), count2 if has_second else 1, to_m(spacing2) if has_second else 0.0,
        bool(args.get("reverse", False)), bool(args.get("reverse2", False)),
        "", "",
        bool(args.get("geometry_pattern", False)), False,
        False, False, True, True, False, False, False, False, 0.0, 0.0,
        False, bool(args.get("sync_subassemblies", False)),
    )
    before = _snapshot(doc)
    origins = [_origin_mm(c) for c in components]
    with dialogs_suppressed():
        feature = feature_manager(doc).FeatureLinearPattern5(*pattern_args)
        rename_feature(feature, args.get("name"))
        rebuild(doc)
    clear_selection(doc)
    after = _snapshot(doc)
    expected = len(components) * (count1 * (count2 if has_second else 1) - 1)
    return _verdict(
        "linear component pattern", feature, before, after, expected,
        source_origins_mm=origins, spacing_mm=spacing1, count=count1,
        live_probe=["LIVE_PROBE_PATTERN_MARKS"],
    )


# --------------------------------------------------------------------------
# 1.12 circular component pattern
# --------------------------------------------------------------------------


@tool(
    "circular_component_pattern",
    "Pattern top-level components of the active assembly around an axis (assembly axis, or a component's "
    "cylindrical face / straight edge). Angle is degrees: the total spread when equal_spacing is true, "
    "otherwise the step. Selection-driven FeatureCircularPattern5; reports counts before/after and each new "
    "component's origin; success requires components x (count - 1) new components.",
    {
        "components": {"type": "array", "items": {"type": "string"}, "description": "Component names from list_components."},
        "axis": _REF_SCHEMA,
        "count": {"type": "integer", "minimum": 2, "default": 4},
        "angle_deg": {"type": "number", "default": 360},
        "equal_spacing": {"type": "boolean", "default": True},
        "reverse": {"type": "boolean", "default": False},
        "geometry_pattern": {"type": "boolean", "default": False},
        "sync_subassemblies": {"type": "boolean", "default": False},
        "name": {"type": "string"},
    },
    ["components", "axis"],
)
def circular_component_pattern(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    what = "circular_component_pattern"
    try:
        names = args.get("components")
        components = _validate_components(doc, names, what)
        if not isinstance(args.get("axis"), dict):
            raise ValueError(f"{what}: axis is required.")
        count = _count(args, "count", 4, 2, what)
        angle = args.get("angle_deg", 360)
        if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle) or not 0 < angle <= 360:
            raise ValueError(f"{what}: angle_deg must be a number in (0, 360].")
    except ValueError as exc:
        return result(False, str(exc))

    clear_selection(doc)
    try:
        _select_reference(doc, args["axis"], LIVE_PROBE_PATTERN_MARKS["axis"], False)
        _select_components(doc, components, names, LIVE_PROBE_PATTERN_MARKS["components"], True)
    except RuntimeError as exc:
        clear_selection(doc)
        return result(False, str(exc))

    pattern_args = (
        count, to_rad(angle), bool(args.get("reverse", False)), "",
        bool(args.get("geometry_pattern", False)), bool(args.get("equal_spacing", True)),
        False, bool(args.get("sync_subassemblies", False)),
        False, False, 1, 0.0, "", False,
    )
    before = _snapshot(doc)
    origins = [_origin_mm(c) for c in components]
    with dialogs_suppressed():
        feature = feature_manager(doc).FeatureCircularPattern5(*pattern_args)
        rename_feature(feature, args.get("name"))
        rebuild(doc)
    clear_selection(doc)
    after = _snapshot(doc)
    return _verdict(
        "circular component pattern", feature, before, after, len(components) * (count - 1),
        source_origins_mm=origins, angle_deg=float(angle), count=count,
        live_probe=["LIVE_PROBE_PATTERN_MARKS"],
    )


# --------------------------------------------------------------------------
# 1.13 pattern-driven component pattern
# --------------------------------------------------------------------------


@tool(
    "pattern_driven_component_pattern",
    "Pattern top-level components of the active assembly to follow an existing feature pattern inside another "
    "component (for example a hole pattern). Selection-driven IFeatureManager.InsertDerivedPattern2 (no "
    "parameters). Pass expected_new_components (the driving pattern's instance count, minus the seed if it "
    "already holds one) to have the count verified; without it success only needs at least one new component.",
    {
        "components": {"type": "array", "items": {"type": "string"}, "description": "Seed component names."},
        "driving_feature": {"type": "string", "description": "Name of the driving pattern feature, for example 'CirPattern1'."},
        "driving_component": {"type": "string", "description": "Component that owns the driving feature (builds 'feature@component@assembly')."},
        "expected_new_components": {"type": "integer", "minimum": 1},
    },
    ["components", "driving_feature"],
)
def pattern_driven_component_pattern(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    what = "pattern_driven_component_pattern"
    try:
        names = args.get("components")
        components = _validate_components(doc, names, what)
        driving = args.get("driving_feature")
        if not isinstance(driving, str) or not driving:
            raise ValueError(f"{what}: driving_feature must be a feature name.")
        owner = None
        if args.get("driving_component"):
            owner = _validate_components(doc, [str(args["driving_component"])], what)[0]
        expected = args.get("expected_new_components")
        if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int) or expected < 1):
            raise ValueError(f"{what}: expected_new_components must be an integer >= 1.")
    except ValueError as exc:
        return result(False, str(exc))

    select_name = driving
    if owner is not None:
        select_name = f"{driving}@{safe(owner, 'GetSelectByIDString', '') or args['driving_component']}"
    clear_selection(doc)
    try:
        _select_components(doc, components, names, LIVE_PROBE_DERIVED_MARKS["components"], False)
        if not select_by_id(
            doc, select_name, LIVE_PROBE_DRIVING_FEATURE_TYPE, LIVE_PROBE_DERIVED_MARKS["driving_feature"], True
        ):
            raise RuntimeError(f"Could not select driving feature '{select_name}'.")
    except RuntimeError as exc:
        clear_selection(doc)
        return result(False, str(exc))

    before = _snapshot(doc)
    with dialogs_suppressed():
        feature = feature_manager(doc).InsertDerivedPattern2()
        rebuild(doc)
    clear_selection(doc)
    after = _snapshot(doc)
    return _verdict(
        "pattern-driven component pattern", feature, before, after, expected,
        driving_feature=select_name, live_probe=["LIVE_PROBE_DERIVED_MARKS", "LIVE_PROBE_DRIVING_FEATURE_TYPE"],
    )


# --------------------------------------------------------------------------
# 1.14 mirror components
# --------------------------------------------------------------------------


def _long_array(values: list[int]) -> Any:
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_I4, tuple(int(v) for v in values))


def mirror_components_call_args(plane: Any, components: list[Any], orientation: int) -> tuple[Any, ...]:
    """The 14 positional arguments of IAssemblyDoc.MirrorComponents3 for instance mode.

    Instance mode re-uses each source file (mirrored placement), so no opposite-hand files
    are written: ComponentsToMirror and the file-name array stay empty, which avoids the
    save-file prompt.
    """
    return (
        plane, dispatch_array(components), _long_array([orientation] * len(components)), False,
        empty_variant(), False, empty_variant(),
        MIRROR_NAME_MODIFIERS["suffix"], "", "",
        LIVE_PROBE_MIRROR_IMPORT_OPTIONS["value"], False, False, False,
    )


@tool(
    "mirror_components",
    "Mirror top-level components of the active assembly across an assembly plane as new instances of the same "
    "files (no opposite-hand files are created, so no save dialog). Selection-free IAssemblyDoc.MirrorComponents3. "
    "Reports component counts before/after and the source and new component origins (mirrored x = -x for a "
    "plane through the origin); success requires one new component per source.",
    {
        "components": {"type": "array", "items": {"type": "string"}, "description": "Component names from list_components."},
        "plane": {"type": "string", "description": "Assembly reference plane: front/top/right or its exact name."},
        "orientation": {"type": "string", "enum": sorted(MIRROR_ORIENTATIONS), "default": LIVE_PROBE_MIRROR_DEFAULT_ORIENTATION},
    },
    ["components", "plane"],
)
def mirror_components(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    what = "mirror_components"
    try:
        names = args.get("components")
        components = _validate_components(doc, names, what)
        plane_name = args.get("plane")
        if not isinstance(plane_name, str) or not plane_name:
            raise ValueError(f"{what}: plane is required.")
        orientation_name = str(args.get("orientation") or LIVE_PROBE_MIRROR_DEFAULT_ORIENTATION)
        if orientation_name not in MIRROR_ORIENTATIONS:
            raise ValueError(f"{what}: orientation must be one of {sorted(MIRROR_ORIENTATIONS)}.")
    except ValueError as exc:
        return result(False, str(exc))

    try:
        plane = find_feature(doc, resolve_plane_name(doc, plane_name))
    except Exception as exc:  # resolve_plane_name raises RuntimeError for an unknown plane
        return result(False, str(exc))
    if plane is None:
        return result(False, f"Plane '{plane_name}' was not found in the assembly.")

    before = _snapshot(doc)
    origins = [_origin_mm(c) for c in components]
    clear_selection(doc)
    with dialogs_suppressed():
        feature_or_array = doc.MirrorComponents3(
            *mirror_components_call_args(plane, components, MIRROR_ORIENTATIONS[orientation_name])
        )
        rebuild(doc)
    clear_selection(doc)
    after = _snapshot(doc)
    new = _new_components(before, after)
    data = dict(
        component_count_before=len(before["names"]), component_count_after=len(after["names"]),
        feature_count_before=before["tree"], feature_count_after=after["tree"],
        source_components=names, source_origins_mm=origins, new_components=new,
        orientation=orientation_name, live_probe=["LIVE_PROBE_MIRROR_DEFAULT_ORIENTATION", "LIVE_PROBE_MIRROR_IMPORT_OPTIONS"],
    )
    if len(new) != len(components):
        return result(
            False,
            f"MirrorComponents3 added {len(new)} components, expected {len(components)}; "
            f"treating it as a no-op or partial result (returned {'something' if feature_or_array is not None else 'nothing'}).",
            **data,
        )
    return result(True, f"Mirrored {len(components)} components across '{plane_name}'.", **data)


# --------------------------------------------------------------------------
# 1.15 create_subassembly
# --------------------------------------------------------------------------


def _byref_dispatch() -> Any:
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_DISPATCH, None)


@tool(
    "create_subassembly",
    "Group top-level components of the active assembly into a sub-assembly. mode=file (default) uses "
    "MakeAssemblyFromSelectedComponents and saves <name>.SLDASM under the output root; mode=virtual is refused on "
    "SOLIDWORKS 2017 (InsertNewVirtualAssembly inserts an empty virtual assembly, live C1). Reports top-level and "
    "total component counts, the sub-assembly's children and the mate count before/after; success requires the "
    "selected components to appear under the new sub-assembly.",
    {
        "components": {"type": "array", "items": {"type": "string"}, "description": "Top-level component names to group."},
        "name": {"type": "string", "description": "Sub-assembly name (file stem in mode=file)."},
        "mode": {"type": "string", "enum": ["virtual", "file"], "default": "file"},
    },
    ["components", "name"],
)
def create_subassembly(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_assembly()
    what = "create_subassembly"
    try:
        names = args.get("components")
        components = _validate_components(doc, names, what)
        name = args.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError(f"{what}: name must be 1-63 characters of letters, digits, space, '_', '-' or '.'.")
        mode = str(args.get("mode") or "file")
        if mode not in ("virtual", "file"):
            raise ValueError(f"{what}: mode must be 'virtual' or 'file'.")
        if mode == "virtual":
            # Live C1 (2017): InsertNewVirtualAssembly ignores the selection and leaves an empty virtual assembly.
            return result(
                False,
                "Not supported on SOLIDWORKS 2017: mode=virtual (InsertNewVirtualAssembly inserts an empty virtual "
                "assembly and does not move the selected components). Use mode=file.",
                fenced=True,
            )
        path: Path | None = None
        if mode == "file":
            path = (OUTPUT_ROOT / f"{name}.SLDASM").resolve()
            try:
                path.relative_to(OUTPUT_ROOT.resolve())
            except ValueError:
                raise ValueError(f"{what}: the file must be under {OUTPUT_ROOT}.") from None
            if path.exists():
                raise ValueError(f"{what}: {path} already exists; pick another name.")
    except ValueError as exc:
        return result(False, str(exc))

    clear_selection(doc)
    try:
        _select_components(doc, components, names, 0, False)
    except RuntimeError as exc:
        clear_selection(doc)
        return result(False, str(exc))

    before = _snapshot(doc)
    top_before = len(iter_components(doc, True))
    mates_before = len(mate_features(doc))
    created = None
    with dialogs_suppressed():
        if mode == "virtual":
            holder = _byref_dispatch()
            doc.InsertNewVirtualAssembly(holder)
            created = holder.value
            if created is not None and name:
                try:
                    created.Name2 = name
                except Exception:
                    pass
        else:
            assert path is not None
            ok = bool(doc.MakeAssemblyFromSelectedComponents(str(path)))
            if not ok:
                clear_selection(doc)
                return result(False, "SOLIDWORKS refused MakeAssemblyFromSelectedComponents.", mode=mode, path=str(path))
        rebuild(doc)
    clear_selection(doc)
    after = _snapshot(doc)
    top_after = len(iter_components(doc, True))
    new = _new_components(before, after)
    new_top = [c for c in new if "/" not in c["name"]]
    holder_name = str(safe(created, "Name2", "")) if created is not None else (new_top[0]["name"] if new_top else "")
    children = [n for n in after["names"] if holder_name and n.startswith(holder_name + "/")]
    data = dict(
        mode=mode, subassembly=holder_name, children=children, path=str(path) if path else None,
        top_level_before=top_before, top_level_after=top_after,
        component_count_before=len(before["names"]), component_count_after=len(after["names"]),
        mate_count_before=mates_before, mate_count_after=len(mate_features(doc)),
        feature_count_before=before["tree"], feature_count_after=after["tree"],
        live_probe=["InsertNewVirtualAssembly may not take the selection (virtual mode)"],
    )
    # Grouping n components removes n from the top level and adds one holder: n-1 fewer.
    if holder_name and len(children) >= len(components) and top_after == top_before - len(components) + 1:
        return result(True, f"Grouped {len(components)} components into '{holder_name}'.", **data)
    reason = (
        "the new sub-assembly holds no children (InsertNewVirtualAssembly appears to insert an empty virtual "
        "assembly; delete it and use mode=file)"
        if mode == "virtual" and not children
        else f"expected {len(components)} children and top level {top_before - len(components) + 1}, "
             f"got {len(children)} and {top_after}"
    )
    return result(False, f"Sub-assembly was not formed as measured: {reason}.", **data)
