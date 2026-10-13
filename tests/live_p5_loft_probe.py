# Modified for SOLIDWORKS 2017 support (fork).
"""LIVE probe for finding #16 (loft fails 240x70 R16 -> 234.4x70 R16, 2.8 mm apart).

Run with SOLIDWORKS 2017 running, NO other document open, SW_MCP_OUTPUT_ROOT=<repo>\\sandbox\\loft_probes.
Calls server.call_tool; direct COM for InsertProtrusionBlend2 option experiments.
Creates scratch parts only; force-closes them.  Never saves.
Usage: python tests/live_p5_loft_probe.py [case-number-prefix ...]
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from solidworks_mcp import server  # noqa: E402
from solidworks_mcp.sw_core import (  # noqa: E402
    active_document, clear_selection, extension, feature_manager, nothing, whats_wrong,
)

CREATED: list[str] = []
STATE: dict = {}


def call(name: str, args: dict | None = None) -> dict:
    return json.loads(asyncio.run(server.call_tool(name, args or {}))[0].text)


def d(p: dict) -> dict:
    return p.get("data", {}) or {}


def new_part() -> str:
    p = call("create_new_document", {"kind": "part"})
    if not p.get("ok"):
        raise RuntimeError(f"create failed {p}")
    t = d(p)["document"]["title"]
    CREATED.append(t)
    return t


def close_part(t: str) -> None:
    call("close_document", {"title": t, "force": True})
    if t in CREATED:
        CREATED.remove(t)


def vol() -> float:
    p = call("get_mass_properties", {})
    return float(d(p).get("volume_mm3", 0.0)) if p.get("ok") else 0.0


def area(w, h, r):
    return w * h - (4 - math.pi) * r * r


def profile(plane, name, w, h, r, corner_order=None, rev=0, cx=0.0, cy=0.0):
    """Rounded rectangle centred on the origin (sketch x/y = model X/Y)."""
    args = {"name": name}
    if plane is None:
        args["plane"] = "front"
    else:
        args["plane_name"] = plane
    s = call("create_sketch", args)
    if not s.get("ok"):
        raise RuntimeError(f"create_sketch {s}")
    origin = d(s).get("origin")
    xs = [(-w / 2 + cx, -h / 2 + cy), (w / 2 + cx, h / 2 + cy)]
    if rev == 1:
        xs = xs[::-1]
    elif rev == 2:
        xs = [(-w / 2 + cx, h / 2 + cy), (w / 2 + cx, -h / 2 + cy)]
    elif rev == 3:
        xs = [(w / 2 + cx, -h / 2 + cy), (-w / 2 + cx, h / 2 + cy)]
    call("draw_rectangle", {"x1_mm": xs[0][0], "y1_mm": xs[0][1], "x2_mm": xs[1][0], "y2_mm": xs[1][1]})
    if r > 0:
        corners = [(w / 2 + cx, h / 2 + cy), (-w / 2 + cx, h / 2 + cy), (-w / 2 + cx, -h / 2 + cy), (w / 2 + cx, -h / 2 + cy)]
        if corner_order:
            corners = [corners[i] for i in corner_order]
        f = call("sketch_fillet", {"radius_mm": r, "corners": [{"x": x, "y": y} for x, y in corners]})
        if not f.get("ok"):
            print("   fillet fail", f.get("message"))
    segs = call("list_sketch_segments", {})
    STATE.setdefault("segs", {})[name] = [
        (s_.get("type"), s_.get("start"), s_.get("end")) for s_ in d(segs).get("segments", [])
    ]
    call("close_sketch", {})
    return origin


def setup(dims, gap=2.8, orderA=None, orderB=None, revA=0, revB=0, cxA=0.0, cxB=0.0):
    wA, hA, rA, wB, hB, rB = dims
    t = new_part()
    call("create_plane", {"mode": "offset", "selection": {"planes": ["front"]}, "distance_mm": gap, "name": "P2"})
    oa = profile(None, "SA", wA, hA, rA, orderA, revA, cxA, hA / 2 if cxA else 0.0)
    ob = profile("P2", "SB", wB, hB, rB, orderB, revB, cxB, hB / 2 if cxB else 0.0)
    STATE["origins"] = (oa, ob)
    STATE["zb"] = ob[2] if ob else gap
    return t


def pick_loft(doc, sketches, picks, *, closed=False, keep=False, nonrational=False, tess=1.0,
              merge=True, mark=1, start_t=0, end_t=0):
    clear_selection(doc)
    ext = extension(doc)
    for i, (nm, pt) in enumerate(zip(sketches, picks)):
        x, y, z = pt if pt else (0, 0, 0)
        ok = ext.SelectByID2(nm, "SKETCH", x / 1000, y / 1000, z / 1000, i > 0, mark, nothing(), 0)
        if not ok:
            print("   select failed", nm, pt)
    fm = feature_manager(doc)
    return fm.InsertProtrusionBlend2(
        closed, keep, nonrational, tess, start_t, end_t, 0.0, 0.0, True, True,
        False, 0.0, 0.0, 0, merge, True, True, 0)


def tool_loft(sketches=("SA", "SB"), **extra):
    def f(doc):
        r = call("loft", {"profile_sketches": list(sketches), **extra})
        print("   tool msg:", r.get("message"), json.dumps(d(r).get("problems", "")))
        return "OK" if r.get("ok") else "FAIL"
    return f


def com_loft(picks=None, sketches=("SA", "SB"), **kw):
    def f(doc):
        pk = picks(STATE) if picks else [None, None]
        r = pick_loft(doc, list(sketches), pk, **kw)
        return "OK" if r is not None else "FAIL"
    return f


ROWS: list[str] = []


def case(label, settings, dims, loft_fn, gap=2.8, **kw):
    only = sys.argv[1:]
    if only and not any(label.startswith(o + " ") for o in only):
        return
    est = (area(*dims[:3]) + area(*dims[3:])) / 2 * gap
    t = None
    try:
        STATE.clear()
        t = setup(dims, gap, **kw)
        _, doc = active_document()
        res = loft_fn(doc)
        v = vol()
        names = [f.get("name") for f in d(call("list_features", {})).get("features", [])]
        tail = [n for n in names if "oft" in str(n)]
        ww = whats_wrong(doc)
        line = f"| {label} | {settings} | {res} | {v:.1f} (est {est:.1f}) | feat {tail} wrong {ww} |"
    except Exception as exc:
        traceback.print_exc()
        line = f"| {label} | {settings} | EXC {exc} | | |"
    finally:
        if t:
            try:
                close_part(t)
            except Exception:
                pass
    print(line, flush=True)
    ROWS.append(line)


def main() -> None:
    docs = call("list_open_documents", {})
    print("open docs:", d(docs))
    if d(docs).get("documents") or d(docs).get("count"):
        print("DOCS OPEN - STOP")
        return
    A = (240, 70, 16, 234.4, 70, 16)
    mp = lambda zsh=1: (lambda st: [(240 / 2 - 16, 35, 0), (234.4 / 2 - 16, 35, st["zb"])])
    mm = lambda st: [(240 / 2 - 16, 35, 0), (-(234.4 / 2 - 16), -35, st["zb"])]
    case("1 baseline tool", "tool loft SA,SB 240x70R16 -> 234.4x70R16", A, tool_loft())
    case("2 ref good tool", "234.4x70R16 -> 232x67.6R14.8", (234.4, 70, 16, 232, 67.6, 14.8), tool_loft())
    case("3 COM default", "SelectByID2 pt=origin, tool flags", A, com_loft())
    case("4 COM matched picks", "pick +X+Y top tangent both", A, com_loft(mp()))
    case("5 COM mismatched picks", "pick +X+Y on SA, -X-Y on SB", A, com_loft(mm))
    case("6 no fillets", "240x70 -> 234.4x70 plain", (240, 70, 0, 234.4, 70, 0), tool_loft())
    case("7 R16 240->238", "240x70R16 -> 238x70R16", (240, 70, 16, 238, 70, 16), tool_loft())
    case("8 identical", "240x70R16 x2", (240, 70, 16, 240, 70, 16), tool_loft())
    case("9 reversed order", "SB,SA", A, tool_loft(("SB", "SA")))
    case("10 keep tangency", "KeepTangency true", A, com_loft(keep=True))
    case("11 nonrational", "ForceNonRational true", A, com_loft(nonrational=True))
    case("12 closed", "Closed true", A, com_loft(closed=True))
    case("13 no merge", "merge false", A, com_loft(merge=False))
    case("14 corner order B", "SB fillet order rotated 2", A, tool_loft(), orderB=[2, 3, 0, 1])
    case("15 gap 10mm", "240->234.4 gap 10", A, tool_loft(), gap=10)
    case("16 diff height", "240x70R16 -> 234.4x69R16", (240, 70, 16, 234.4, 69, 16), tool_loft())
    case("17 diff R", "240x70R16 -> 234.4x70R15.9", (240, 70, 16, 234.4, 70, 15.9), tool_loft())
    for rb in (1, 2, 3):
        case(f"2{rb} B drawn rev={rb}", f"SB rectangle corners mode {rb}", A, tool_loft(), revB=rb)
    for ra in (1, 2, 3):
        case(f"3{ra} A drawn rev={ra}", f"SA rectangle corners mode {ra}", A, tool_loft(), revA=ra)
    case("41 corner-origin", "A x0..240, B x0..234.4 (left aligned)", A, tool_loft(), cxA=120, cxB=117.2)
    case("42 corner-origin right", "A x0..240, B x5.6..240 (right aligned)", A, tool_loft(), cxA=120, cxB=122.8)
    case("43 B only fillets", "A sharp 240x70, B R16", (240, 70, 0, 234.4, 70, 16), tool_loft())
    case("24 B rev=3 matched picks", "SB mode3, picks +X+Y top tangent both", A, com_loft(mp()), revB=3)
    case("25 B rev=3 picks at SB start vertex far", "SB mode3, pick SA +X+Y, SB -X-Y", A, com_loft(mm), revB=3)
    case("26 B rev=3 picks mm2", "SB mode3, pick SA +X+Y, SB +X-Y", A,
         com_loft(lambda st: [(224, 35, 0), (234.4 / 2 - 16, -35, st["zb"])]), revB=3)
    case("27 B rev=3 picks mm3", "SB mode3, pick SA +X+Y, SB -X+Y", A,
         com_loft(lambda st: [(224, 35, 0), (-(234.4 / 2 - 16), 35, st["zb"])]), revB=3)
    case("44 B 3 fillets", "A 4 fillets, B 3 fillets", A, tool_loft(), orderB=[0, 1, 2])
    case("45 A 3 fillets", "A 3 fillets, B 4 fillets", A, tool_loft(), orderA=[0, 1, 2])
    case("46 both 3 fillets same", "both 3 fillets", A, tool_loft(), orderA=[0, 1, 2], orderB=[0, 1, 2])
    case("47 both 3 fillets different", "A fillets 0,1,2 B fillets 1,2,3", A, tool_loft(), orderA=[0, 1, 2], orderB=[1, 2, 3])
    print("\n".join(ROWS))
    print("DONE")


if __name__ == "__main__":
    try:
        main()
    finally:
        for t in list(CREATED):
            try:
                close_part(t)
            except Exception:
                pass
        print("leftover:", d(call("list_open_documents", {})))
