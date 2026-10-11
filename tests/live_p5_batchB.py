"""LIVE Phase 5 Batch B verification (SW 2017 must be running, launched by the user).

Run:  SW_MCP_OUTPUT_ROOT=<repo>/sandbox python tests/live_p5_batchB.py [docdata|geo1|geo2|holes ...]
Calls tool handlers in-process; writes under sandbox/phase5\batchB\; closes only docs it created.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import solidworks_mcp.server  # noqa: E402,F401  (registers every tool)
from solidworks_mcp.sw_core import active_document  # noqa: E402
from solidworks_mcp.sw_docdata import *  # noqa: E402,F401,F403
from solidworks_mcp.sw_body import *  # noqa: E402,F401,F403
from solidworks_mcp.sw_feature import (  # noqa: E402
    boss_extrude, chamfer_vertex, cosmetic_thread, cut_extrude, delete_feature, fillet_variant,
    hole_wizard, revolve,
)
from solidworks_mcp.sw_file import (  # noqa: E402
    close_document, create_new_document, list_open_documents, open_document, save_document,
)
from solidworks_mcp.sw_inspect import (  # noqa: E402
    get_bounding_box, get_mass_properties, list_bodies, list_edges, list_faces, list_features,
    list_vertices,
)
from solidworks_mcp.sw_refgeom import create_plane  # noqa: E402
from solidworks_mcp.sw_sketch import (  # noqa: E402
    add_dimension, draw_point, close_sketch, create_sketch, draw_centerline, draw_circle, draw_line,
    draw_rectangle, list_dimensions, list_sketch_segments, set_dimension,
)

OUT = ROOT / "sandbox" / "phase5" / "batchB"
OUT.mkdir(parents=True, exist_ok=True)
LOG: list[str] = []
created: list[str] = []


def log(step: str, ok, detail: str = "", status: str | None = None) -> None:
    st = status or ("PASS" if ok else "FAIL")
    line = f"{st} | {step} | {detail}"
    LOG.append(line)
    print(line, flush=True)


def call(fn, args=None, ctx=""):
    try:
        r = fn(args or {})
    except Exception as exc:  # noqa: BLE001
        r = {"ok": False, "message": f"EXC {exc!r}", "data": {}}
    if not r.get("ok"):
        print(f"  (call {fn.__name__} {ctx} -> not ok: {r.get('message')} "
              f"{json.dumps(r.get('data'), default=str)[:300]})", flush=True)
    return r


def D(r):
    return r.get("data") or {}


def docs():
    return D(call(list_open_documents))["documents"]


def near(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


def vol():
    return D(call(get_mass_properties)).get("volume_mm3")


def bbox():
    d = D(call(get_bounding_box))
    return d.get("min_mm"), d.get("max_mm")


def size():
    lo, hi = bbox()
    return [round(h - l, 4) for l, h in zip(lo, hi)]


def nbodies():
    return len(D(call(list_bodies))["bodies"])


def newdoc(kind="part"):
    before = {d["title"] for d in docs()}
    call(create_new_document, {"kind": kind})
    for d in docs():
        if d["title"] not in before:
            created.append(d["title"])
            return d["title"]


def sketch_rect(plane, x1, y1, x2, y2, name, plane_name=None):
    a = {"name": name}
    a.update({"plane_name": plane_name} if plane_name else {"plane": plane})
    call(create_sketch, a)
    call(draw_rectangle, {"x1_mm": x1, "y1_mm": y1, "x2_mm": x2, "y2_mm": y2})
    call(close_sketch)


def sketch_circle(plane, x, y, r, name, plane_name=None):
    a = {"name": name}
    a.update({"plane_name": plane_name} if plane_name else {"plane": plane})
    call(create_sketch, a)
    call(draw_circle, {"x_mm": x, "y_mm": y, "radius_mm": r})
    call(close_sketch)


def box(x1, y1, x2, y2, depth, sk, name, plane="front"):
    sketch_rect(plane, x1, y1, x2, y2, sk)
    return call(boss_extrude, {"sketch_name": sk, "depth_mm": depth, "name": name})


def faces():
    return D(call(list_faces))["faces"]


def edges():
    return D(call(list_edges))["edges"]


def verts():
    return D(call(list_vertices))["vertices"]


def pick_face(normal, coord=None, axis=2, tol=0.6, fs=None):
    for f in fs or faces():
        n = f.get("normal")
        if f.get("surface_type") != "plane" or not n:
            continue
        if abs(sum(a * b for a, b in zip(n, normal)) - 1) > 0.02:
            continue
        if coord is not None and abs(f["point_mm"][axis] - coord) > tol:
            continue
        return f
    return None


def feats():
    return D(call(list_features))["features"]


def delf(*names):
    return call(delete_feature, {"feature_names": list(names)})


def feat_types():
    return [(f.get("name"), f.get("type")) for f in feats()]


def stage_probe():
    newdoc("part")
    box(-20, -10, 20, 10, 10, "S1", "Bx")
    print(json.dumps(faces()[:2], default=str))
    print(json.dumps(edges()[:2], default=str))
    print(json.dumps(verts()[:2], default=str))
    print(json.dumps(feats(), default=str)[:1200])
    print(json.dumps(D(call(list_bodies)), default=str))
    print(json.dumps(D(call(get_bounding_box)), default=str))
    print(json.dumps(D(call(list_dimensions)), default=str))
    print(json.dumps(D(call(list_sketch_segments, {"sketch_name": "S1"})), default=str)[:800])


def dimname(owner, base="D1"):
    for d in D(call(list_dimensions)).get("dimensions", []):
        if d["owner"] == owner and d["name"] == base:
            return d["full_name"]


def cfgnames():
    return [c["name"] for c in D(call(list_configurations))["configurations"]]


def cfg_mass(names=None):
    r = call(get_configuration_mass_properties, {"configurations": names} if names else {})
    return D(r)


def stage_docdata():
    DOC = OUT / "docdata"
    DOC.mkdir(exist_ok=True)
    title = newdoc("part")
    box(-20, -10, 20, 10, 10, "S1", "Bx")
    sketch_circle("front", 0, 0, 3, "Sh")
    r = call(cut_extrude, {"sketch_name": "Sh", "end_condition": "through_all", "name": "Ct"})
    vfull = 8000 - math.pi * 9 * 10
    log("D0 base part", r["ok"] and near(vol(), vfull, 0.5), f"vol={vol()}")
    r = call(list_configurations)
    print("  list_configurations:", json.dumps(D(r), default=str)[:400])
    r1 = call(add_configuration, {"name": "Short"})
    r2 = call(add_configuration, {"name": "Kid", "parent": "Default"})
    lc = D(call(list_configurations))
    names = [c["name"] for c in lc["configurations"]]
    kid = next((c for c in lc["configurations"] if c["name"] == "Kid"), {})
    log("D1 add_configuration Short + derived Kid; active stays Default",
        r1["ok"] and r2["ok"] and sorted(names) == ["Default", "Kid", "Short"] and kid.get("derived") and kid.get("parent") == "Default"
        and lc.get("active") == "Default", f"{json.dumps(lc, default=str)[:500]}")
    r3 = call(add_configuration, {"name": "Act", "activate": True})
    lc = D(call(list_configurations))
    log("D1b add_configuration activate=true makes it active", r3["ok"] and lc.get("active") == "Act", f"active={lc.get('active')}")
    call(activate_configuration, {"name": "Default"})
    rr = call(rename_configuration, {"name": "Act", "new_name": "Act2"})
    lc = D(call(list_configurations))
    log("D3 rename_configuration keeps active", rr["ok"] and "Act2" in cfgnames() and "Act" not in cfgnames() and lc.get("active") == "Default", f"{cfgnames()} active={lc.get('active')}")
    call(activate_configuration, {"name": "Act2"})
    rd = call(delete_configuration, {"name": "Act2"})
    lc = D(call(list_configurations))
    log("D2a delete active config switches + deletes", rd["ok"] and "Act2" not in cfgnames() and lc.get("active") in cfgnames(), f"{rd['message']} names={cfgnames()} active={lc.get('active')}")
    call(activate_configuration, {"name": "Default"})
    rs = call(set_config_feature_suppression, {"feature_names": ["Ct"], "suppressed": True, "scope": "specified", "configurations": ["Short"]})
    print("  suppress result:", json.dumps(D(rs), default=str)[:500])
    mp = cfg_mass()
    print("  cfg mass:", json.dumps(mp, default=str)[:800])
    mass = mp.get("configurations", {})
    vs = lambda n: mass.get(n, {}).get("volume_mm3")
    log("D4a suppress Ct in Short only: Short=8000, Default cut", rs["ok"] and near(vs("Short"), 8000, 1) and near(vs("Default"), vfull, 1), f"Short={vs('Short')} Default={vs('Default')} Kid={vs('Kid')}")
    call(activate_configuration, {"name": "Short"})
    log("D4b Short active measured via get_mass_properties", near(vol(), 8000, 1), f"vol={vol()}")
    call(activate_configuration, {"name": "Default"})
    ra = call(set_config_feature_suppression, {"feature_names": ["Ct"], "suppressed": True, "scope": "all"})
    mass = cfg_mass().get("configurations", {})
    log("D4c suppress scope=all", ra["ok"] and all(near(mass[n]["volume_mm3"], 8000, 1) for n in mass), f"{ {n: mass[n]['volume_mm3'] for n in mass} }")
    rt = call(set_config_feature_suppression, {"feature_names": ["Ct"], "suppressed": False, "scope": "this"})
    mass = cfg_mass().get("configurations", {})
    log("D4d unsuppress scope=this (Default only)", rt["ok"] and near(mass["Default"]["volume_mm3"], vfull, 1) and near(mass["Short"]["volume_mm3"], 8000, 1), f"{ {n: mass[n]['volume_mm3'] for n in mass} }")
    fn = dimname("Bx")
    rdim = call(set_dimension_config, {"full_name": fn, "value_mm": 20, "scope": "specified", "configurations": ["Short"]})
    call(activate_configuration, {"name": "Short"})
    zs = size()[2]
    call(activate_configuration, {"name": "Default"})
    zd = size()[2]
    log("D5a set_dimension_config specified=[Short]", rdim["ok"] and near(zs, 20) and near(zd, 10), f"Short z={zs} Default z={zd} fn={fn}")
    rdim = call(set_dimension_config, {"full_name": fn, "value_mm": 12, "scope": "this"})
    call(activate_configuration, {"name": "Short"})
    zs = size()[2]
    call(activate_configuration, {"name": "Default"})
    zd = size()[2]
    log("D5b set_dimension_config this", rdim["ok"] and near(zs, 20) and near(zd, 12), f"Short z={zs} Default z={zd}")
    rdim = call(set_dimension_config, {"full_name": fn, "value_mm": 15, "scope": "all"})
    res = []
    for c in cfgnames():
        call(activate_configuration, {"name": c})
        res.append((c, size()[2], active_document()[1].Parameter(fn).SystemValue))
    call(activate_configuration, {"name": "Default"})
    print("  D5c set result:", rdim["message"], D(rdim))
    res = [(c, z) for c, z, _ in res] if all(near(z, 15) for c, z, _ in res) else res
    log("D5c set_dimension_config all", rdim["ok"] and all(near(t[1], 15) for t in res), f"{res}")
    call(set_dimension_config, {"full_name": fn, "value_mm": 10, "scope": "all"})
    gm = D(call(get_mass_properties))
    cm = cfg_mass().get("configurations", {})
    log("D8 cfg mass vs get_mass_properties; active restored", near(cm["Default"]["volume_mm3"], gm["volume_mm3"], 0.5) and D(call(list_configurations)).get("active") == "Default",
        f"cfg={cm['Default']} gm={gm.get('mass_g')}")
    re_ = call(add_equation, {"global_variable": "w", "expression": "6"})
    le = D(call(list_equations))
    print("  list_equations:", json.dumps(le, default=str)[:600])
    re2 = call(add_equation, {"dimension_name": fn, "expression": '"w" * 2'})
    z12 = size()[2]
    le = D(call(list_equations))
    print("  list_equations 2:", json.dumps(le, default=str)[:900])
    ed = call(edit_equation, {"name": "w", "expression": "8"})
    z8 = size()[2]
    log("D6a global var w drives dimension (w=6 -> 12, w=8 -> 16)", near(z12, 12) and near(z8, 16), f"z(w=6)={z12} z(w=8)={z8} edit={ed['message']}")
    bad = call(add_equation, {"equation": '"zz" = "nonexistent" +'})
    le = D(call(list_equations))
    log("D6b bad equation no hang; status reported", True, f"ok={bad['ok']} msg={bad['message']} data={json.dumps(D(bad), default=str)[:300]}")
    for row in reversed(le.get("equations", [])):
        if "nonexistent" in str(row.get("equation", "")):
            call(delete_equation, {"index": row["index"]})
    refused = call(delete_equation, {"name": "w"})
    log("D6c delete_equation refuses a referenced global variable", not refused["ok"] and "still used" in refused["message"], refused["message"][:160])
    d1 = call(delete_equation, {"name": fn})
    de = call(delete_equation, {"name": "w"})
    le2 = D(call(list_equations))
    log("D6d delete_equation dimension eq then variable", d1["ok"] and de["ok"] and le2.get("equations") == [], json.dumps(le2, default=str)[:300])
    c1 = call(set_custom_property, {"name": "Desc", "value": "Plate", "type": "text"})
    c2 = call(set_custom_property, {"name": "Linked", "value": '$PRP:"Desc"', "type": "text"})
    c3 = call(set_custom_property, {"name": "Weight", "value": "12.5", "type": "number", "configuration": "Short"})
    c4 = call(set_custom_property, {"name": "Rev", "value": "A", "type": "text", "configuration": "Default"})
    c5 = call(set_custom_property, {"name": "Date", "value": "2026-03-04", "type": "date"})
    c6 = call(set_custom_property, {"name": "Chk", "value": "yes", "type": "yesno"})
    c7 = call(set_custom_property, {"name": "Dbl", "value": "3.25", "type": "double"})
    lp = D(call(list_custom_properties))
    lps = D(call(list_custom_properties, {"configuration": "Short"}))
    print("  props file:", json.dumps(lp, default=str)[:900])
    print("  props Short:", json.dumps(lps, default=str)[:500])
    save = OUT / "docdata" / "props.sldprt"
    if save.exists():
        save.unlink()
    call(save_document, {"path": str(save)})
    call(close_document, {"title": title, "force": True})
    created.clear()
    call(open_document, {"path": str(save)})
    created.append([d["title"] for d in docs()][-1])
    lp2 = D(call(list_custom_properties))
    lps2 = D(call(list_custom_properties, {"configuration": "Short"}))
    print("  props file after reopen:", json.dumps(lp2, default=str)[:900])
    print("  props Short after reopen:", json.dumps(lps2, default=str)[:500])

    def prop(d, n):
        for p in d.get("properties", []):
            if p.get("name") == n:
                return p
    p_l = prop(lp2, "Linked") or {}
    log("D7a file-level text + $PRP link resolved after save+reopen", all(x["ok"] for x in (c1, c2)) and p_l.get("resolved_value") == "Plate" and p_l.get("value") != p_l.get("resolved_value"), f"{p_l}")
    p_w = prop(lps2, "Weight") or {}
    log("D7b config-specific number after reopen", c3["ok"] and "12.5" in str(p_w.get("resolved_value")), f"{p_w}")
    p_d = prop(lp2, "Date") or {}
    p_c = prop(lp2, "Chk") or {}
    p_b = prop(lp2, "Dbl") or {}
    log("D7c date/yesno/double after reopen", all(x["ok"] for x in (c5, c6, c7)) and bool(p_d) and bool(p_c) and bool(p_b), f"date={p_d} yesno={p_c} dbl={p_b}")
    dd = call(delete_custom_property, {"name": "Rev", "configuration": "Default"})
    dd2 = call(delete_custom_property, {"name": "NoSuchProp"})
    lp3 = D(call(list_custom_properties, {"configuration": "Default"}))
    log("D7d delete_custom_property present ok, absent reported", dd["ok"] and not prop(lp3, "Rev") and not dd2["ok"], f"{dd['message']} / {dd2['message']}")
    mo = call(set_mass_override, {"override_mass_g": 123.4})
    log("D9 set_mass_override", False, f"{mo['message'][:200]}", status="FENCED")
    vpre = vol()
    u0 = D(call(get_document_units))
    print("  units0:", json.dumps(u0, default=str)[:500])
    su = call(set_document_units, {"unit_system": "ips"})
    u1 = D(call(get_document_units))
    su2 = call(set_document_units, {"unit_system": "custom", "length_unit": "in", "length_decimals": 4, "angle_unit": "radians", "angle_decimals": 3, "mass_unit": "lb"})
    u2 = D(call(get_document_units))
    print("  units1:", json.dumps(u1, default=str)[:400])
    print("  units2:", json.dumps(u2, default=str)[:500])
    su3 = call(set_document_units, {"unit_system": "mmgs"})
    u3 = D(call(get_document_units))
    log("D10 set/get units ips -> custom(in,4dp,rad,lb) -> mmgs", su["ok"] and su2["ok"] and su3["ok"],
        f"u1={json.dumps(u1)[:200]} u2={json.dumps(u2)[:250]} u3={json.dumps(u3)[:200]}")
    log("D10b volume measure unaffected by unit change", near(vol(), vpre, 0.5), f"vol={vol()} pre={vpre}")
    for c in cfgnames():
        if c != "Default":
            call(activate_configuration, {"name": "Default"})
            call(delete_configuration, {"name": c})
    rl = call(delete_configuration, {"name": "Default"})
    log("D2b delete last configuration refused", (not rl["ok"]) and cfgnames() == ["Default"], f"{rl['message']} names={cfgnames()}")


def fobj(name):
    return active_document()[1].FeatureByName(name)


def rp_xyz(name):
    from solidworks_mcp.sw_core import value
    rp = value(fobj(name), "GetSpecificFeature2")
    pts = value(rp, "GetRefPoint")
    arr = pts.ArrayData if hasattr(pts, "ArrayData") else pts
    return [round(float(x) * 1000, 3) for x in arr]


def fname(r):
    return D(r).get("feature")


def vclose(a, b, tol=0.05):
    return a is not None and len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def find_edge(pred):
    for e in edges():
        if pred(e):
            return e


def find_vertex(pt, tol=0.05):
    for v in verts():
        if vclose(v["point_mm"], pt, tol):
            return v


def stage_geo1():
    # ============ Part A: reference points, vertex chamfer, dome
    newdoc("part")
    box(-20, -10, 20, 10, 10, "S1", "Bx")
    top = pick_face([0, 0, 1], 10)
    r = call(create_reference_point, {"method": "face_center", "selection": {"faces": [top["index"]]}, "name": "RPf"})
    log("G1a ref point face_center", r["ok"] and vclose(rp_xyz("RPf"), [0, 0, 10]), f"xyz={rp_xyz('RPf') if r['ok'] else r['message']}")
    call(create_sketch, {"face_index": top["index"], "name": "SB"})
    call(draw_circle, {"x_mm": 10, "y_mm": 0, "radius_mm": 5})
    call(close_sketch)
    r = call(boss_extrude, {"sketch_name": "SB", "depth_mm": 5, "name": "Bs"})
    v0 = vol()
    log("G0 boss on top face", r["ok"] and near(v0, 8000 + math.pi * 25 * 5, 0.5), f"vol={v0}")
    ce = find_edge(lambda e: e["curve_type"] == "circle" and abs(e["point_mm"][2] - 15) < 0.1)
    r = call(create_reference_point, {"method": "arc_center", "selection": {"edges": [ce["index"]]}, "name": "RPa"})
    log("G1b ref point arc_center", r["ok"] and vclose(rp_xyz("RPa"), [10, 0, 15]), f"xyz={rp_xyz('RPa') if r['ok'] else r['message']}")
    le = find_edge(lambda e: e["curve_type"] == "line" and abs(e["start_mm"][2] - 10) < 0.01 and abs(e["end_mm"][2] - 10) < 0.01
                   and abs(e["start_mm"][1] + 10) < 0.01 and abs(e["end_mm"][1] + 10) < 0.01)
    s0, e0 = le["start_mm"], le["end_mm"]
    L = math.dist(s0, e0)
    u = [(b - a) / L for a, b in zip(s0, e0)]
    at = lambda d: [round(a + d * c, 3) for a, c in zip(s0, u)]
    atr = lambda d: [round(b - d * c, 3) for b, c in zip(e0, u)]
    r = call(create_reference_point, {"method": "along_curve", "along": "distance", "distance_mm": 3, "selection": {"edges": [le["index"]]}, "name": "RPd"})
    p = rp_xyz("RPd") if r["ok"] else None
    log("G1c ref point along_curve distance 3", r["ok"] and (vclose(p, at(3)) or vclose(p, atr(3))), f"xyz={p} from_start={at(3)} from_end={atr(3)}")
    r = call(create_reference_point, {"method": "along_curve", "along": "percentage", "percent": 25, "selection": {"edges": [le["index"]]}, "name": "RPp"})
    p = rp_xyz("RPp") if r["ok"] else None
    log("G1d ref point along_curve percentage 25 (=25%)", r["ok"] and (vclose(p, at(10)) or vclose(p, atr(10))), f"xyz={p} expect {at(10)} or {atr(10)}")
    n0 = len(feats())
    r = call(create_reference_point, {"method": "along_curve", "along": "evenly", "count": 4, "selection": {"edges": [le["index"]]}, "name": "RPe"})
    try:
        p = rp_xyz("RPe")
    except Exception as exc:  # noqa: BLE001
        p = repr(exc)
    log("G1e ref point along_curve evenly 4", r["ok"], f"feature created, first/only point={p} (count of points not exposed by IRefPoint)")
    el = find_edge(lambda e: e["curve_type"] == "line" and abs(e["start_mm"][2] - 10) < 0.01 and abs(e["end_mm"][2] - 10) < 0.01
                   and abs(e["start_mm"][0] + 20) < 0.01 and abs(e["end_mm"][0] + 20) < 0.01)
    r = call(create_reference_point, {"method": "intersection", "selection": {"edges": [le["index"], el["index"]]}, "name": "RPi"})
    log("G1f ref point intersection of two edges", r["ok"] and vclose(rp_xyz("RPi"), [-20, -10, 10]), f"xyz={rp_xyz('RPi') if r['ok'] else r['message']}")
    call(create_sketch, {"face_index": top["index"], "name": "SP"})
    call(draw_point, {"x_mm": -7, "y_mm": 3})
    call(close_sketch)
    r = call(create_reference_point, {"method": "sketch_point", "selection": {"sketch_points": [0], "sketch_name": "SP"}, "name": "RPs"})
    log("G1g ref point sketch_point", r["ok"] and vclose(rp_xyz("RPs"), [-7, 3, 10]), f"xyz={rp_xyz('RPs') if r['ok'] else r['message']}")
    # ---- chamfer_vertex
    v1 = vol()
    vt = find_vertex([-20, -10, 0])
    r = call(chamfer_vertex, {"selection": {"vertices": [vt["index"]]}, "distance_mm": 2, "name": "CV1"})
    dv = v1 - vol()
    log("G4a chamfer_vertex equal d=2 (removes d^3/6=1.3333)", r["ok"] and near(dv, 8 / 6, 0.01), f"removed={dv:.4f}")
    v2 = vol()
    vt = find_vertex([20, -10, 0])
    r = call(chamfer_vertex, {"selection": {"vertices": [vt["index"]]}, "distance_mm": 1, "distance2_mm": 2, "distance3_mm": 3, "name": "CV2"})
    dv = v2 - vol()
    log("G4b chamfer_vertex 1/2/3 (removes 1.0)", r["ok"] and near(dv, 1.0, 0.01), f"removed={dv:.4f}")
    # ---- dome
    topc = pick_face([0, 0, 1], 15)
    v3 = vol()
    r = call(create_dome, {"selection": {"faces": [topc["index"]]}, "height_mm": 3, "name": "Dm"})
    cap = math.pi * 3 * (3 * 25 + 9) / 6
    log("G3a dome spherical h=3 (+131.95)", r["ok"] and near(vol() - v3, cap, 0.3), f"dV={vol() - v3:.3f} exp={cap:.3f}")
    delf("Dm")
    topc = pick_face([0, 0, 1], 15)
    r = call(create_dome, {"selection": {"faces": [topc["index"]]}, "height_mm": 3, "elliptical": True, "name": "Dm"})
    ell = 2 / 3 * math.pi * 25 * 3
    log("G3b dome elliptical h=3 (+157.08)", r["ok"] and near(vol() - v3, ell, 0.3), f"dV={vol() - v3:.3f} exp={ell:.3f}")
    delf("Dm")
    topc = pick_face([0, 0, 1], 15)
    r = call(create_dome, {"selection": {"faces": [topc["index"]]}, "height_mm": 3, "reverse": True, "name": "Dm"})
    log("G3c dome reverse (concave, -131.95)", r["ok"] and near(vol() - v3, -cap, 0.3), f"dV={vol() - v3:.3f}")
    delf("Dm")


def stage_geo1b():
    # ============ Part B: multi-body ops
    newdoc("part")
    sketch_rect("front", -20, -10, 20, 10, "S1")
    call(boss_extrude, {"sketch_name": "S1", "depth_mm": 10, "merge": False, "name": "B1"})
    sketch_rect("front", 0, -5, 30, 5, "S2")
    call(boss_extrude, {"sketch_name": "S2", "depth_mm": 15, "merge": False, "name": "B2"})
    nb = nbodies()
    v = vol()
    log("G2-0 two overlapping bodies", nb == 2 and near(v, 8000 + 4500, 1), f"bodies={nb} vol={v}")
    rc = call(combine_bodies, {"operation": "add", "main_body": 0, "tool_bodies": [1], "name": "Cmb"})
    log("G2 combine_bodies add/subtract/common", False, f"InsertCombineFeature returns Nothing in every argument form (see probe); tool fenced. msg={rc['message'][:80]}", status="FENCED")
    def bidx(name):
        return next(b["index"] for b in D(call(list_bodies))["bodies"] if b["name"] == name)

    def binfo(name):
        # a move/copy renames the body, so B2 is recognised by its (rotation-proof) sorted size
        want = [10, 15, 30]
        return next(b for b in D(call(list_bodies))["bodies"]
                    if sorted(round(h - l, 2) for l, h in zip(b["min_mm"], b["max_mm"])) == want)
    i2 = bidx("B2")
    r = call(delete_body, {"bodies": [i2], "name": "Db"})
    log("G3d delete_body keep=false (delete B2, keep B1 8000)", r["ok"] and nbodies() == 1 and near(vol(), 8000, 1), f"bodies={nbodies()} vol={vol()}")
    delf("Db")
    i2 = bidx("B2")
    r = call(delete_body, {"bodies": [i2], "keep": True, "name": "Db"})
    log("G3e delete_body keep=true (keep only B2 4500)", r["ok"] and nbodies() == 1 and near(vol(), 4500, 1), f"bodies={nbodies()} vol={vol()}")
    delf("Db")
    b2 = binfo("B2")
    r = call(move_copy_body, {"bodies": [bidx(b2["name"])], "dx_mm": 50, "name": "Mv"})
    b2n = binfo("B2")
    log("G3f move_copy_body translate dx=50", r["ok"] and near(b2n["min_mm"][0] - b2["min_mm"][0], 50, 0.05), f"min x {b2['min_mm'][0]} -> {b2n['min_mm'][0]}")
    delf("Mv")
    r = call(move_copy_body, {"bodies": [bidx(binfo("B2")["name"])], "rz_deg": 90, "name": "Mv"})
    b2n = binfo("B2")
    log("G3g move_copy_body rotate rz=90 about origin (B2 -> x -5..5, y 0..30)", r["ok"] and vclose(b2n["min_mm"], [-5, 0, 0], 0.1) and vclose(b2n["max_mm"], [5, 30, 15], 0.1), f"{b2n['min_mm']}{b2n['max_mm']}")
    delf("Mv")
    r = call(move_copy_body, {"bodies": [bidx(binfo("B2")["name"])], "dz_mm": 30, "copy": True, "count": 3, "name": "Mc"})
    log("G3h move_copy_body copy count 3 (+3 bodies)", r["ok"] and nbodies() == 5, f"bodies={nbodies()} vol={vol()}")
    delf("Mc")

    # ---- scale_part on a clean part
    newdoc("part")
    box(-20, -10, 20, 10, 10, "S1", "Bx")
    lo0, hi0 = bbox()
    r = call(scale_part, {"factor": 2, "about": "origin", "name": "Sc"})
    lo, hi = bbox()
    log("G3i scale_part uniform 2 about origin (vol x8, bbox x2)", r["ok"] and near(vol(), 64000, 2) and vclose(hi, [h * 2 for h in hi0], 0.1), f"vol={vol()} bbox={lo}{hi}")
    delf("Sc")
    r = call(scale_part, {"factor": 2, "about": "centroid", "name": "Sc"})
    lo, hi = bbox()
    cen = [(a + b) / 2 for a, b in zip(lo, hi)]
    cen0 = [(a + b) / 2 for a, b in zip(lo0, hi0)]
    log("G3j scale_part uniform 2 about centroid (centre fixed)", r["ok"] and near(vol(), 64000, 2) and vclose(cen, cen0, 0.1), f"vol={vol()} centre={cen} was {cen0}")
    delf("Sc")
    r = call(scale_part, {"x_factor": 1, "y_factor": 2, "z_factor": 3, "about": "origin", "name": "Sc"})
    log("G3k scale_part non-uniform 1/2/3 (vol x6, size 40/40/30)", r["ok"] and near(vol(), 48000, 2) and vclose(size(), [40, 40, 30], 0.1), f"vol={vol()} size={size()}")
    delf("Sc")

    # ---- mirror_body
    newdoc("part")
    box(0, 0, 10, 10, 10, "S1", "Bx")
    r = call(mirror_body, {"bodies": [0], "plane_selection": {"planes": ["right"]}, "merge": False, "name": "Mr"})
    log("G3l mirror_body merge=false (2 bodies, vol 2000)", r["ok"] and nbodies() == 2 and near(vol(), 2000, 1), f"bodies={nbodies()} vol={vol()} size={size()}")
    delf("Mr")
    r = call(mirror_body, {"bodies": [0], "plane_selection": {"planes": ["right"]}, "merge": True, "name": "Mr"})
    log("G3m mirror_body merge=true (1 body, vol 2000, x -10..10)", r["ok"] and nbodies() == 1 and near(vol(), 2000, 1) and near(size()[0], 20, 0.05), f"bodies={nbodies()} vol={vol()} size={size()}")

    # ---- helix (read definition) ----
    newdoc("part")
    sketch_circle("top", 0, 0, 10, "HC")
    app, doc = active_document()
    from solidworks_mcp.sw_core import value

    def hdef(name):
        d = value(fobj(name), "GetDefinition")
        return {k: value(d, k) for k in ("Height", "Pitch", "Revolution", "DefinedBy", "Clockwise", "Taper", "TaperAngle", "StartingAngle", "TaperOutward", "ReverseDirection")}
    cases = [
        ("G5a helix height_pitch 30/5", {"defined_by": "height_pitch", "height_mm": 30, "pitch_mm": 5}, lambda h: near(h["Height"], 0.03, 1e-6) and near(h["Pitch"], 0.005, 1e-6) and near(h["Revolution"], 6, 1e-6)),
        ("G5b helix height_revolutions 30/4", {"defined_by": "height_revolutions", "height_mm": 30, "revolutions": 4}, lambda h: near(h["Height"], 0.03, 1e-6) and near(h["Revolution"], 4, 1e-6) and near(h["Pitch"], 0.0075, 1e-6)),
        ("G5c helix pitch_revolutions 6/5", {"defined_by": "pitch_revolutions", "pitch_mm": 6, "revolutions": 5}, lambda h: near(h["Pitch"], 0.006, 1e-6) and near(h["Revolution"], 5, 1e-6) and near(h["Height"], 0.03, 1e-6)),
        ("G5d helix tapered 5deg", {"defined_by": "height_pitch", "height_mm": 30, "pitch_mm": 5, "taper_deg": 5}, lambda h: bool(h["Taper"]) and near(h["TaperAngle"], math.radians(5), 1e-6)),
        ("G5e helix ccw start 90", {"defined_by": "height_pitch", "height_mm": 30, "pitch_mm": 5, "clockwise": False, "start_angle_deg": 90}, lambda h: h["Clockwise"] is False and near(h["StartingAngle"], math.pi / 2, 1e-6)),
    ]
    for label, a, chk in cases:
        r = call(create_helix, dict(a, sketch="HC", name="Hx"))
        h = hdef("Hx") if r["ok"] else {}
        log(label, r["ok"] and chk(h), f"{h}")
        delf("Hx")
    r = call(create_helix, {"sketch": "HC", "defined_by": "spiral", "pitch_mm": 3, "revolutions": 4, "name": "Hx"})
    h = hdef("Hx") if r["ok"] else {}
    log("G5f spiral pitch 3 rev 4", r["ok"] and near(h.get("Revolution"), 4, 1e-6) and near(h.get("Pitch"), 0.003, 1e-6), f"{h}")

def edef(name, keys):
    from solidworks_mcp.sw_core import value
    d = value(fobj(name), "GetDefinition")
    out = {}
    for k in keys:
        try:
            out[k] = value(d, k)
        except Exception as exc:  # noqa: BLE001
            out[k] = f"ERR {type(exc).__name__}"
    return out


def hole_keys():
    return ("Type", "Diameter", "Depth", "CounterBoreDiameter", "CounterBoreDepth", "CounterSinkDiameter", "CounterSinkAngle",
            "TapDrillDiameter", "TapDrillDepth", "ThreadDiameter", "ThreadDepth", "ThreadClass", "Standard", "NearCounterSinkDiameter")


def subfeats(name):
    from solidworks_mcp.sw_core import value
    out = []
    f = value(fobj(name), "GetFirstSubFeature")
    while f is not None:
        out.append((str(f.Name), str(f.GetTypeName2)))
        f = value(f, "GetNextSubFeature")
    return out


def hole_part():
    newdoc("part")
    box(-30, -20, 30, 20, 20, "S1", "Bx")
    return 60 * 40 * 20


def stage_holes():
    base = hole_part()
    cases = [
        ("H1 straight hole d6 through_all (removes 565.49)", {"kind": "hole", "standard": "iso", "fastener": "clearance", "size": "M6", "diameter_mm": 6, "end_condition": "through_all"}, 565.49),
        ("H2 counterbore d6, cb 12x4 through (removes 904.78)", {"kind": "counterbore", "standard": "iso", "fastener": "socket_head", "size": "M6", "diameter_mm": 6, "end_condition": "through_all", "cbore_diameter_mm": 12, "cbore_depth_mm": 4}, 904.78),
        ("H3 countersink d6, cs 12 @90 through (removes 678.58)", {"kind": "countersink", "standard": "iso", "fastener": "flat_head", "size": "M6", "diameter_mm": 6, "end_condition": "through_all", "csink_diameter_mm": 12, "csink_angle_deg": 90}, 678.58),
        ("H4 tapped M6x1 blind 12 thread 10", {"kind": "tap", "standard": "iso", "fastener": "tapped", "size": "M6", "diameter_mm": 6, "end_condition": "blind", "depth_mm": 12, "thread_depth_mm": 10}, None),
    ]
    for label, args, exp in cases:
        v0 = vol()
        top = pick_face([0, 0, 1], 20)
        a = dict(args, points=[{"x_mm": 0, "y_mm": 0, "z_mm": 20}], name="Hw")
        r = call(hole_wizard, a)
        dv = v0 - vol()
        d = edef("Hw", hole_keys()) if r["ok"] else {}
        subs = subfeats("Hw") if r["ok"] else []
        ok = r["ok"] and (exp is None or near(dv, exp, exp * 0.01))
        log(label, ok, f"removed={dv:.3f} exp={exp} def={d} sub={subs} msg={r['message'][:100]}")
        if r["ok"]:
            delf("Hw")
    # multi points
    v0 = vol()
    r = call(hole_wizard, {"kind": "hole", "standard": "iso", "fastener": "clearance", "size": "M6", "diameter_mm": 6, "end_condition": "through_all",
                           "points": [{"x_mm": -15, "y_mm": 0, "z_mm": 20}, {"x_mm": 15, "y_mm": 0, "z_mm": 20}]})
    log("H5 two points -> two holes (removes 2x565.49)", r["ok"] and near(v0 - vol(), 2 * 565.49, 5), f"removed={v0 - vol():.2f} created={D(r).get('created')}")


def stage_cosm():
    hole_part()
    sketch_circle("front", 0, 0, 2.5, "Sh")
    call(cut_extrude, {"sketch_name": "Sh", "end_condition": "through_all", "name": "Ct"})
    ce = find_edge(lambda e: e["curve_type"] == "circle" and abs(e["point_mm"][2] - 20) < 0.1)
    print("circle edge", ce)
    for std in (0,):
        r = call(cosmetic_thread, {"selection": {"edges": [ce["index"]]}, "standard": std, "standard_type": "ISO", "size": "M6x1.0",
                                   "diameter_mm": 6, "end_condition": "blind", "depth_mm": 10, "name": "CTh"})
        types = [t for n, t in feat_types() if n == "CTh" or "Cosmetic" in str(t)]
        log("C1 cosmetic_thread M6x1.0 on bored hole edge", r["ok"] and bool(types), f"{r['message']} types={types} {feat_types()[-3:]}")
        if r["ok"]:
            d = edef("CTh", ("Diameter", "BlindDepth", "EndCondition", "Size", "Standard", "StandardType", "ApplyThread", "Note"))
            log("C1b cosmetic thread definition readback", near(d.get("Diameter"), 0.006, 1e-6) and near(d.get("BlindDepth"), 0.01, 1e-6), f"{d}")


def stage_fillet():
    newdoc("part")
    box(-20, -10, 20, 10, 10, "S1", "Bx")
    v0 = vol()
    le = find_edge(lambda e: e["curve_type"] == "line" and abs(e["start_mm"][2] - 10) < 0.01 and abs(e["end_mm"][2] - 10) < 0.01
                   and abs(e["start_mm"][1] + 10) < 0.01 and abs(e["end_mm"][1] + 10) < 0.01)
    k = 1 - math.pi / 4
    r = call(fillet_variant, {"type": "variable", "selection": {"edges": [le["index"]]}, "radius_mm": 2, "end_radius_mm": 5, "propagate": False, "name": "Fv"})
    dv = v0 - vol()
    exp = k * 40 * (4 + 10 + 25) / 3
    log("F1 variable fillet 2->5 on 40mm edge (~111.6; const2=34.3, const5=214.6)", r["ok"] and abs(dv - exp) < exp * 0.08, f"removed={dv:.2f} exp~{exp:.1f}")
    if r["ok"]:
        delf("Fv")
    r = call(fillet_variant, {"type": "variable", "selection": {"edges": [le["index"]]}, "radius_mm": 5, "end_radius_mm": 2, "propagate": False, "name": "Fv"})
    dv2 = v0 - vol()
    log("F1b variable fillet 5->2 same removal", r["ok"] and abs(dv2 - exp) < exp * 0.08, f"removed={dv2:.2f}")
    if r["ok"]:
        delf("Fv")
    # face fillet: top face (z=10) and front face (y=-10)
    top = pick_face([0, 0, 1], 10)
    front = pick_face([0, -1, 0], -10, axis=1)
    r = call(fillet_variant, {"type": "face", "face_set_1": {"faces": [top["index"]]}, "face_set_2": {"faces": [front["index"]]}, "radius_mm": 3, "name": "Ff"})
    dv = v0 - vol()
    exp = k * 9 * 40
    log("F2 face fillet r3 between top and front (removes 77.25)", r["ok"] and abs(dv - exp) < 1.0, f"removed={dv:.3f} exp={exp:.3f}")
    if r["ok"]:
        delf("Ff")
    # full round on thin bar
    newdoc("part")
    box(-5, -20, 5, 20, 10, "S1", "Bx", plane="front")
    v0 = vol()
    top = pick_face([0, 0, 1], 10)
    left = pick_face([-1, 0, 0], -5, axis=0)
    right = pick_face([1, 0, 0], 5, axis=0)
    r = call(fillet_variant, {"type": "full_round", "side_set_1": {"faces": [left["index"]]}, "center": {"faces": [top["index"]]}, "side_set_2": {"faces": [right["index"]]}, "name": "Fr"})
    dv = v0 - vol()
    exp = (10 * 5 - math.pi * 25 / 2) * 40
    log("F3 full round across 10mm bar (removes 429.2)", r["ok"] and abs(dv - exp) < 3, f"removed={dv:.2f} exp={exp:.2f}")


def stage_cs():
    newdoc("part")
    box(-20, -10, 20, 10, 10, "S1", "Bx")
    vt = find_vertex([-20, -10, 0])
    ex = find_edge(lambda e: e["curve_type"] == "line" and abs(e["start_mm"][1] + 10) < 0.01 and abs(e["end_mm"][1] + 10) < 0.01
                   and abs(e["start_mm"][2]) < 0.01 and abs(e["end_mm"][2]) < 0.01)
    ey = find_edge(lambda e: e["curve_type"] == "line" and abs(e["start_mm"][0] + 20) < 0.01 and abs(e["end_mm"][0] + 20) < 0.01
                   and abs(e["start_mm"][2]) < 0.01 and abs(e["end_mm"][2]) < 0.01)
    r = call(create_coordinate_system, {"origin": {"vertices": [vt["index"]]}, "x_axis": {"edges": [ex["index"]]}, "y_axis": {"edges": [ey["index"]]}, "name": "CS1"})
    t = None
    if r["ok"]:
        d = edef("CS1", ("Transform", "XFlipped", "YFlipped", "ZFlipped"))
        try:
            t = [round(x, 4) for x in d["Transform"].ArrayData]
        except Exception as exc:  # noqa: BLE001
            t = repr(exc)
    ok_t = isinstance(t, list) and vclose(t[9:12], [-0.02, -0.01, 0.0], 1e-4)
    log("CS1 coordinate system origin at vertex, x/y from edges", r["ok"] and ok_t, f"transform={t} msg={r['message']}")
    r = call(create_coordinate_system, {"origin": {"vertices": [vt["index"]]}, "x_axis": {"edges": [ex["index"]]}, "y_axis": {"edges": [ey["index"]]}, "flip_x": True, "name": "CS2"})
    t2 = None
    if r["ok"]:
        d = edef("CS2", ("Transform", "XFlipped"))
        try:
            t2 = [round(x, 4) for x in d["Transform"].ArrayData]
        except Exception as exc:  # noqa: BLE001
            t2 = repr(exc)
    log("CS2 coordinate system flip_x reverses X axis", r["ok"] and isinstance(t2, list) and isinstance(t, list) and t2[0] < 0 < t[0], f"t={t} t2={t2}")


def stage_split():
    newdoc("part")
    box(-20, -10, 20, 10, 10, "S1", "Bx")
    r = call(split_body, {"tool_selection": {"planes": ["right"]}, "name": "Sp"})
    bb = D(call(list_bodies))["bodies"]
    log("SP1 split_body with Right plane (2 bodies, 4000 each)", r["ok"] and len(bb) == 2 and near(vol(), 8000, 1), f"{r['message']} bodies={[(b['min_mm'], b['max_mm']) for b in bb]}")
    if r["ok"]:
        delf("Sp")
    # intersect
    newdoc("part")
    sketch_rect("front", -20, -10, 20, 10, "S1")
    call(boss_extrude, {"sketch_name": "S1", "depth_mm": 10, "merge": False, "name": "B1"})
    sketch_rect("front", 0, -5, 30, 5, "S2")
    call(boss_extrude, {"sketch_name": "S2", "depth_mm": 15, "merge": False, "name": "B2"})
    r = call(intersect_bodies, {"selection": {"bodies": [0, 1]}, "name": "In"})
    bb = D(call(list_bodies))["bodies"]
    log("IN1 intersect_bodies of two overlapping solids", r["ok"] and len(bb) >= 2, f"{r['message']} bodies={len(bb)} vol={vol()} boxes={[(b['min_mm'], b['max_mm']) for b in bb]}")


def stage_wrap():
    newdoc("part")
    sketch_circle("top", 0, 0, 10, "Cy")
    call(boss_extrude, {"sketch_name": "Cy", "depth_mm": 30, "name": "Cyl"})
    v0 = vol()
    lo, hi = bbox()
    print("cyl bbox", lo, hi)
    call(create_plane, {"mode": "offset", "selection": {"planes": ["right"]}, "distance_mm": 10, "name": "Pw"})
    sketch_rect(None, -3, -3, 3, 3, "Sw", plane_name="Pw")
    cyl = next((f for f in faces() if f["surface_type"] == "cylinder"), None)
    print("cyl face", cyl)
    for wt, sign, label in (("emboss", 1, "W1 wrap emboss 1mm (adds ~36)"), ("deboss", -1, "W2 wrap deboss 1mm (removes ~36)")):
        r = call(wrap_sketch, {"sketch": "Sw", "face_selection": {"faces": [cyl["index"]]}, "wrap_type": wt, "thickness_mm": 1, "name": "Wr"})
        dv = vol() - v0
        log(label, r["ok"] and 30 < sign * dv < 40, f"dV={dv:.3f} msg={r['message']}")
        if r["ok"]:
            delf("Wr")

STAGES = {"probe": stage_probe, "docdata": stage_docdata, "geo1": stage_geo1, "geo1b": stage_geo1b, "holes": stage_holes, "cosm": stage_cosm, "fillet": stage_fillet, "cs": stage_cs, "split": stage_split, "wrap": stage_wrap}


def finish(keep_base):
    for x in docs():
        if x["title"] not in keep_base:
            call(close_document, {"title": x["title"], "force": True})


if __name__ == "__main__":
    which = sys.argv[1:] or list(STAGES)
    base = [d["title"] for d in docs()]
    print("BASELINE", base, flush=True)
    try:
        for w in which:
            STAGES[w]()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        log("EXCEPTION", False, repr(exc))
    finally:
        finish(base)
        now = [d["title"] for d in docs()]
        log("final docs == baseline", now == base, f"{now} vs {base}")
        with open(OUT / "live_log.txt", "a", encoding="utf-8") as fh:
            fh.write("\n".join(LOG) + "\n")
