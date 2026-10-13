# Modified for SOLIDWORKS 2017 support (fork).
"""LIVE verification of the loft fix (finding #16): auto start alignment, start_points, hints, twist warning.

Run with SOLIDWORKS 2017 running, NO other document open, SW_MCP_OUTPUT_ROOT=<repo>\\sandbox\\loft_probes.
Creates scratch parts only; force-closes them.  Never saves.  Results go to stdout and
sandbox/loft_probes/loft_fix_results.json.
Usage: python tests/live_p5_loft_fix.py [check-prefix ...]   (e.g. 1 2 3)
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import live_p5_loft_probe as P  # noqa: E402

call, d, area = P.call, P.d, P.area
RESULTS: list[dict] = []


def est(dims, gap):
    return (area(*dims[:3]) + area(*dims[3:])) / 2 * gap


def ped(dims, gap):
    """Prismatoid estimate h/6 (A1 + 4 Am + A2) for comparison with the tool's expected_volume_mm3."""
    a1, a2 = area(*dims[:3]), area(*dims[3:])
    return gap / 6 * (a1 + 4 * (a1 + a2) / 2 + a2)


def arc_profile(plane, name, w, h, r, clockwise):
    """Rounded rectangle from lines and arcs; clockwise swaps each arc's start/end and passes direction -1."""
    s = call("create_sketch", {"name": name, **({"plane": "front"} if plane is None else {"plane_name": plane})})
    if not s.get("ok"):
        raise RuntimeError(f"create_sketch {s}")
    x, y = w / 2, h / 2
    lines = [
        (x, -y + r, x, y - r), (x - r, y, -x + r, y), (-x, y - r, -x, -y + r), (-x + r, -y, x - r, -y)]
    arcs = [  # centre, ccw start, ccw end
        ((x - r, y - r), (x, y - r), (x - r, y)), ((-x + r, y - r), (-x + r, y), (-x, y - r)),
        ((-x + r, -y + r), (-x, -y + r), (-x + r, -y)), ((x - r, -y + r), (x - r, -y), (x, -y + r))]
    for x1, y1, x2, y2 in lines:
        rr = call("draw_line", {"x1_mm": x1, "y1_mm": y1, "x2_mm": x2, "y2_mm": y2})
        if not rr.get("ok"):
            print("   line fail", rr.get("message"))
    for c, a, b in arcs:
        if clockwise:
            a, b = b, a
        rr = call("draw_arc", {"center_x_mm": c[0], "center_y_mm": c[1], "start_x_mm": a[0], "start_y_mm": a[1],
                               "end_x_mm": b[0], "end_y_mm": b[1], "direction": -1 if clockwise else 1})
        if not rr.get("ok"):
            print("   arc fail", rr.get("message"))
    segs = d(call("list_sketch_segments", {})).get("segments", [])
    call("close_sketch", {})
    return segs


def run(label, dims, loft_args=None, gap=2.8, builder=None, **kw):
    only = sys.argv[1:]
    if only and not any(label.startswith(o + " ") or label.split()[0].startswith(o) for o in only):
        return
    t = None
    row = {"label": label, "dims": dims, "gap": gap, "estimate": round(est(dims, gap), 1),
           "prismatoid": round(ped(dims, gap), 1)}
    try:
        P.STATE.clear()
        if builder:
            t = P.new_part()
            call("create_plane", {"mode": "offset", "selection": {"planes": ["front"]}, "distance_mm": gap, "name": "P2"})
            builder(dims)
        else:
            t = P.setup(dims, gap, **kw)
        r = call("loft", {"profile_sketches": ["SA", "SB"], **(loft_args or {})})
        data = d(r)
        row.update(ok=r.get("ok"), message=r.get("message"), start_points_mm=data.get("start_points_mm"),
                   counts=data.get("profile_segment_counts"), warnings=data.get("warnings"),
                   hint=data.get("hint"), twist_check=data.get("twist_check"),
                   delta=data.get("volume_delta_mm3"), expected=data.get("expected_volume_mm3"),
                   volume=round(P.vol(), 1))
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        row["exc"] = str(exc)
    finally:
        if t:
            try:
                P.close_part(t)
            except Exception:  # noqa: BLE001
                pass
    print(json.dumps(row, default=str), flush=True)
    RESULTS.append(row)


def main() -> None:
    docs = call("list_open_documents", {})
    print("open docs:", d(docs))
    if d(docs).get("documents") or d(docs).get("count"):
        print("DOCS OPEN - STOP")
        return
    A = (240, 70, 16, 234.4, 70, 16)
    zb = 2.8
    # 1 field case, default args
    run("1 field default", A)
    # 2 default auto-alignment against the investigation's mismatched-start constructions
    run("2a SB rev3 (23)", A, revB=3)
    run("2b SA rev3 (33)", A, revA=3)
    run("2c both 3 fillets different corners (47)", A, orderA=[0, 1, 2], orderB=[1, 2, 3])
    run("2d B rev1", A, revB=1)
    run("2e B rev2", A, revB=2)
    run("2f fillet order B rotated (14)", A, orderB=[2, 3, 0, 1])
    run("2g A 4 fillets B 3 fillets (44)", A, orderB=[0, 1, 2])
    run("2h left aligned (41)", A, cxA=120, cxB=117.2)
    run("2i A rev3 B rev2", A, revA=3, revB=2)
    # 3 explicit mismatched start points (sketch coords == model XY on Front; SB plane is at z=gap)
    run("3a explicit 180deg mismatch", A,
        {"start_points": [[224, 35, 0], [-(234.4 / 2 - 16), -35, zb]]}, revB=3)
    run("3b explicit 90deg mismatch (+X-Y)", A,
        {"start_points": [[224, 35, 0], [234.4 / 2 - 16, -35, zb]]}, revB=3)
    run("3c explicit matched (exact vertices)", A,
        {"start_points": [[104, 35, 0], [234.4 / 2 - 16, 35, zb]]}, revB=3)
    run("3f explicit 180deg mismatch (exact vertices)", A,
        {"start_points": [[104, 35, 0], [-(234.4 / 2 - 16), -35, zb]]})
    run("3g explicit 90deg mismatch (exact vertices)", A,
        {"start_points": [[104, 35, 0], [234.4 / 2 - 16, -35, zb]]})
    run("3d explicit bad point (off sketch)", A, {"start_points": [[0, 500, 0], [0, 500, zb]]})
    run("3e explicit wrong count", A, {"start_points": [[0, 0, 0]]})
    # 4 segment count mismatch
    run("4 segments 4 vs 8", (240, 70, 0, 234.4, 70, 16))
    run("4b segments 4 vs 8 explicit mismatch", (240, 70, 0, 234.4, 70, 16),
        {"start_points": [[120, 35, 0], [-(234.4 / 2 - 16), -35, zb]]})
    # 5 closed with 2 profiles
    run("5 closed two profiles", A, {"closed": True})
    # 6 clockwise arcs
    def b_ccw(dims):
        arc_profile(None, "SA", *dims[:3], clockwise=False)
        arc_profile("P2", "SB", *dims[3:], clockwise=False)

    def b_cw(dims):
        arc_profile(None, "SA", *dims[:3], clockwise=True)
        arc_profile("P2", "SB", *dims[3:], clockwise=True)

    def b_mix(dims):
        arc_profile(None, "SA", *dims[:3], clockwise=True)
        arc_profile("P2", "SB", *dims[3:], clockwise=False)

    run("6a arcs ccw", A, builder=b_ccw)
    run("6b arcs cw", A, builder=b_cw)
    run("6c arcs A cw B ccw", A, builder=b_mix)
    out = ROOT / "sandbox" / "loft_probes" / "loft_fix_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(RESULTS, indent=1, default=str))
    print("DONE")


if __name__ == "__main__":
    try:
        main()
    finally:
        for t in list(P.CREATED):
            try:
                P.close_part(t)
            except Exception:  # noqa: BLE001
                pass
        print("leftover:", d(call("list_open_documents", {})))
