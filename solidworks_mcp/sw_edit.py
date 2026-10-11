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

"""Batch C3: allow-listed edit_feature built on sw_core.feature_data, plus the split_body retry (plan items 3.9-3.12).

``edit_feature`` edits an existing feature through ``GetDefinition`` /
``ModifyDefinition`` (ADR-0007).  It is deliberately not generic: only the feature
types in ``EDIT_TYPES`` are accepted, keyed by ``IFeature.GetTypeName2``, because
every data interface has its own setters and ``ModifyDefinition`` can return True
and change nothing.  Success is the value read back from a fresh definition after
a rebuild, never the return value.

3.10 (combine_bodies) stays fenced: 2017 has no Combine entry in
``swFeatureNameID_e``, so there is no route to retry.  3.12 (set_mass_override)
stays fenced by decision D4.  3.11 is ``split_via_cut`` below, reached from
split_body(method="cut") and live-tested with SW_MCP_DISABLE_FENCES=1.

Constants marked LIVE-PROBE are unverified on 2017.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Final

from .sw_core import (
    call_versioned,
    com_error,
    dialogs_suppressed,
    exit_active_sketch,
    feature_data,
    feature_manager,
    feature_property,
    find_feature,
    flag_methods,
    rebuild,
    rename_feature,
    require_part,
    result,
    select_sketch_for_feature,
    to_deg,
    to_m,
    to_rad,
    tool,
    value,
    whats_wrong,
)
from .sw_feature import _ExtrudePlan, _NO_START_OFFSET, _feature_names
from .sw_surface import _resolve, _snapshot

# --------------------------------------------------------------------------
# edit_feature allow-list (ADR-0007 decision 5, D5)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EditParam:
    """One editable parameter: how the user states it and how COM reads/writes it."""

    kind: str  # length_mm | angle_deg | count | bool
    read: Callable[[Any], Any]  # raw COM value
    write: Callable[[Any, Any], None]  # (data, raw COM value)
    description: str = ""


def _prop(member: str) -> tuple[Callable[[Any], Any], Callable[[Any, Any], None]]:
    return (lambda data: value(data, member)), (lambda data, raw: setattr(data, member, raw))


def _fn_param(getter: str, setter: str, *lead: Any) -> tuple[Callable[[Any], Any], Callable[[Any, Any], None]]:
    return (
        (lambda data: getattr(data, getter)(*lead)),
        (lambda data, raw: getattr(data, setter)(*lead, raw)),
    )


# Members called with arguments on a definition object; flagged as methods before use.
_DATA_METHODS: Final = ("GetDepth", "SetDepth", "GetEdgeChamferDistance", "SetEdgeChamferDistance")
# GetTypeName2 strings (LIVE-PROBE: confirm each with list_features before the first edit).
TYPE_EXTRUDE: Final = "Extrusion"
TYPE_FILLET: Final = "Fillet"
TYPE_CHAMFER: Final = "Chamfer"
TYPE_LINEAR_PATTERN: Final = "LPattern"
TYPE_CIRCULAR_PATTERN: Final = "CirPattern"
TYPE_SHELL: Final = "Shell"
# GetDepth/SetDepth "Forward" flag: True addresses direction 1.
EXTRUDE_DIRECTION_1: Final = True
# IChamferFeatureData2 Side index for the first (or only) distance.  LIVE-PROBE.
CHAMFER_SIDE_1: Final = 0

_depth_r, _depth_w = _fn_param("GetDepth", "SetDepth", EXTRUDE_DIRECTION_1)
_chamfer_r, _chamfer_w = _fn_param("GetEdgeChamferDistance", "SetEdgeChamferDistance", CHAMFER_SIDE_1)
_rev_r, _rev_w = _prop("ReverseDirection")
# ISimpleFilletFeatureData2.SetRadius needs a fillet-item object; DefaultRadius is the
# constant-radius property.  LIVE-PROBE: confirm it moves a multi-edge constant fillet.
_fillet_r, _fillet_w = _prop("DefaultRadius")
_space_r, _space_w = _prop("D1Spacing")
_lcount_r, _lcount_w = _prop("D1TotalInstances")
_ccount_r, _ccount_w = _prop("TotalInstances")
_cangle_r, _cangle_w = _prop("Spacing")
_shell_r, _shell_w = _prop("Thickness")

EDIT_TYPES: Final[dict[str, dict[str, EditParam]]] = {
    TYPE_EXTRUDE: {
        "depth_mm": EditParam("length_mm", _depth_r, _depth_w, "Direction 1 depth."),
        "reverse": EditParam("bool", _rev_r, _rev_w, "Flip the extrude direction."),
    },
    TYPE_FILLET: {"radius_mm": EditParam("length_mm", _fillet_r, _fillet_w, "Constant fillet radius.")},
    TYPE_CHAMFER: {"distance_mm": EditParam("length_mm", _chamfer_r, _chamfer_w, "First chamfer distance.")},
    TYPE_LINEAR_PATTERN: {
        "spacing_mm": EditParam("length_mm", _space_r, _space_w, "Direction 1 spacing."),
        "count": EditParam("count", _lcount_r, _lcount_w, "Direction 1 total instances (>= 2)."),
    },
    TYPE_CIRCULAR_PATTERN: {
        "count": EditParam("count", _ccount_r, _ccount_w, "Total instances (>= 2)."),
        "angle_deg": EditParam("angle_deg", _cangle_r, _cangle_w, "Spacing angle (total angle if equal spacing)."),
    },
    TYPE_SHELL: {"thickness_mm": EditParam("length_mm", _shell_r, _shell_w, "Wall thickness.")},
}

_TOLERANCE: Final = {"length_mm": 1e-4, "angle_deg": 1e-3, "count": 0.0, "bool": 0.0}


def _check_value(name: str, raw: Any, kind: str) -> Any:
    """Validate one user value (no COM): the user-unit value, ready to compare."""
    if kind == "bool":
        if not isinstance(raw, bool):
            raise ValueError(f"{name} must be true or false.")
        return raw
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{name} must be a number.")
    if kind == "count":
        if int(raw) != raw or raw < 2:
            raise ValueError(f"{name} must be a whole number of at least 2.")
        return int(raw)
    if raw <= 0:
        raise ValueError(f"{name} must be greater than 0.")
    if kind == "angle_deg" and raw > 360:
        raise ValueError(f"{name} must be at most 360 degrees.")
    return float(raw)


def _to_raw(kind: str, user: Any) -> Any:
    return {"length_mm": to_m, "angle_deg": to_rad}.get(kind, lambda v: v)(user)


def _from_raw(kind: str, raw: Any) -> Any:
    if kind == "bool":
        return bool(raw)
    if kind == "count":
        return int(raw)
    return round(float({"length_mm": lambda v: v * 1000.0, "angle_deg": to_deg}[kind](float(raw))), 6)


def _same(kind: str, a: Any, b: Any) -> bool:
    return abs(float(a) - float(b)) <= _TOLERANCE[kind]


class _NothingToChange(Exception):
    """Every requested value already holds; leave feature_data without ModifyDefinition."""


def _read_all(data: Any, params: dict[str, EditParam], names: list[str]) -> dict[str, Any]:
    flag_methods(data, *_DATA_METHODS)
    return {name: _from_raw(params[name].kind, params[name].read(data)) for name in names}


def _edit_schema() -> dict[str, Any]:
    allowed = "; ".join(f"{t}: {', '.join(p)}" for t, p in EDIT_TYPES.items())
    return {
        "feature_name": {"type": "string", "description": "Feature name from list_features."},
        "params": {
            "type": "object",
            "description": f"Values to change, by GetTypeName2 type -> allowed keys: {allowed}.",
            "properties": {
                "depth_mm": {"type": "number", "exclusiveMinimum": 0},
                "reverse": {"type": "boolean"},
                "radius_mm": {"type": "number", "exclusiveMinimum": 0},
                "distance_mm": {"type": "number", "exclusiveMinimum": 0},
                "spacing_mm": {"type": "number", "exclusiveMinimum": 0},
                "count": {"type": "integer", "minimum": 2},
                "angle_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 360},
                "thickness_mm": {"type": "number", "exclusiveMinimum": 0},
            },
            "additionalProperties": False,
        },
    }


_ALL_KINDS: Final = {name: p.kind for params in EDIT_TYPES.values() for name, p in params.items()}


@tool(
    "edit_feature",
    "Edit parameters of an existing feature in place. Only these feature types are supported (by "
    "GetTypeName2): Extrusion (depth_mm, reverse), Fillet (radius_mm), Chamfer (distance_mm), "
    "LPattern (spacing_mm, count), CirPattern (count, angle_deg), Shell (thickness_mm); any other "
    "type is refused. Success is judged by reading the value back after a rebuild: `changed` is true "
    "only when the model now holds the new value. Reports feature-tree count, volume and bounding "
    "box before and after.",
    _edit_schema(),
    ["feature_name", "params"],
)
def edit_feature(args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("feature_name")
    params = args.get("params")
    if not isinstance(name, str) or not name.strip():
        return result(False, "feature_name must be a non-empty string.")
    if not isinstance(params, dict) or not params:
        return result(False, "params must be an object with at least one value to change.")
    wanted: dict[str, Any] = {}
    for key, raw in params.items():
        if key not in _ALL_KINDS:
            return result(False, f"Unknown parameter '{key}'. Known parameters: {sorted(_ALL_KINDS)}.")
        try:
            wanted[key] = _check_value(key, raw, _ALL_KINDS[key])
        except ValueError as exc:
            return result(False, str(exc))

    _, doc = require_part()
    exit_active_sketch(doc)
    feature = find_feature(doc, name)
    if feature is None:
        return result(False, f"No feature named '{name}'. Use list_features.")
    type_name = str(feature_property(feature, "GetTypeName2", ""))
    allowed = EDIT_TYPES.get(type_name)
    if allowed is None:
        return result(
            False,
            f"edit_feature does not support feature type '{type_name}' (feature '{name}'). "
            f"Supported types: {sorted(EDIT_TYPES)}.",
            feature=name, feature_type=type_name,
        )
    unsupported = [key for key in wanted if key not in allowed]
    if unsupported:
        return result(
            False,
            f"A {type_name} feature cannot edit {unsupported}; it supports {sorted(allowed)}.",
            feature=name, feature_type=type_name,
        )

    names = list(wanted)
    snapshot_before = _snapshot(doc)
    before: dict[str, Any] = {}
    try:
        with dialogs_suppressed():
            try:
                with feature_data(feature, doc) as data:
                    before = _read_all(data, allowed, names)
                    pending = [k for k in names if not _same(allowed[k].kind, before[k], wanted[k])]
                    if not pending:
                        raise _NothingToChange
                    for key in pending:
                        allowed[key].write(data, _to_raw(allowed[key].kind, wanted[key]))
            except _NothingToChange:
                pass
            rebuilt = rebuild(doc)
    except RuntimeError as exc:  # feature_data has already released selection access
        return result(False, f"edit_feature failed: {exc}", feature=name, feature_type=type_name)
    except Exception as exc:
        return com_error(exc)

    # Read back from a fresh definition: the object edited above is stale after the rebuild.
    fresh = find_feature(doc, name)
    try:
        after = _read_all(value(fresh, "GetDefinition"), allowed, names) if fresh is not None else {}
    except Exception as exc:
        return result(False, f"Edited '{name}' but could not read the definition back: {exc}", feature=name)
    problems = whats_wrong(doc)
    snapshot_after = _snapshot(doc)

    report: dict[str, Any] = {}
    changed_any = failed = False
    for key in names:
        kind = allowed[key].kind
        holds = key in after and _same(kind, after[key], wanted[key])
        moved = key in after and not _same(kind, after[key], before[key])
        status = "unchanged" if _same(kind, before[key], wanted[key]) and holds else ("changed" if holds and moved else "failed")
        changed_any |= status == "changed"
        failed |= status == "failed"
        report[key] = {"requested": wanted[key], "before": before[key], "after": after.get(key), "status": status}

    data_out = dict(
        feature=name, feature_type=type_name, params=report, changed=changed_any, rebuilt=rebuilt,
        features_before=snapshot_before["features"], features_after=snapshot_after["features"],
        volume_before_mm3=snapshot_before["volume_mm3"], volume_after_mm3=snapshot_after["volume_mm3"],
        bbox_before_mm=snapshot_before["bbox_mm"], bbox_after_mm=snapshot_after["bbox_mm"],
    )
    if problems:
        data_out["problems"] = problems
    if failed:
        bad = [k for k, v in report.items() if v["status"] == "failed"]
        return result(
            False,
            f"ModifyDefinition was accepted but the read-back does not show the requested value for {bad}.",
            **data_out,
        )
    if problems:
        return result(False, f"Edited '{name}', but the model now has rebuild errors.", **data_out)
    if not changed_any:
        return result(True, f"'{name}' already holds the requested values; nothing was changed.", **data_out)
    return result(True, f"Edited '{name}' ({type_name}); read-back confirms the new value.", **data_out)


# --------------------------------------------------------------------------
# 3.11 split_body retry: FeatureCut4 through-all kerf
# --------------------------------------------------------------------------


def split_via_cut(args: dict[str, Any]) -> dict[str, Any]:
    """Split a body by cutting a closed sketch profile through all, in both directions.

    Called from ``split_body(method="cut")``.  PostSplitBody builds nothing on 2017,
    so the split is made by an ordinary FeatureCut4 whose profile slices the body in
    two.  Unlike a true split this removes the profile's prism (the kerf), so total
    volume drops by the kerf volume; the result reports it.  Success means the solid
    count rose.  LIVE-PROBE: whether FeatureCut4 keeps every resulting body without
    the multi-body prompt (UseAutoSelect/feature scope) on 2017.
    """
    selection = args.get("tool_selection") or {}
    sketches = list(selection.get("sketches") or [])
    if len(sketches) != 1 or any(key != "sketches" for key in selection):
        return result(False, 'method "cut" needs tool_selection {"sketches": [one closed profile sketch]} and nothing else.')
    _, doc = require_part()
    exit_active_sketch(doc)
    sketch = select_sketch_for_feature(doc, sketches[0])
    plan = _ExtrudePlan({"end_condition": "through_all", "end_condition2": "through_all"})
    cut_args = (
        *plan.head(False, False), False, True, True,
        False, False, False,
        *_NO_START_OFFSET, False,
    )
    before, names = _snapshot(doc), _feature_names(doc)
    with dialogs_suppressed():
        returned = call_versioned(
            feature_manager(doc),
            ("FeatureCut4", cut_args),
            ("FeatureCut3", cut_args[:26]),
        )
    feature = _resolve(doc, returned, names)
    rename_feature(feature, args.get("name"))
    problems = whats_wrong(doc) if feature is not None else []
    after = _snapshot(doc)
    solids_gained = after["solid_bodies"] - before["solid_bodies"]
    data = dict(
        sketch=sketch, method="cut", features_before=before["features"], features_after=after["features"],
        solid_bodies_before=before["solid_bodies"], solid_bodies_after=after["solid_bodies"],
        volume_before_mm3=before["volume_mm3"], volume_after_mm3=after["volume_mm3"],
        kerf_volume_mm3=round(before["volume_mm3"] - after["volume_mm3"], 4),
    )
    if feature is None:
        return result(False, "FeatureCut4 created no feature; the profile must be a closed sketch crossing the body.", **data)
    if problems:
        data["problems"] = problems
        return result(False, "The split cut has rebuild errors.", **data)
    if solids_gained < 1:
        return result(False, "The cut built but the solid-body count did not rise, so the body was not split.", **data)
    return result(True, f"Split by cutting '{sketch}': {before['solid_bodies']} -> {after['solid_bodies']} solid bodies "
                  "(the cut removes the profile's volume).", **data)
