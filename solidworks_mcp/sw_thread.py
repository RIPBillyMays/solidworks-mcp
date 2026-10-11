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

"""Batch C2 (part features): swept (modeled) threads (plan item 2.7).

The cosmetic-thread option of hole_wizard (2.8) lives in ``sw_feature`` next to
the tool it extends.

A modeled thread is a helix (``create_helix``) plus a small triangular profile
sketch on a plane that contains the cylinder axis and the helix start point,
swept along the helix with a cut (or a boss).  The profile is an ISO-style
60 degree triangle; its apex sits ``depth`` away from the surface, and its base
overshoots the surface by 10 % of the depth so the cut leaves no sliver.  The
tool returns the measured volume change next to the analytic thread volume.
"""

from __future__ import annotations

import math
from typing import Any, Final

from .sw_body import create_helix
from .sw_core import (
    call_versioned,
    clear_selection,
    dialogs_suppressed,
    exit_active_sketch,
    feature_manager,
    feature_result,
    find_feature,
    get_bodies,
    register_flag_methods,
    rename_feature,
    require_part,
    result,
    select_object,
    tool,
    to_m,
)
from .sw_sheetmetal import part_snapshot
from .sw_sketch import close_sketch, create_sketch, draw_line

register_flag_methods("IFeatureManager", ["InsertProtrusionSwept4", "InsertCutSwept5"])

# ISO metric thread: 60 degree flanks, basic external thread depth 0.6134 * pitch.
THREAD_HALF_ANGLE_DEG: Final = 30.0
ISO_DEPTH_PER_PITCH: Final = 0.6134
OVERSHOOT_FRACTION: Final = 0.1
# Selection marks for the swept features (the same convention the sweep tool uses):
# profile 1, path 4.
SWEEP_MARK_PROFILE: Final = 1
SWEEP_MARK_PATH: Final = 4
# LIVE-PROBE: TwistCtrlOption for a helical path (0 = follow path).
THREAD_TWIST_CONTROL: Final = 0
# Plan tolerance on the measured thread volume.
VOLUME_TOLERANCE: Final = 0.03
AXES: Final = ("u", "v")


def thread_profile(
    start_mm: tuple[float, float], axis: str, depth_mm: float, cut: bool, external: bool
) -> list[tuple[float, float]]:
    """Triangle (u, v) points in sketch millimetres.

    ``start_mm`` is where the helix pierces the profile plane; the cylinder axis
    runs along sketch axis ``axis`` ("u" or "v") through the sketch origin, so
    the radial direction is the other coordinate's sign.  The tool volume lies
    on the material side for a cut and on the open side for a boss.
    """
    u0, v0 = float(start_mm[0]), float(start_mm[1])
    radial = v0 if axis == "u" else u0
    outward = 1.0 if radial > 0 else -1.0
    into_material = -outward if external else outward
    tool_dir = into_material if cut else -into_material
    half = math.tan(math.radians(THREAD_HALF_ANGLE_DEG))
    # LIVE (C2): a cut with overshoot removed ~5 % too much volume on a bolt (external);
    # base exactly on the surface matches Pappus to 0.2 %.  A boss still needs the overlap to fuse.
    overshoot = 0.0 if cut else OVERSHOOT_FRACTION * depth_mm
    base_half = (depth_mm + overshoot) * half

    def point(radial_offset: float, axial_offset: float) -> tuple[float, float]:
        if axis == "v":  # axis along v: radial is u
            return (u0 + radial_offset, v0 + axial_offset)
        return (u0 + axial_offset, v0 + radial_offset)

    base_shift = -tool_dir * overshoot
    return [
        point(tool_dir * depth_mm, 0.0),
        point(base_shift, base_half),
        point(base_shift, -base_half),
    ]


def expected_thread_volume_mm3(
    radius_mm: float, pitch_mm: float, length_mm: float, depth_mm: float, cut: bool, external: bool
) -> float:
    """Pappus estimate: triangle area inside the material x centroid path x turns."""
    half = math.tan(math.radians(THREAD_HALF_ANGLE_DEG))
    area = depth_mm * depth_mm * half  # base 2*depth*half on the surface, apex at depth
    # Material side is inward for an external thread, outward for an internal one.
    toward_material = -1.0 if external else 1.0
    direction = toward_material if cut else -toward_material
    centroid_radius = radius_mm + direction * depth_mm / 3.0
    return area * 2.0 * math.pi * centroid_radius * (length_mm / pitch_mm)


@tool(
    "swept_thread",
    "Model a thread by sweeping a 60 degree triangle along a helix. Needs a closed circle sketch "
    "(circle_sketch, radius = the cylinder surface the thread starts on) and a profile_plane that "
    "contains the cylinder axis and the helix start point; start_mm is that start point in the "
    "plane's sketch coordinates and axis ('u' or 'v') is the sketch axis the cylinder runs along "
    "through the sketch origin. external cuts a bolt thread, otherwise an internal (hole) thread. "
    "mode cut removes material, boss adds a ridge. Returns the measured volume change next to the "
    "analytic thread volume (plan tolerance 3 %).",
    {
        "circle_sketch": {"type": "string", "description": "Circle sketch the helix is built from."},
        "profile_plane": {"type": "string", "description": "Plane name (front/top/right or exact name) for the profile."},
        "start_mm": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
        "axis": {"type": "string", "enum": list(AXES), "default": "v"},
        "pitch_mm": {"type": "number", "exclusiveMinimum": 0},
        "length_mm": {"type": "number", "exclusiveMinimum": 0},
        "depth_mm": {"type": "number", "exclusiveMinimum": 0, "description": "Thread depth; default ISO 0.6134 x pitch."},
        "external": {"type": "boolean", "default": True},
        "mode": {"type": "string", "enum": ["cut", "boss"], "default": "cut"},
        "name": {"type": "string"},
    },
    ["circle_sketch", "profile_plane", "start_mm", "pitch_mm", "length_mm"],
)
def swept_thread(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    pitch = float(args.get("pitch_mm") or 0.0)
    length = float(args.get("length_mm") or 0.0)
    start = args.get("start_mm")
    axis = str(args.get("axis", "v"))
    mode = str(args.get("mode", "cut"))
    external = bool(args.get("external", True))
    if pitch <= 0 or length <= 0:
        return result(False, "pitch_mm and length_mm must be positive.")
    if length < pitch:
        return result(False, "length_mm must be at least one pitch.")
    if axis not in AXES or mode not in ("cut", "boss"):
        return result(False, f"axis must be one of {list(AXES)} and mode cut or boss.")
    if not args.get("circle_sketch") or not args.get("profile_plane"):
        return result(False, "circle_sketch and profile_plane are required.")
    if not start or len(start) != 2:
        return result(False, "start_mm must be [u, v] in sketch millimetres.")
    radial = float(start[1] if axis == "u" else start[0])
    if radial == 0.0:
        return result(False, "start_mm lies on the cylinder axis; its coordinate across the axis must be non-zero.")
    depth = float(args.get("depth_mm") or ISO_DEPTH_PER_PITCH * pitch)
    if depth <= 0 or depth >= abs(radial):
        return result(False, "depth_mm must be positive and smaller than the thread radius.")
    cut = mode == "cut"
    base_name = str(args.get("name") or "Thread")

    exit_active_sketch(doc)
    before = part_snapshot(doc)
    bodies_before = len(get_bodies(doc))

    helix = create_helix({
        "sketch": args["circle_sketch"], "defined_by": "height_pitch", "height_mm": length,
        "pitch_mm": pitch, "name": f"{base_name}_Helix",
    })
    if not helix.get("ok"):
        return result(False, f"Could not build the helix: {helix.get('message')}", helix=helix.get("data"))
    helix_name = (helix.get("data") or {}).get("feature") or f"{base_name}_Helix"

    sketch_name = f"{base_name}_Profile"
    opened = create_sketch({"plane_name": str(args["profile_plane"]), "name": sketch_name})
    if not opened.get("ok"):
        return result(False, f"Could not open the profile sketch: {opened.get('message')}", helix=helix_name)
    points = thread_profile((float(start[0]), float(start[1])), axis, depth, cut, external)
    for first, second in zip(points, points[1:] + points[:1]):
        drawn = draw_line({"x1_mm": first[0], "y1_mm": first[1], "x2_mm": second[0], "y2_mm": second[1]})
        if not drawn.get("ok"):
            close_sketch({})
            return result(False, f"Could not draw the thread profile: {drawn.get('message')}", helix=helix_name)
    close_sketch({})

    profile = find_feature(doc, sketch_name)
    path = find_feature(doc, str(helix_name))
    if profile is None or path is None:
        return result(False, "The profile sketch or helix could not be found after creation.",
                      helix=helix_name, profile=sketch_name)
    clear_selection(doc)
    if not select_object(doc, profile, SWEEP_MARK_PROFILE, False) or not select_object(doc, path, SWEEP_MARK_PATH, True):
        return result(False, "Could not select the profile and helix for the sweep.", helix=helix_name, profile=sketch_name)

    manager = feature_manager(doc)
    with dialogs_suppressed():
        if cut:
            cut_args = (
                False, True, THREAD_TWIST_CONTROL, False, False,
                0, 0, False, 0.0, 0.0, 0, 0,
                True, True, 0.0, False,
                False, False, False,
                False, 0.0, 0,
            )
            feature = call_versioned(manager, ("InsertCutSwept5", cut_args))
        else:
            boss_args = (
                False, True, THREAD_TWIST_CONTROL, False, False,
                0, 0, False, 0.0, 0.0, 0, 0,
                True, True, True,
                0.0, False, False, 0.0, 0,
            )
            feature = call_versioned(manager, ("InsertProtrusionSwept4", boss_args))
    rename_feature(feature, args.get("name"))
    out = feature_result(
        doc, feature, "swept thread", helix=helix_name, profile=sketch_name,
        pitch_mm=pitch, length_mm=length, depth_mm=round(depth, 6), mode=mode, external=external,
    )

    after = part_snapshot(doc)
    delta = after.get("volume_mm3", 0.0) - before.get("volume_mm3", 0.0)
    expected = expected_thread_volume_mm3(abs(radial), pitch, length, depth, cut, external)
    measured_volume = -delta if cut else delta
    deviation = (measured_volume - expected) / expected if expected else None
    bodies_after = len(get_bodies(doc))
    data = out.setdefault("data", {})
    data.update(
        before=before, after=after, volume_removed_or_added_mm3=round(measured_volume, 4),
        expected_volume_mm3=round(expected, 4),
        deviation=None if deviation is None else round(deviation, 4),
        within_tolerance=deviation is not None and abs(deviation) <= VOLUME_TOLERANCE,
        bodies_before=bodies_before, bodies_after=bodies_after,
    )
    if feature is not None and out["ok"]:
        if measured_volume <= 0:
            out["ok"] = False
            out["message"] = "The sweep returned a feature but the volume did not change the right way; treat it as a silent no-op."
        elif bodies_after != bodies_before:
            out["ok"] = False
            out["message"] = f"The thread changed the body count ({bodies_before} -> {bodies_after}); a self-intersecting sweep is likely."
    return out
