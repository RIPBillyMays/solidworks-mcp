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

"""Batch C1 (assembly): advanced mate types for add_mate dispatch (limit, gear, rack-pinion, screw, cam, hinge, slot, path, symmetric/width edge cases) and add_mate_reference (plan items 1.1-1.10).

``add_mate`` (sw_assembly.py) calls ``plan_advanced_mate`` before it touches COM.
The plan validates every input, maps the user-facing arguments onto the 15
``IAssemblyDoc.AddMate5`` parameters and decides the selection marks.  Plain
mate types without any of the new arguments return no plan, so the Batch A
path is untouched.

Everything that Batch C could not settle offline is isolated in a constant
named ``LIVE_PROBE_*`` below.  The live pass (``tests/live_p5_batchC1.py``)
changes that one constant if the first guess is wrong.

The numeric tables here are built with ``dict(...)`` calls on purpose: the
enum coverage scan in ``test_sw2017_enums.py`` only reads literal tables, and
this module's values are pinned to the 2017 typelib in
``tests/test_sw2017_batchC_assembly.py`` instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .sw_core import (
    clear_selection,
    dialogs_suppressed,
    feature_manager,
    feature_property,
    iter_edge_objects,
    iter_face_objects,
    iter_feature_objects,
    nothing,
    register_flag_methods,
    require_part,
    result,
    to_m,
    to_rad,
    tool,
)

# Late-bound members called with arguments (ADR-0007: per-module registration).
register_flag_methods("IAssemblyDoc", ("AddMate5",))
register_flag_methods("IFeatureManager", ("InsertMateReference2",))

# --------------------------------------------------------------------------
# Constants.  swMateType_e values are pinned in the batchC assembly tests.
# --------------------------------------------------------------------------

# New names accepted by add_mate beyond sw_core.MATE_TYPES.  The two limit
# names are aliases of distance/angle that insist on min and max.
ADV_MATE_TYPES = dict(
    gear=10, rack_pinion=13, screw=17, cam=9, hinge=22, path=15,
    limit_distance=5, limit_angle=6,
)

# Entities a mate needs at minimum (checked against the real selection count).
MIN_ENTITIES = dict(
    gear=2, rack_pinion=2, screw=2, cam=2, hinge=4, path=2,
    limit_distance=2, limit_angle=2, slot=2, symmetric=3, width=4,
)

# LIVE-PROBE: which AddMate5 numeric slot carries the rack-and-pinion
# "distance per revolution" and the screw pitch.  Candidates: "distance"
# (arg 4, all three of 4-6 are set) or "ratio" (arg 7, GearRatioNumerator).
LIVE_PROBE_VALUE_SLOT = dict(rack_pinion="distance", screw="distance")

# LIVE-PROBE: selection marks.  The plan says "cam mark 1, follower mark 8?";
# hinge and path marks are guesses taken from the property-manager box order.
LIVE_PROBE_CAM_MARKS = dict(cam=1, follower=8)
LIVE_PROBE_HINGE_MARKS = dict(concentric=1, coincident=2)
LIVE_PROBE_PATH_MARKS = dict(point=1, path=2)
LIVE_PROBE_SYMMETRIC_MARKS = dict(symmetry_plane=1, entity=0)

# LIVE-PROBE: slot constraint -> WidthMateOption (swMateWidthOptions_e).  The
# slot mate has no parameter of its own in AddMate5, so the width-option slot
# is the most likely carrier.  centered=0, free=1, dimension=2, percent=3.
LIVE_PROBE_SLOT_CONSTRAINT = dict(center=0, free=1, distance=2, percent=3)

# LIVE-PROBE: whether the width/slot percentage goes into the Distance slots as
# a 0..1 fraction (assumed) rather than into the Angle slots.
LIVE_PROBE_PERCENT_AS_FRACTION = dict(enabled=True)

# swMateReferenceType_e / swMateReferenceAlignment_e for InsertMateReference2.
MATE_REFERENCE_TYPES = dict(default=0, tangent=1, coincident=2, concentric=3, parallel=4)
MATE_REFERENCE_ALIGNMENTS = dict(any=0, aligned=1, anti_aligned=2, closest=3)
# Live 2017: a mate reference shows in the tree as a PosGroupFolder (named "<name>-<1>") inside a MateReferenceGroupFolder.
MATE_REFERENCE_FEATURE_TYPES = ("MateReference", "PosGroupFolder")

_VALUE_SLOTS = ("distance", "ratio")
_ROLE_SETS = dict(
    cam=("cam", "follower"),
    hinge=("concentric", "coincident"),
    path=("point", "path"),
    symmetric=("symmetry_plane", "entity"),
)


@dataclass
class MatePlan:
    """Validated AddMate5 parameters plus the marks and bookkeeping for one mate."""

    name: str
    mate_type: int
    flip: bool = False
    distance_m: float = 0.0
    upper_d_m: float = 0.0
    lower_d_m: float = 0.0
    ratio_num: float = 1.0
    ratio_den: float = 1.0
    angle_rad: float = 0.0
    upper_a_rad: float = 0.0
    lower_a_rad: float = 0.0
    width_option: int | None = None
    lock_rotation: bool = False
    min_entities: int = 2
    probes: list[str] = field(default_factory=list)

    def addmate5_args(self, alignment: int, status: Any) -> tuple[Any, ...]:
        """The 15 positional arguments of IAssemblyDoc.AddMate5, in typelib order."""
        return (
            self.mate_type, alignment, self.flip,
            self.distance_m, self.upper_d_m, self.lower_d_m,
            self.ratio_num, self.ratio_den,
            self.angle_rad, self.upper_a_rad, self.lower_a_rad,
            False, self.lock_rotation,
            0 if self.width_option is None else self.width_option,
            status,
        )

    def set_distance(self, metres: float) -> None:
        self.distance_m = self.upper_d_m = self.lower_d_m = metres


def _num(args: dict[str, Any], key: str) -> float | None:
    raw = args.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError(f"{key} must be a number.")
    try:
        number = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number.") from None
    if not math.isfinite(number):
        raise ValueError(f"{key} must be a finite number.")
    return number


def _positive(args: dict[str, Any], key: str, what: str) -> float:
    number = _num(args, key)
    if number is None or number <= 0:
        raise ValueError(f"{what} needs {key} > 0.")
    return number


def _percent(args: dict[str, Any], key: str) -> float:
    pct = _num(args, key)
    if pct is None or not 0.0 <= pct <= 100.0:
        raise ValueError(f"{key} must be between 0 and 100.")
    return pct / 100.0


def _required_limits(args: dict[str, Any], lo_key: str, hi_key: str, val_key: str, unit: str) -> tuple[float, float, float]:
    lo, hi, val = _num(args, lo_key), _num(args, hi_key), _num(args, val_key)
    if lo is None or hi is None:
        raise ValueError(f"A limit mate needs both {lo_key} and {hi_key}.")
    if lo > hi:
        raise ValueError(f"{lo_key} ({lo} {unit}) must not exceed {hi_key} ({hi} {unit}).")
    if val is None:
        val = lo
    if not lo <= val <= hi:
        raise ValueError(f"{val_key} ({val} {unit}) must lie within [{lo}, {hi}] {unit}.")
    return lo, hi, val


# Per-type refusals found by the live pass (docs/reports/phase5-batchC1-live.md): add_mate stays available for every
# other type.  Checked before any selection or COM call.
UNSUPPORTED_MATE_TYPES: dict[str, str] = {
    "cam": "AddMate5 with a cam-follower mate crashes the SOLIDWORKS 2017 process (RPC failure, SW exits); "
           "create cam mates in the SOLIDWORKS UI.",
    "rack_pinion": "AddMate5 rejects rack-and-pinion mates (status 0, 'unknown error') with both the distance and "
                   "ratio value slots; create rack-and-pinion mates in the SOLIDWORKS UI.",
    "hinge": "AddMate5 rejects hinge mates (status 0, 'unknown error') for both mark layouts tried; "
             "add a concentric plus a coincident mate instead, or use the SOLIDWORKS UI.",
    "path": "AddMate5 with a path mate crashes the SOLIDWORKS 2017 process (RPC failure, SW exits); "
            "create path mates in the SOLIDWORKS UI.",
}


def plan_advanced_mate(args: dict[str, Any]) -> MatePlan | None:
    """Validate and map an add_mate request, or return None for a plain Batch A mate.

    Raises ValueError with a user-readable message; nothing here touches COM.
    """
    name = str(args["mate_type"])
    entities = args.get("entities") or []
    flip = bool(args.get("flip", False))
    lock = bool(args.get("lock_rotation", False))

    def base(mate_type: int, **extra: Any) -> MatePlan:
        return MatePlan(name, mate_type, flip=extra.pop("flip", flip), lock_rotation=lock,
                        min_entities=MIN_ENTITIES[name], **extra)

    if name == "limit_distance":
        lo, hi, val = _required_limits(args, "min_distance_mm", "max_distance_mm", "distance_mm", "mm")
        plan = base(ADV_MATE_TYPES[name])
        plan.distance_m, plan.upper_d_m, plan.lower_d_m = to_m(val), to_m(hi), to_m(lo)
        return plan

    if name == "limit_angle":
        lo, hi, val = _required_limits(args, "min_angle_deg", "max_angle_deg", "angle_deg", "deg")
        plan = base(ADV_MATE_TYPES[name])
        plan.angle_rad, plan.upper_a_rad, plan.lower_a_rad = to_rad(val), to_rad(hi), to_rad(lo)
        return plan

    if name == "gear":
        num = _num(args, "ratio_num")
        den = _num(args, "ratio_den")
        num = 1.0 if num is None else num
        den = 1.0 if den is None else den
        if num <= 0 or den <= 0:
            raise ValueError("A gear mate needs ratio_num > 0 and ratio_den > 0 (use reverse=true for opposite rotation).")
        return base(ADV_MATE_TYPES[name], flip=bool(args.get("reverse", flip)), ratio_num=num, ratio_den=den)

    if name in ("rack_pinion", "screw"):
        key = "distance_per_rev_mm" if name == "rack_pinion" else "pitch_mm"
        number = _positive(args, key, f"A {name.replace('_', '-')} mate")
        slot = str(args.get("value_slot") or LIVE_PROBE_VALUE_SLOT[name])
        if slot not in _VALUE_SLOTS:
            raise ValueError(f"value_slot must be one of {list(_VALUE_SLOTS)}.")
        plan = base(ADV_MATE_TYPES[name], flip=bool(args.get("reverse", flip)),
                    probes=[f"LIVE_PROBE_VALUE_SLOT[{name}]={slot}"])
        if slot == "distance":
            plan.set_distance(to_m(number))
        else:
            plan.ratio_num = to_m(number)
        return plan

    if name in ("cam", "path"):
        return base(ADV_MATE_TYPES[name], probes=[f"LIVE_PROBE_{name.upper()}_MARKS"])

    if name == "hinge":
        lo, hi = _num(args, "min_angle_deg"), _num(args, "max_angle_deg")
        plan = base(ADV_MATE_TYPES[name], probes=["LIVE_PROBE_HINGE_MARKS"])
        if (lo is None) != (hi is None):
            raise ValueError("A hinge angle limit needs both min_angle_deg and max_angle_deg.")
        if lo is not None and hi is not None:
            if lo > hi:
                raise ValueError("min_angle_deg must not exceed max_angle_deg.")
            plan.angle_rad, plan.upper_a_rad, plan.lower_a_rad = to_rad(lo), to_rad(hi), to_rad(lo)
        return plan

    if name == "slot" and args.get("slot_constraint") is not None:
        constraint = str(args["slot_constraint"])
        if constraint not in LIVE_PROBE_SLOT_CONSTRAINT:
            raise ValueError(f"slot_constraint must be one of {sorted(LIVE_PROBE_SLOT_CONSTRAINT)}.")
        plan = base(21, width_option=LIVE_PROBE_SLOT_CONSTRAINT[constraint], probes=["LIVE_PROBE_SLOT_CONSTRAINT"])
        if constraint == "distance":
            plan.set_distance(to_m(_positive(args, "distance_mm", "slot_constraint=distance")))
        elif constraint == "percent":
            plan.set_distance(_percent(args, "slot_percent"))
            plan.probes.append("LIVE_PROBE_PERCENT_AS_FRACTION")
        return plan

    if name == "width" and args.get("width_percent") is not None:
        if str(args.get("width_option", "centered")) != "percent":
            raise ValueError("width_percent is only used with width_option=percent.")
        plan = base(11, width_option=3, probes=["LIVE_PROBE_PERCENT_AS_FRACTION"])
        plan.set_distance(_percent(args, "width_percent"))
        return plan

    if name == "symmetric" and any(isinstance(e, dict) and e.get("role") for e in entities):
        return base(8, probes=["LIVE_PROBE_SYMMETRIC_MARKS"])

    return None


def assign_marks(plan: MatePlan, specs: list[dict[str, Any]]) -> list[int]:
    """Selection mark per entity spec.  An explicit non-zero ``mark`` on a spec always wins.

    Roles come from ``spec["role"]`` or, when absent, from the position:
    cam -> all but the last are the cam, the last the follower; hinge -> the
    first two concentric, the rest coincident; path -> the first is the point,
    the rest the path; symmetric -> the first is the symmetry plane.
    Raises ValueError for a role that does not belong to this mate type.
    """
    names = _ROLE_SETS.get(plan.name)
    marks: list[int] = []
    last = len(specs) - 1
    for index, spec in enumerate(specs):
        role = spec.get("role")
        if role is not None and (names is None or str(role) not in names):
            raise ValueError(f"role '{role}' is not valid for a {plan.name} mate; use one of {list(names or ())}.")
        explicit = int(spec.get("mark", 0) or 0)
        if explicit or names is None:
            marks.append(explicit)
        elif plan.name == "cam":
            marks.append(LIVE_PROBE_CAM_MARKS[str(role or ("follower" if index == last else "cam"))])
        elif plan.name == "hinge":
            marks.append(LIVE_PROBE_HINGE_MARKS[str(role or ("concentric" if index < 2 else "coincident"))])
        elif plan.name == "path":
            marks.append(LIVE_PROBE_PATH_MARKS[str(role or ("point" if index == 0 else "path"))])
        else:  # symmetric
            marks.append(LIVE_PROBE_SYMMETRIC_MARKS[str(role or ("symmetry_plane" if index == 0 else "entity"))])
    return marks


# --------------------------------------------------------------------------
# add_mate_reference (plan 1.10)
# --------------------------------------------------------------------------

_REFERENCE_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "maxItems": 3,
    "description": (
        "Up to three references (primary, secondary, tertiary). Each is {face|edge: index from "
        "list_faces/list_edges, type: default|tangent|coincident|concentric|parallel, "
        "alignment: any|aligned|anti_aligned|closest, align_axes?: bool}."
    ),
    "items": {
        "type": "object",
        "properties": {
            "face": {"type": "integer"},
            "edge": {"type": "integer"},
            "type": {"type": "string", "enum": sorted(MATE_REFERENCE_TYPES), "default": "default"},
            "alignment": {"type": "string", "enum": sorted(MATE_REFERENCE_ALIGNMENTS), "default": "any"},
            "align_axes": {"type": "boolean", "default": False},
        },
    },
}


def plan_mate_reference(args: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate add_mate_reference input into [{kind, index, type, alignment, align_axes}]."""
    refs = args.get("references")
    if not isinstance(refs, list) or not 1 <= len(refs) <= 3:
        raise ValueError("references must list one to three entities.")
    planned: list[dict[str, Any]] = []
    for position, ref in enumerate(refs, start=1):
        if not isinstance(ref, dict):
            raise ValueError(f"Reference {position} must be an object.")
        kinds = [k for k in ("face", "edge") if ref.get(k) is not None]
        if len(kinds) != 1:
            raise ValueError(f"Reference {position} needs exactly one of face or edge (an index).")
        index = ref[kinds[0]]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError(f"Reference {position}: {kinds[0]} must be a non-negative integer index.")
        ref_type = str(ref.get("type", "default"))
        alignment = str(ref.get("alignment", "any"))
        if ref_type not in MATE_REFERENCE_TYPES:
            raise ValueError(f"Reference {position}: type must be one of {sorted(MATE_REFERENCE_TYPES)}.")
        if alignment not in MATE_REFERENCE_ALIGNMENTS:
            raise ValueError(f"Reference {position}: alignment must be one of {sorted(MATE_REFERENCE_ALIGNMENTS)}.")
        planned.append({
            "kind": kinds[0], "index": index,
            "type": MATE_REFERENCE_TYPES[ref_type], "alignment": MATE_REFERENCE_ALIGNMENTS[alignment],
            "align_axes": bool(ref.get("align_axes", False)),
        })
    return planned


def _mate_reference_names(doc: Any) -> list[str]:
    return [
        str(feature_property(f, "Name", ""))
        for f in iter_feature_objects(doc)
        if str(feature_property(f, "GetTypeName2", "")) in MATE_REFERENCE_FEATURE_TYPES
    ]


def mate_reference_call_args(name: str, entities: list[Any], planned: list[dict[str, Any]]) -> list[Any]:
    """The 12 positional arguments of IFeatureManager.InsertMateReference2.

    Primary and secondary carry (entity, type, alignment, align_axes); the
    tertiary has no align_axes.  Unused slots get a typed null entity.
    """
    out: list[Any] = [name]
    for slot in range(3):
        if slot < len(planned):
            ref = planned[slot]
            out += [entities[slot], ref["type"], ref["alignment"]]
            if slot < 2:
                out.append(ref["align_axes"])
        else:
            out += [nothing(), 0, 0]
            if slot < 2:
                out.append(False)
    return out


@tool(
    "add_mate_reference",
    "Insert a Mate Reference feature into the active PART from faces/edges (indices from list_faces / "
    "list_edges), so inserting the part into an assembly can auto-mate. Reports the feature tree and "
    "MateReference counts before and after; success means a MateReference feature actually appeared.",
    {
        "name": {"type": "string", "description": "Name for the mate reference feature.", "default": "MateReference"},
        "references": _REFERENCE_SCHEMA,
    },
    ["references"],
)
def add_mate_reference(args: dict[str, Any]) -> dict[str, Any]:
    try:
        planned = plan_mate_reference(args)
    except ValueError as exc:
        return result(False, str(exc))
    _, doc = require_part()
    faces = iter_face_objects(doc)
    edges = iter_edge_objects(doc)
    entities: list[Any] = []
    for position, ref in enumerate(planned, start=1):
        pool = faces if ref["kind"] == "face" else edges
        if ref["index"] >= len(pool):
            return result(
                False,
                f"Reference {position}: {ref['kind']} index {ref['index']} is out of range (0..{len(pool) - 1}).",
            )
        entities.append(pool[ref["index"]][0])

    name = str(args.get("name") or "MateReference")
    tree_before = len(iter_feature_objects(doc))
    refs_before = _mate_reference_names(doc)
    clear_selection(doc)
    with dialogs_suppressed():
        feature = feature_manager(doc).InsertMateReference2(*mate_reference_call_args(name, entities, planned))
    refs_after = _mate_reference_names(doc)
    data = dict(
        feature_count_before=tree_before, feature_count_after=len(iter_feature_objects(doc)),
        mate_references_before=len(refs_before), mate_references_after=len(refs_after),
        reference_count=len(planned),
    )
    if feature is None or len(refs_after) <= len(refs_before):
        return result(
            False,
            "SOLIDWORKS created no MateReference feature (it can silently create an empty reference).",
            **data,
        )
    created = str(feature_property(feature, "Name", name))
    return result(True, f"Inserted mate reference '{created}'.", feature=created, **data)
