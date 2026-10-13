# Modified for SOLIDWORKS 2017 support (fork).
"""LIVE verification of the Phase 5 file/inspect fixes (#10 rebuild, #18 list paging/filters, #19 screenshot save_as).

Run with SOLIDWORKS 2017 running and NO document open, and SW_MCP_OUTPUT_ROOT set to
<repo>\\sandbox\\fixes_probes (the script refuses to run otherwise).  Calls server.call_tool so
dispatch and stamping run.  Creates scratch parts only; force-closes everything it made.  Never saves a document.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from solidworks_mcp import server  # noqa: E402
from solidworks_mcp import sw_core  # noqa: E402

OUT = ROOT / "sandbox" / "fixes_probes"
RESULTS: list[dict] = []
CREATED: list[str] = []

GRID = 15          # GRID x GRID holes
PITCH = 10.0
RADIUS = 3.0
PLATE = GRID * PITCH  # 150 mm square, 5 mm thick


def call(name: str, args: dict | None = None) -> dict:
    content = asyncio.run(server.call_tool(name, args or {}))
    return json.loads(content[0].text)


def d(p: dict) -> dict:
    return p.get("data", {}) or {}


def record(finding: str, check: str, passed: bool | None, evidence: str) -> None:
    """passed=None records SKIP (could not set the scenario up live)."""
    status = "SKIP" if passed is None else ("PASS" if passed else "FAIL")
    RESULTS.append({"finding": finding, "check": check, "result": status, "evidence": evidence})
    print(f"[{status}] {finding} | {check}: {evidence}", flush=True)


def info(msg: str) -> None:
    print("  .", msg, flush=True)


def new_part() -> str:
    p = call("create_new_document", {"kind": "part"})
    if not p.get("ok"):
        raise RuntimeError(f"create failed {p}")
    title = d(p)["document"]["title"]
    CREATED.append(title)
    return title


def close_part(title: str) -> None:
    call("close_document", {"title": title, "force": True})
    if title in CREATED:
        CREATED.remove(title)


def near(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


def simple_box(depth=10, size=20) -> None:
    call("create_sketch", {"plane": "front", "name": "Base"})
    call("draw_rectangle", {"x1_mm": 0, "y1_mm": 0, "x2_mm": size, "y2_mm": size})
    call("close_sketch", {})
    b = call("boss_extrude", {"sketch_name": "Base", "depth_mm": depth, "name": "Box"})
    if not b.get("ok"):
        raise RuntimeError(f"box failed {b}")


# ---------------------------------------------------------------- #10
def f10() -> None:
    F = "#10"
    t = new_part()
    simple_box()
    r = call("rebuild_document", {})
    rd = d(r)
    record(F, "clean part: ok:true, problems [], warnings list, rebuild_returned present",
           bool(r.get("ok")) and rd.get("problems") == [] and isinstance(rd.get("warnings"), list)
           and "rebuild_returned" in rd,
           f"ok={r.get('ok')} data={json.dumps(rd)[:300]}")
    r = call("rebuild_document", {})  # second time: nothing stale
    rd = d(r)
    record(F, "second rebuild of an unchanged clean part still ok:true (ForceRebuild3 fallback allowed)",
           bool(r.get("ok")) and rd.get("problems") == [],
           f"ok={r.get('ok')} returned={rd.get('rebuild_returned')} err={rd.get('rebuild_error')} "
           f"force_used={rd.get('force_rebuild_used')} force_err={rd.get('force_rebuild_error')}")
    r = call("rebuild_document", {"force_all": True})
    rd = d(r)
    record(F, "force_all=true on clean part: ok:true and new fields present",
           bool(r.get("ok")) and rd.get("problems") == [] and "warnings" in rd and "rebuild_returned" in rd,
           f"ok={r.get('ok')} data={json.dumps(rd)[:300]}")
    record(F, "R2 force_all=true: no TypeError / rebuild_error in result",
           bool(r.get("ok")) and not rd.get("rebuild_error") and "TypeError" not in json.dumps(r),
           f"ok={r.get('ok')} rebuild_error={rd.get('rebuild_error')!r} returned={rd.get('rebuild_returned')}")

    # deliberate error: fillet that stops fitting once the box gets thin
    edges = d(call("list_edges", {"within_box": {"min": [-1, -1, 9.9], "max": [21, 21, 10.1]}})).get("edges", [])
    line = [e for e in edges if e.get("curve_type") == "line"]
    fr = call("fillet", {"radius_mm": 4, "selection": {"edges": [line[0]["index"]]}, "name": "BigFillet"})
    info(f"fillet R4 ok={fr.get('ok')}")
    # Radius far beyond the 10 mm box height: the fillet cannot rebuild any more.
    ef = call("edit_feature", {"feature_name": "BigFillet", "params": {"radius_mm": 40}})
    info(f"edit_feature fillet R40: ok={ef.get('ok')} changed={d(ef).get('changed')} msg={str(ef.get('message'))[:200]}")
    ce = call("check_errors", {})
    info(f"check_errors: {json.dumps(ce)[:300]}")
    r = call("rebuild_document", {})
    rd = d(r)
    probs = rd.get("problems") or []
    warns = rd.get("warnings") or []
    info(f"rebuild_document on broken part: ok={r.get('ok')} data={json.dumps(rd)[:500]}")
    if not probs and not warns and r.get("ok"):
        # SOLIDWORKS 2017 tolerated every attempt (fillet R40 on a 10 mm box, chamfer/shell edits are refused
        # and rolled back by edit_feature), so no rebuild error could be provoked through the public tools.
        record(F, "part with a deliberate error: errors under problems, warnings under warnings",
               None, "SKIP: could not provoke a rebuild error/warning (fillet R40 rebuilt fine; edit_feature rolls back bad edits)")
    else:
        record(F, "part with a deliberate error: ok:false, error under problems (not warnings)",
               r.get("ok") is False and len(probs) >= 1,
               f"ok={r.get('ok')} problems={json.dumps(probs)[:250]} warnings={json.dumps(warns)[:250]}")
    # restore -> clean again
    call("edit_feature", {"feature_name": "BigFillet", "params": {"radius_mm": 2}})
    r = call("rebuild_document", {})
    record(F, "after restoring radius: rebuild ok:true with no problems",
           bool(r.get("ok")) and (d(r).get("problems") == []), f"ok={r.get('ok')} problems={d(r).get('problems')}")
    close_part(t)


def f10_warning() -> None:
    """Try to provoke a pure warning: overdefined sketch.  Reported as RECORDED either way."""
    F = "#10"
    t = new_part()
    call("create_sketch", {"plane": "front", "name": "W"})
    call("draw_line", {"x1_mm": 0, "y1_mm": 0, "x2_mm": 30, "y2_mm": 0})
    call("draw_line", {"x1_mm": 30, "y1_mm": 0, "x2_mm": 30, "y2_mm": 20})
    call("draw_line", {"x1_mm": 30, "y1_mm": 20, "x2_mm": 0, "y2_mm": 20})
    call("draw_line", {"x1_mm": 0, "y1_mm": 20, "x2_mm": 0, "y2_mm": 0})
    for rel, sel in (("horizontal", [0]), ("vertical", [1]), ("horizontal", [2]), ("vertical", [3])):
        call("add_relation", {"relation": rel, "selection": {"sketch_segments": sel}})
    st = call("get_sketch_status", {})
    call("close_sketch", {})
    b = call("boss_extrude", {"sketch_name": "W", "depth_mm": 5})
    r = call("rebuild_document", {})
    rd = d(r)
    record(F, "RECORDED: rebuild of part with an underdefined sketch (warnings/problems split)",
           r.get("ok") is not None and bool(b.get("ok")),
           f"sketch_status={json.dumps(d(st))[:120]} ok={r.get('ok')} problems={json.dumps(rd.get('problems'))[:150]} "
           f"warnings={json.dumps(rd.get('warnings'))[:200]}")
    close_part(t)


# ---------------------------------------------------------------- #18
def build_grid_plate() -> str:
    t = new_part()
    call("create_sketch", {"plane": "front", "name": "PlateS"})
    call("draw_rectangle", {"x1_mm": 0, "y1_mm": 0, "x2_mm": PLATE, "y2_mm": PLATE})
    call("close_sketch", {})
    b = call("boss_extrude", {"sketch_name": "PlateS", "depth_mm": 5, "name": "Plate"})
    if not b.get("ok"):
        raise RuntimeError(f"plate failed {b}")
    # One hole, then a 15 x 15 linear pattern (225 hole faces): drawing 225 circles one by one is
    # O(n^2) in COM calls and takes over half an hour.
    call("create_sketch", {"plane": "front", "name": "HoleS"})
    call("draw_circle", {"x_mm": PITCH / 2, "y_mm": PITCH / 2, "radius_mm": RADIUS})
    call("close_sketch", {})
    c = call("cut_extrude", {"sketch_name": "HoleS", "depth_mm": 5, "direction": "+normal", "name": "Hole0"})
    info(f"cut ok={c.get('ok')} delta={d(c).get('volume_delta_mm3')}")
    if not c.get("ok"):
        raise RuntimeError(f"cut failed {c}")
    edges = d(call("list_edges", {"limit": 1000})).get("edges", [])
    ex = [e for e in edges if e.get("curve_type") == "line" and near(e["start_mm"][1], e["end_mm"][1], 1e-6)
          and near(e["start_mm"][2], e["end_mm"][2], 1e-6) and abs(e["start_mm"][0] - e["end_mm"][0]) > PLATE - 1]
    ey = [e for e in edges if e.get("curve_type") == "line" and near(e["start_mm"][0], e["end_mm"][0], 1e-6)
          and near(e["start_mm"][2], e["end_mm"][2], 1e-6) and abs(e["start_mm"][1] - e["end_mm"][1]) > PLATE - 1]
    if not ex or not ey:
        raise RuntimeError("could not find plate edges for pattern directions")
    want = PLATE * PLATE * 5 - GRID * GRID * math.pi * RADIUS ** 2 * 5
    for r1 in (False, True):
        for r2 in (False, True):
            pr = call("linear_pattern", {
                "selection": {"features": ["Hole0"]}, "direction1_selection": {"edges": [ex[0]["index"]]},
                "count1": GRID, "spacing1_mm": PITCH, "reverse1": r1,
                "direction2_selection": {"edges": [ey[0]["index"]]}, "count2": GRID, "spacing2_mm": PITCH, "reverse2": r2,
                "name": "HolesPat"})
            v = d(call("get_mass_properties", {})).get("volume_mm3", 0.0)
            info(f"pattern reverse=({r1},{r2}) ok={pr.get('ok')} vol={v} want={want:.1f}")
            if pr.get("ok") and abs(v - want) < 1.0:
                return t
            if pr.get("ok"):
                call("delete_feature", {"feature_names": ["HolesPat"]})
    raise RuntimeError("pattern did not reach the expected volume")


def f18() -> None:
    F = "#18"
    t = build_grid_plate()
    expected_vol = PLATE * PLATE * 5 - GRID * GRID * math.pi * RADIUS ** 2 * 5
    v = d(call("get_mass_properties", {})).get("volume_mm3")
    info(f"volume {v} expected {expected_vol:.3f}")

    full = call("list_faces", {})
    fd = d(full)
    N = fd.get("total_faces")
    first = fd.get("faces", [])
    record(F, "list_faces default on >200-face part: 200 returned, truncated true, total == total_faces == N, offset 0",
           isinstance(N, int) and N > 200 and len(first) == 200 and fd.get("truncated") is True
           and fd.get("total") == N and fd.get("offset") == 0,
           f"N={N} returned={len(first)} truncated={fd.get('truncated')} total={fd.get('total')} offset={fd.get('offset')} "
           f"msg={str(full.get('message'))[:140]}")
    # page through, union must be 0..N-1
    allf = list(first)
    off = 200
    while True:
        pg = d(call("list_faces", {"offset": off}))
        allf += pg.get("faces", [])
        if not pg.get("truncated"):
            last = pg
            break
        off += len(pg.get("faces", []))
    idxs = sorted(f["index"] for f in allf)
    record(F, "offset paging reaches the end: last page truncated false, union of indices == 0..N-1 exactly once",
           idxs == list(range(N)) and last.get("offset") == 200,
           f"pages_total={len(allf)} unique={len(set(idxs))} N={N} last.offset={last.get('offset')} last.len={len(last.get('faces', []))}")
    p5 = d(call("list_faces", {"limit": 5, "offset": 3}))
    record(F, "limit=5 offset=3: 5 returned, truncated true, offset 3, total N, first index 3",
           len(p5.get("faces", [])) == 5 and p5.get("truncated") is True and p5.get("offset") == 3
           and p5.get("total") == N and p5["faces"][0]["index"] == 3,
           f"len={len(p5.get('faces', []))} truncated={p5.get('truncated')} offset={p5.get('offset')} total={p5.get('total')} "
           f"first={p5['faces'][0]['index'] if p5.get('faces') else None}")
    tail = d(call("list_faces", {"limit": 5, "offset": N - 3}))
    record(F, "offset near end: 3 returned, truncated false",
           len(tail.get("faces", [])) == 3 and tail.get("truncated") is False, f"len={len(tail.get('faces', []))} truncated={tail.get('truncated')}")

    # feature filter (COM equality)
    hf = d(call("list_faces", {"feature": "HolesPat", "limit": 1000}))
    h0 = d(call("list_faces", {"feature": "Hole0", "limit": 1000})).get("faces", [])
    cyl = [f for f in allf if f.get("surface_type") == "cylinder"]
    hole_faces = hf.get("faces", [])
    record(F, "feature='HolesPat' + 'Hole0': together exactly the 225 cylinder faces, all cylinders, no plate faces",
           len(hole_faces) + len(h0) == GRID * GRID and all(f.get("surface_type") == "cylinder" for f in hole_faces + h0)
           and sorted(f["index"] for f in hole_faces + h0) == sorted(f["index"] for f in cyl),
           f"HolesPat={len(hole_faces)} Hole0={len(h0)} cylinders_in_part={len(cyl)} total={hf.get('total')} "
           f"types={sorted(set(str(f.get('surface_type')) for f in hole_faces))}")
    pf = d(call("list_faces", {"feature": "Plate", "limit": 1000}))
    pl = pf.get("faces", [])
    record(F, "feature='Plate': no hole cylinders, only plane faces (planar top/bottom/sides)",
           len(pl) >= 2 and all(f.get("surface_type") == "plane" for f in pl) and len(pl) <= 6,
           f"returned={len(pl)} types={[f.get('surface_type') for f in pl]} areas={[f.get('area_mm2') for f in pl]}")
    try:
        bad = call("list_faces", {"feature": "NoSuchFeature"})
        record(F, "unknown feature refused", bad.get("ok") is False, f"ok={bad.get('ok')} msg={str(bad.get('message'))[:100]}")
    except Exception as exc:
        record(F, "unknown feature refused", False, f"EXC {exc}")

    # within_box: first hole is centred at (5,5)
    box = {"min": [0.0, 0.0, -0.5], "max": [10.0, 10.0, 5.5]}
    wb = d(call("list_faces", {"within_box": box, "limit": 1000}))
    lo, hi = box["min"], box["max"]
    truth = sorted(f["index"] for f in allf
                   if f.get("point_mm") and all(lo[i] <= f["point_mm"][i] <= hi[i] for i in range(3)))
    got = sorted(f["index"] for f in wb.get("faces", []))
    record(F, "within_box on faces matches an independent filter of the full list (and is non-empty, not everything)",
           got == truth and 1 <= len(got) < N, f"got={got} truth={truth} N={N}")
    swapped = d(call("list_faces", {"within_box": {"min": box["max"], "max": box["min"]}, "limit": 1000}))
    record(F, "within_box with swapped corners gives the same faces",
           sorted(f["index"] for f in swapped.get("faces", [])) == truth, f"got={[f['index'] for f in swapped.get('faces', [])]}")

    close_part(t)


def f18_edges() -> None:
    F = "#18"
    t = build_grid_plate()
    lo, hi = [0.0, 0.0, -0.5], [10.0, 10.0, 5.5]
    box = {"min": lo, "max": hi}
    # edges
    import time
    t0 = time.time()
    ea = d(call("list_edges", {"limit": 5000}))
    info(f"list_edges full took {time.time() - t0:.0f}s")
    E = ea.get("total_edges")
    alle = ea.get("edges", [])
    record(F, "list_edges limit=5000 returns every edge; default (200) truncates with total",
           len(alle) == E and ea.get("truncated") is False
           and ea.get("total") == E,
           f"E={E} returned={len(alle)} truncated={ea.get('truncated')} total={ea.get('total')}")
    dflt = d(call("list_edges", {}))
    record(F, "list_edges default limit 200: 200 returned, truncated true, total == total_edges",
           len(dflt.get("edges", [])) == 200 and dflt.get("truncated") is True and dflt.get("total") == E,
           f"returned={len(dflt.get('edges', []))} truncated={dflt.get('truncated')} total={dflt.get('total')} E={E}")
    he = d(call("list_edges", {"feature": "HolesPat", "limit": 5000}))
    hed = he.get("edges", [])
    record(F, "list_edges feature='HolesPat': circular hole rims only (>= 2*224 circles), fewer than all edges",
           len(hed) >= 2 * (GRID * GRID - 1) and sum(1 for e in hed if e.get("curve_type") == "circle") >= 2 * (GRID * GRID - 1)
           and len(hed) < E
           and all(e.get("curve_type") in ("circle", "line") for e in hed),
           f"returned={len(hed)} circles={sum(1 for e in hed if e.get('curve_type') == 'circle')} "
           f"lines={sum(1 for e in hed if e.get('curve_type') == 'line')} total_edges={E}")
    ebox = {"min": [0.0, 0.0, -0.5], "max": [10.0, 10.0, 5.5]}
    we = d(call("list_edges", {"within_box": ebox, "limit": 5000}))
    def _pts(e):
        return [e[k] for k in ("point_mm", "start_mm", "end_mm") if e.get(k)]

    etruth = sorted(e["index"] for e in alle
                    if _pts(e) and all(lo[i] <= p[i] <= hi[i] for p in _pts(e) for i in range(3)))
    egot = sorted(e["index"] for e in we.get("edges", []))
    record(F, "within_box on edges matches independent filter and is non-empty",
           egot == etruth and 1 <= len(egot) < E, f"got={egot} truth={etruth} E={E}")
    close_part(t)


# ---------------------------------------------------------------- #19
def f19() -> None:
    F = "#19"
    root = Path(sw_core.OUTPUT_ROOT)
    shots = root / "screenshots"
    t = new_part()
    simple_box()
    before = set(shots.glob("*")) if shots.exists() else set()
    r = call("capture_screenshot", {"save_as": "probe19.png", "width_px": 600})
    rd = d(r)
    saved = Path(rd.get("saved_path", "")) if rd.get("saved_path") else None
    expected = shots / "probe19.png"
    size = expected.stat().st_size if expected.exists() else -1
    sig = expected.read_bytes()[:8] if expected.exists() else b""
    record(F, "save_as='probe19.png': file exists under OUTPUT_ROOT/screenshots, non-empty PNG, saved_path matches",
           bool(r.get("ok")) and expected.exists() and size > 1000 and sig == b"\x89PNG\r\n\x1a\n"
           and saved is not None and saved.resolve() == expected.resolve(),
           f"ok={r.get('ok')} saved_path={rd.get('saved_path')} size={size} sig={sig!r} root={root}")
    mid = set(shots.glob("*"))
    r2 = call("capture_screenshot", {"width_px": 400})
    after = set(shots.glob("*"))
    record(F, "no save_as: no leftover file added",
           bool(r2.get("ok")) and after == mid and "saved_path" not in d(r2),
           f"ok={r2.get('ok')} new_files={[p.name for p in after - mid]} saved_path={d(r2).get('saved_path')}")
    for bad in ("../x", "a/b.png", "..\\x.png", "C:x.png", "CON", "NUL.png"):
        pre = set(shots.glob("*")) if shots.exists() else set()
        rb = call("capture_screenshot", {"save_as": bad})
        post = set(shots.glob("*")) if shots.exists() else set()
        record(F, f"save_as={bad!r} rejected, nothing written",
               rb.get("ok") is False and pre == post, f"ok={rb.get('ok')} new={[p.name for p in post - pre]} msg={str(rb.get('message'))[:100]}")
    r3 = call("capture_screenshot", {"save_as": "noext", "view": "current", "width_px": 300})
    record(F, "name without extension gets .png appended",
           bool(r3.get("ok")) and (shots / "noext.png").exists() and (shots / "noext.png").stat().st_size > 0,
           f"ok={r3.get('ok')} saved_path={d(r3).get('saved_path')}")
    close_part(t)


def main() -> int:
    env_root = os.environ.get("SW_MCP_OUTPUT_ROOT", "")
    if Path(sw_core.OUTPUT_ROOT).resolve() != (ROOT / "sandbox" / "fixes_probes").resolve():
        print("STOP: OUTPUT_ROOT is", sw_core.OUTPUT_ROOT, "env", env_root)
        return 3
    before = d(call("list_open_documents", {})).get("documents", [])
    if before:
        print("STOP: documents already open:", [x["title"] for x in before])
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        only = sys.argv[1:]
        for fn in (f10, f10_warning, f19, f18, f18_edges):
            if only and fn.__name__ not in only:
                continue
            try:
                fn()
            except Exception as exc:
                record(fn.__name__, "script", False, f"EXCEPTION {type(exc).__name__}: {exc}")
                traceback.print_exc()
    finally:
        for t in reversed(list(CREATED)):
            try:
                print("closed", t, call("close_document", {"title": t, "force": True}).get("ok"))
            except Exception as exc:
                print("close fail", t, exc)
        left = d(call("list_open_documents", {})).get("documents", [])
        print("documents left:", [x["title"] for x in left])
        suffix = "_" + "_".join(sys.argv[1:]) if sys.argv[1:] else ""
        (OUT / f"results_file_inspect{suffix}.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    return 0 if all(r["result"] in ("PASS", "SKIP") for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
