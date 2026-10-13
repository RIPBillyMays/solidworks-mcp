# Modified for SOLIDWORKS 2017 support (fork).
"""LIVE verification of polygon fix, active_document stamping and activate_document.

Run with SOLIDWORKS 2017 running and no other document open. Calls server.call_tool
so begin_call and the stamping are exercised.  Saves only under sandbox/fix3_probes/.
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

OUT = ROOT / "sandbox" / "fix3_probes"
RESULTS: list[dict] = []
CREATED: list[str] = []


def call(name: str, args: dict | None = None) -> dict:
    fn = server.call_tool
    content = asyncio.run(fn(name, args or {}))
    return json.loads(content[0].text)


def d(p: dict) -> dict:
    return p.get("data", {}) or {}


def record(check: str, passed: bool, evidence: str) -> None:
    RESULTS.append({"check": check, "result": "PASS" if passed else "FAIL", "evidence": evidence})
    print(f"[{'PASS' if passed else 'FAIL'}] {check}: {evidence}", flush=True)


def new_part(sketch: str | None = None) -> dict:
    p = call("create_new_document", {"kind": "part"})
    if not p.get("ok"):
        raise RuntimeError(f"create failed {p}")
    title = d(p)["document"]["title"]
    CREATED.append(title)
    if sketch:
        s = call("create_sketch", {"plane": "front", "name": sketch})
        if not s.get("ok"):
            raise RuntimeError(f"sketch failed {s}")
    return p


def poly(inscribed: bool, name: str) -> None:
    new_part(name)
    p = call("draw_polygon", {"center_x_mm": 0, "center_y_mm": 0, "point_x_mm": 10, "point_y_mm": 0,
                              "sides": 6, "inscribed": inscribed})
    call("close_sketch", {})
    ext = call("boss_extrude", {"sketch_name": name, "depth_mm": 5, "name": name + "_Boss"})
    vol = float(d(call("get_mass_properties", {})).get("volume_mm3", float("nan"))) if ext.get("ok") else float("nan")
    return p, ext, vol


def c1_c2() -> None:
    p, ext, vol = poly(True, "P1")
    a = d(p).get("actual")
    area = 3 * math.sqrt(3) / 2 * 100
    record("1 polygon inscribed=true r=10", bool(p.get("ok")) and d(p).get("verified") is True,
           f"ok={p.get('ok')} verified={d(p).get('verified')} actual={a} msg={str(p.get('message'))[:80]}; "
           f"volume={vol:.3f} expected(corner 10)={area*5:.3f}")
    p, ext, vol = poly(False, "P2")
    a = d(p).get("actual")
    exp = 2 * math.sqrt(3) * 100 * 5
    record("2 polygon inscribed=false apothem 10", bool(p.get("ok")) and d(p).get("verified") is True
           and math.isclose(vol, exp, rel_tol=1e-3),
           f"ok={p.get('ok')} verified={d(p).get('verified')} actual={a} (expect corner 11.547); "
           f"volume={vol:.3f} expected={exp:.3f}")


def c3() -> None:
    new_part("R1")
    p = call("draw_rectangle", {"x1_mm": 0, "y1_mm": 0, "x2_mm": 30, "y2_mm": 20})
    record("3 draw_rectangle", bool(p.get("ok")) and d(p).get("verified") is True,
           f"ok={p.get('ok')} verified={d(p).get('verified')} actual={d(p).get('actual')}")
    call("close_sketch", {})


def c4_to_7() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    titles = []
    paths = []
    for tag in ("FixA", "FixB"):
        p7 = new_part("S")
        if tag == "FixA":
            c7_new = p7
        path = OUT / f"{tag}.sldprt"
        if path.exists():
            path.unlink()
        s = call("save_document", {"path": str(path)})
        info = call("get_active_document_info", {})
        t = d(info).get("title") or d(info).get("document", {}).get("title")
        print("saved", tag, s.get("ok"), s.get("message"), "title", t, "info", str(info)[:200])
        titles.append(t)
        paths.append(path)
        if t:
            CREATED[-1] = t
    a, b = titles
    record("7a create_new_document carries new active title",
           c7_new.get("active_document") is not None and c7_new["active_document"] == d(c7_new)["document"]["title"],
           f"active_document={c7_new.get('active_document')} doc={d(c7_new)['document']['title']}")
    mixed = "".join(ch.upper() if i % 2 else ch.lower() for i, ch in enumerate(a))
    r = call("activate_document", {"title": mixed})
    lf = call("list_features", {})
    record("4 activate_document mixed case", bool(r.get("ok")) and r.get("active_document") == a
           and lf.get("active_document") == a,
           f"A={a} B={b} requested={mixed} result.active_document={r.get('active_document')} ok={r.get('ok')} "
           f"list_features.active_document={lf.get('active_document')}")
    bad = call("activate_document", {"title": "no_such_doc_zzz"})
    record("5 bad title", bad.get("ok") is False, f"ok={bad.get('ok')} msg={str(bad.get('message'))[:100]} "
           f"active_document={bad.get('active_document')}")
    unk = call("definitely_not_a_tool", {})
    record("6 unknown tool after doc tool has no active_document",
           "active_document" not in unk and unk.get("ok") is False, f"{unk}")
    lod = call("list_open_documents", {})
    record("6b list_open_documents has no active_document", "active_document" not in lod, f"keys={list(lod)}")
    # open_document on b's saved file (already open, becomes active)
    o = call("open_document", {"path": str(paths[1])})
    record("7b open_document carries active title", bool(o.get("ok")) and o.get("active_document") == b,
           f"ok={o.get('ok')} active_document={o.get('active_document')} expected={b} msg={str(o.get('message'))[:80]}")


def main() -> int:
    before = d(call("list_open_documents", {})).get("documents", [])
    if before:
        print("STOP: documents already open:", [x["title"] for x in before])
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        for fn in (c1_c2, c3, c4_to_7):
            try:
                fn()
            except Exception as exc:
                record(fn.__name__, False, f"EXCEPTION {type(exc).__name__}: {exc}")
                traceback.print_exc()
    finally:
        for t in reversed(CREATED):
            try:
                print("closed", t, call("close_document", {"title": t, "force": True}).get("ok"))
            except Exception as exc:
                print("close fail", t, exc)
        left = d(call("list_open_documents", {})).get("documents", [])
        print("documents left:", [x["title"] for x in left])
        (OUT / "results.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    return 0 if all(r["result"] == "PASS" for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
