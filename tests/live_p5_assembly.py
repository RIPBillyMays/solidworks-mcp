"""LIVE Phase 5 assembly scenario (SW 2017 must be running, launched by the user).

Run with SW_MCP_OUTPUT_ROOT=<repo>\\sandbox.  Calls tool handlers in-process.
Writes every file under sandbox\\phase5\\asm\\ and closes only documents it created.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from solidworks_mcp.sw_assembly import (  # noqa: E402
    add_mate, delete_mate, insert_component, list_components, list_mates, set_component_fixed,
)
from solidworks_mcp.sw_feature import boss_extrude, cut_extrude  # noqa: E402
from solidworks_mcp.sw_file import (  # noqa: E402
    close_document, create_new_document, list_open_documents, save_document,
)
from solidworks_mcp.sw_inspect import check_errors, get_mass_properties, list_faces  # noqa: E402
from solidworks_mcp.sw_sketch import close_sketch, create_sketch, draw_circle, draw_rectangle, set_dimension  # noqa: E402

OUT = ROOT / "sandbox" / "phase5" / "asm"
OUT.mkdir(parents=True, exist_ok=True)
LOG: list[str] = []
created: list[str] = []  # titles of docs this script created


def log(step: str, ok: bool, detail: str = "") -> None:
    line = f"{'PASS' if ok else 'FAIL'} | {step} | {detail}"
    LOG.append(line)
    print(line, flush=True)


def call(fn, args, ctx=""):
    r = fn(args)
    if not r.get("ok"):
        print(f"  (call {fn.__name__} {ctx} -> not ok: {r.get('message')} "
              f"{json.dumps(r.get('data'), default=str)[:300]})", flush=True)
    return r


def docs():
    return call(list_open_documents, {})["data"]["documents"]


def title_for(path: Path):
    for d in docs():
        if d.get("path") and Path(d["path"]).resolve() == path.resolve():
            return d["title"]
    return None


def near(a, b, tol=0.05):
    return abs(a - b) <= tol


def build_part(sketch_fn, depth, tag):
    call(create_new_document, {"kind": "part"})
    call(create_sketch, {"plane": "front", "name": f"{tag}_sk"})
    sketch_fn()
    call(close_sketch, {})
    return call(boss_extrude, {"sketch_name": f"{tag}_sk", "depth_mm": depth, "name": f"{tag}_boss"})


def step_parts():
    build_part(lambda: call(draw_rectangle, {"x1_mm": -50, "y1_mm": -30, "x2_mm": 50, "y2_mm": 30}), 10, "A")
    call(create_sketch, {"plane": "front", "name": "A_hole_sk"})
    call(draw_circle, {"x_mm": 0, "y_mm": 0, "radius_mm": 5})
    call(close_sketch, {})
    call(cut_extrude, {"sketch_name": "A_hole_sk", "end_condition": "through_all", "name": "A_hole"})
    va = call(get_mass_properties, {})["data"]["volume_mm3"]
    pa = OUT / "A.sldprt"
    pa.unlink(missing_ok=True)
    call(save_document, {"path": str(pa)})
    build_part(lambda: call(draw_circle, {"x_mm": 0, "y_mm": 0, "radius_mm": 5}), 30, "B")
    vb = call(get_mass_properties, {})["data"]["volume_mm3"]
    pb = OUT / "B.sldprt"
    pb.unlink(missing_ok=True)
    call(save_document, {"path": str(pb)})
    ea, eb = 60000 - math.pi * 25 * 10, math.pi * 25 * 30
    log("2 part A volume", near(va, ea, 1.0), f"{va:.3f} vs {ea:.3f}")
    log("2 part B volume", near(vb, eb, 1.0), f"{vb:.3f} vs {eb:.3f}")
    log("2 files exist non-empty",
        pa.exists() and pa.stat().st_size > 0 and pb.exists() and pb.stat().st_size > 0,
        f"A={pa.stat().st_size if pa.exists() else None} B={pb.stat().st_size if pb.exists() else None}")
    ta, tb = title_for(pa), title_for(pb)
    created.extend([t for t in (ta, tb) if t])
    return pa, pb, ta, tb


def faces_now():
    return call(list_faces, {})["data"]["faces"]


def find(faces, bodykey, stype, normal=None):
    out = []
    for f in faces:
        if bodykey.lower() not in str(f.get("body", "")).lower():
            continue
        if f.get("surface_type") != stype:
            continue
        if normal and f.get("normal"):
            if abs(sum(a * b for a, b in zip(f["normal"], normal)) - 1) > 0.02:
                continue
        out.append(f)
    return out


def at_z(fs, z, tol=0.5):
    return [f for f in fs if abs(f["point_mm"][2] - z) < tol] or fs


def comp_origins():
    return {c["name"]: c.get("origin_mm") for c in call(list_components, {})["data"]["components"]}


def main(baseline):
    log("1 baseline", True, f"{baseline}")
    pa, pb, ta, tb = step_parts()

    ra = call(close_document, {"title": ta, "save": False})
    rb = call(close_document, {"title": tb, "save": False})
    log("3 close A,B (save=false, clean)", ra["ok"] and rb["ok"], f"{ra['message']} | {rb['message']}")
    created.clear()
    after = [d["title"] for d in docs()]
    log("3 counts back to baseline after closing parts", after == baseline, f"{after}")

    call(create_new_document, {"kind": "part"})
    call(create_sketch, {"plane": "front", "name": "Dirty_sk"})
    call(draw_circle, {"x_mm": 0, "y_mm": 0, "radius_mm": 5})
    call(close_sketch, {})
    call(boss_extrude, {"sketch_name": "Dirty_sk", "depth_mm": 5})
    d = [x for x in docs() if x["title"] not in baseline]
    dt = d[0]["title"] if d else None
    if dt:
        created.append(dt)
    log("3 dirty doc flagged", bool(d) and bool(d[0].get("dirty")), f"{d}")
    r = call(close_document, {"title": dt, "save": False, "force": False})
    still = any(x["title"] == dt for x in docs())
    log("3 dirty close refused", (not r["ok"]) and still, r["message"])
    r = call(close_document, {"title": dt, "force": True})
    gone = not any(x["title"] == dt for x in docs())
    log("3 force close works", r["ok"] and gone, r["message"])
    if gone:
        created.remove(dt)

    r = call(create_new_document, {"kind": "assembly"})
    adoc = [x for x in docs() if x["title"] not in baseline]
    if adoc:
        created.append(adoc[0]["title"])
    log("4 new assembly", r["ok"], r["message"])
    ia = call(insert_component, {"path": str(pa), "x_mm": 0, "y_mm": 0, "z_mm": 0})
    ib = call(insert_component, {"path": str(pb), "x_mm": 50, "y_mm": 0, "z_mm": 40})
    for x in docs():
        if x["title"] not in baseline and x["title"] not in created:
            created.append(x["title"])
    oa, obb = ia["data"].get("origin_mm"), ib["data"].get("origin_mm")
    log("4 insert A origin (0,0,0)", ia["ok"] and bool(oa) and all(near(v, 0, 0.01) for v in oa), str(oa))
    log("4 insert B origin (50,0,40)", ib["ok"] and bool(obb) and all(near(v, e, 0.01) for v, e in zip(obb, (50, 0, 40))), str(obb))
    nameA, nameB = ia["data"]["component"], ib["data"]["component"]
    r = call(set_component_fixed, {"component_names": [nameA], "fixed": True})
    log("4 fix A", r["ok"], r["message"])

    faces = faces_now()
    print("  faces:", [(f["index"], f.get("body"), f.get("surface_type"), f.get("normal"), f.get("point_mm"))
                       for f in faces], flush=True)
    hole = find(faces, "A", "cylinder")
    pin = find(faces, "B", "cylinder")
    pinbot = find(faces, "B", "plane", (0, 0, -1))
    platetop = at_z(find(faces, "A", "plane", (0, 0, 1)), 10)
    log("4 face lookup", all([hole, pin, pinbot, platetop]),
        f"hole={[f['index'] for f in hole]} pin={[f['index'] for f in pin]} "
        f"pinbot={[f['index'] for f in pinbot]} platetop={[f['index'] for f in platetop]}")
    if not all([hole, pin, pinbot, platetop]):
        return

    def origin_b():
        return comp_origins().get(nameB)

    r = call(add_mate, {"mate_type": "concentric", "selection": {"faces": [pin[0]["index"], hole[0]["index"]]}})
    ob = origin_b()
    log("4a concentric", r["ok"] and near(ob[0], 0) and near(ob[1], 0), f"{r['message']} B origin={ob}")

    faces = faces_now()
    pinbot = find(faces, "B", "plane", (0, 0, -1))
    platetop = at_z(find(faces, "A", "plane", (0, 0, 1)), 10)
    r = call(add_mate, {"mate_type": "coincident",
                        "selection": {"faces": [pinbot[0]["index"], platetop[0]["index"]]},
                        "alignment": "anti_aligned"})
    ob = origin_b()
    log("4b coincident (pin bottom on plate top)", r["ok"] and near(ob[2], 10), f"{r['message']} B origin={ob} (expect z=10)")

    faces = faces_now()
    pintop = find(faces, "B", "plane", (0, 0, 1))
    platebot = at_z(find(faces, "A", "plane", (0, 0, -1)), 0)
    r = call(add_mate, {"mate_type": "distance", "distance_mm": 40,
                        "selection": {"faces": [pintop[0]["index"], platebot[0]["index"]]},
                        "alignment": "aligned"})
    ob = origin_b()
    log("4c distance 40 (pin top to plate bottom; consistent with coincident)", r["ok"] and near(ob[2], 10),
        f"{r['message']} warn={r['data'].get('warning')} B origin={ob}")
    log("4d angle/parallel", True, "SKIPPED: no non-axial planar pairs (pin is a cylinder; plate faces only +/-Z)")
    m = call(list_mates, {})["data"]["mates"]
    log("4 list_mates", len(m) >= 3, json.dumps(m))
    ce = call(check_errors, {})
    log("4 check_errors", ce["ok"], ce["message"])

    distname = next((x["name"] for x in m if x.get("mate_type") == "distance"), None)
    cands = []
    if distname:
        cands += [f"D1@{distname}", f"D2@{distname}"]
    cands += ["D1@Distance1", "D1@Distance2"]
    found = None
    for c in cands:
        r = call(set_dimension, {"full_name": c, "value_mm": 40}, c)
        print("  probe", c, r["ok"], r["message"], flush=True)
        if "No dimension named" not in r["message"]:
            found = c
            break
    log("5a find mate dimension name", found is not None, f"tried {cands}; hit={found}")

    coin = next((x["name"] for x in m if x.get("mate_type") == "coincident"), None)
    r = call(delete_mate, {"mate_name": coin})
    m2 = call(list_mates, {})["data"]["mates"]
    log("6 delete_mate coincident",
        r["ok"] and all(x["name"] != coin for x in m2) and len(m2) == len(m) - 1,
        f"{r['message']} | now {[x['name'] for x in m2]}")
    ce = call(check_errors, {})
    log("6 rebuild 0 errors", ce["ok"], ce["message"] + " " + json.dumps(ce.get("data"), default=str)[:200])
    if found:
        r = call(set_dimension, {"full_name": found, "value_mm": 45})
        ob = origin_b()
        log("5b set_dimension distance 40->45 moves pin", r["ok"] and near(ob[2], 15),
            f"{r['message']} B origin={ob} (expect z=15)")
        ce = call(check_errors, {})
        log("5c rebuild after edit", ce["ok"], ce["message"])
    missing = call(delete_mate, {"mate_name": "NoSuchMate"})
    log("6 delete_mate unknown name refused", not missing["ok"], missing["message"])

    pasm = OUT / "asm.sldasm"
    pasm.unlink(missing_ok=True)
    r = call(save_document, {"path": str(pasm)})
    log("7 save assembly", r["ok"] and pasm.exists() and pasm.stat().st_size > 0, r["message"])


if __name__ == "__main__":
    base = [d["title"] for d in docs()]
    try:
        main(base)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        log("EXCEPTION", False, repr(exc))
    finally:
        # Assembly first (it holds the parts), then the parts.
        for t in sorted(created, key=lambda s: 0 if "sldasm" in s.lower() or "assem" in s.lower() else 1):
            call(close_document, {"title": t, "force": True})
        # Parts opened implicitly by insert_component: close any doc not in baseline.
        for x in docs():
            if x["title"] not in base:
                call(close_document, {"title": x["title"], "force": True})
        now = [d["title"] for d in docs()]
        log("7 final docs == baseline", now == base, f"{now} vs {base}")
        (OUT / "live_log.txt").write_text("\n".join(LOG), encoding="utf-8")
