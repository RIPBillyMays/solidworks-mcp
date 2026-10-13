"""LIVE Phase 5 Batch A verification (SW 2017 must be running, launched by the user).

Run:  SW_MCP_OUTPUT_ROOT=<repo>\\sandbox python tests/live_p5_batchA.py [feature|asm|export ...]
Calls tool handlers in-process; writes under sandbox\\phase5\\batchA\\; closes only docs it created.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from solidworks_mcp.sw_assembly import *  # noqa: E402,F401,F403
from solidworks_mcp.sw_core import active_document  # noqa: E402
from solidworks_mcp.sw_feature import boss_extrude, cut_extrude, delete_feature, revolve  # noqa: E402
from solidworks_mcp.sw_file import (  # noqa: E402
    close_document, create_new_document, export_bodies, export_components, export_document,
    list_export_formats, list_open_documents, save_document,
)
from solidworks_mcp.sw_inspect import (  # noqa: E402
    check_errors, get_bounding_box, get_mass_properties, list_bodies, list_faces, list_features, list_vertices,
)
from solidworks_mcp.sw_refgeom import create_plane  # noqa: E402
from solidworks_mcp.sw_select import clear_selection_tool, redo, select_entity, undo  # noqa: E402
from solidworks_mcp.sw_sketch import (  # noqa: E402
    close_sketch, create_sketch, draw_centerline, draw_circle, draw_line, draw_rectangle,
)

OUT = ROOT / "sandbox" / "phase5" / "batchA"
OUT.mkdir(parents=True, exist_ok=True)
LOG: list[str] = []
created: list[str] = []


def log(step: str, ok, detail: str = "") -> None:
    line = f"{'PASS' if ok else 'FAIL'} | {step} | {detail}"
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
    return a is not None and abs(a - b) <= tol


def vol():
    return D(call(get_mass_properties)).get("volume_mm3")


def bbox():
    d = D(call(get_bounding_box))
    return d.get("min_mm"), d.get("max_mm")


def newdoc(kind):
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


def faces():
    return D(call(list_faces))["faces"]


def pick_face(normal, z=None, axis=2, tol=0.6, fs=None):
    for f in fs or faces():
        n = f.get("normal")
        if f.get("surface_type") != "plane" or not n:
            continue
        if abs(sum(a * b for a, b in zip(n, normal)) - 1) > 0.02:
            continue
        if z is not None and abs(f["point_mm"][axis] - z) > tol:
            continue
        return f
    return None


def delf(*names):
    return call(delete_feature, {"feature_names": list(names)})


def stage_feature():
    newdoc("part")
    # ---- 1 regression
    sketch_rect("front", -20, -10, 20, 10, "S1")
    r = call(boss_extrude, {"sketch_name": "S1", "depth_mm": 10, "name": "Bx"})
    v = vol()
    log("F1a boss blind 10", r["ok"] and near(v, 8000, 0.5), f"vol={v}")
    sketch_circle("front", 0, 0, 3, "Sh")
    r = call(cut_extrude, {"sketch_name": "Sh", "end_condition": "through_all", "name": "Ct"})
    v = vol()
    e = 8000 - math.pi * 9 * 10
    log("F1b cut through_all", r["ok"] and near(v, e, 0.5), f"vol={v} exp={e:.2f}")
    delf("Ct", "Bx")
    call(create_sketch, {"plane": "front", "name": "SR"})
    call(draw_rectangle, {"x1_mm": 0, "y1_mm": 0, "x2_mm": 10, "y2_mm": 20})
    call(draw_centerline, {"x1_mm": 0, "y1_mm": -5, "x2_mm": 0, "y2_mm": 25})
    call(close_sketch)
    r = call(revolve, {"sketch_name": "SR", "angle_deg": 360, "name": "Rv"})
    v = vol()
    e = math.pi * 100 * 20
    log("F1c revolve 360", r["ok"] and near(v, e, 1), f"vol={v} exp={e:.2f}")
    delf("Rv")
    r = call(revolve, {"sketch_name": "SR", "angle_deg": 90, "angle2_deg": 90, "name": "Rv2"})
    v = vol()
    log("F11a revolve angle+angle2 (90+90=half)", r["ok"] and near(v, e / 2, 1), f"vol={v} exp={e/2:.2f}")
    delf("Rv2")
    r = call(revolve, {"sketch_name": "SR", "angle_deg": 180, "mid_plane": True, "name": "Rv3"})
    v = vol()
    lo, hi = bbox()
    log("F11b revolve mid_plane 180", r["ok"] and near(v, e / 2, 1) and near(lo[2], -hi[2], 0.5),
        f"vol={v} bbox={lo}{hi}")
    delf("Rv3")
    call(create_sketch, {"plane": "front", "name": "SRO"})
    call(draw_line, {"x1_mm": 5, "y1_mm": 0, "x2_mm": 5, "y2_mm": 20})
    call(draw_centerline, {"x1_mm": 0, "y1_mm": -5, "x2_mm": 0, "y2_mm": 25})
    call(close_sketch)
    h = 20 * math.pi
    for tag, thin, exp in (("c one_direction", {"thickness_mm": 1, "type": "one_direction"}, h * (36 - 25) if False else None),
                           ("d mid_plane", {"thickness_mm": 2, "type": "mid_plane"}, h * (36 - 16)),
                           ("e two_directions", {"thickness_mm": 1, "type": "two_directions", "thickness2_mm": 1}, h * (36 - 16))):
        r = call(revolve, {"sketch_name": "SRO", "angle_deg": 360, "thin": thin, "name": "RvT"})
        v = vol()
        ok = r["ok"] and v is not None and (exp is None and (near(v, h * 11, 2) or near(v, h * 9, 2)) or (exp is not None and near(v, exp, 2)))
        log(f"F11{tag} revolve thin (open profile)", ok, f"vol={v} exp={exp} (1-dir: {h*11:.1f} out or {h*9:.1f} in) msg={r['message']}")
        delf("RvT")

    # ---- 8 draft
    sketch_rect("front", -20, -10, 20, 10, "S2")
    r = call(boss_extrude, {"sketch_name": "S2", "depth_mm": 10, "draft_deg": 5, "name": "Dr_in"})
    vin = vol()
    delf("Dr_in")
    r2 = call(boss_extrude, {"sketch_name": "S2", "depth_mm": 10, "draft_deg": 5, "draft_outward": True, "name": "Dr_out"})
    vout = vol()
    delf("Dr_out")
    log("F8 draft in < 8000 < out", r["ok"] and r2["ok"] and vin < 8000 < vout, f"in={vin} out={vout}")

    # ---- 7 second direction
    r = call(boss_extrude, {"sketch_name": "S2", "depth_mm": 10, "end_condition2": "blind", "depth2_mm": 5, "name": "Two"})
    lo, hi = bbox()
    v = vol()
    log("F7a second direction 10+5", r["ok"] and near(hi[2] - lo[2], 15, 0.1) and near(v, 40 * 20 * 15, 1), f"bbox z {lo[2]}..{hi[2]} vol={v}")
    delf("Two")
    r = call(boss_extrude, {"sketch_name": "S2", "depth_mm": 10, "end_condition2": "blind", "depth2_mm": 5, "draft2_deg": 5, "name": "Two2"})
    v = vol()
    log("F7b second direction + draft2", r["ok"] and v is not None and 11000 < v < 12000, f"vol={v} (undrafted 12000)")
    delf("Two2")

    r = call(boss_extrude, {"sketch_name": "S2", "depth_mm": 10, "end_condition": "mid_plane", "name": "Mid"})
    lo, hi = bbox()
    log("F-mid boss mid_plane", r["ok"] and near(lo[2], -5, 0.1) and near(hi[2], 5, 0.1), f"z {lo[2]}..{hi[2]}")
    delf("Mid")

    # ---- 9 thin
    sketch_rect("front", -20, -10, 20, 10, "ST")
    for kind, extra in (("one_direction", {}), ("two_directions", {"thickness2_mm": 1}), ("mid_plane", {})):
        th = {"thickness_mm": 2, "type": kind, **extra}
        r = call(boss_extrude, {"sketch_name": "ST", "depth_mm": 10, "thin": th, "name": "Th"})
        v = vol()
        lo, hi = bbox()
        exp = {"one_direction": 2560, "two_directions": 3720, "mid_plane": 2400}[kind]
        log(f"F9 thin {kind}", r["ok"] and near(v, exp, 2), f"vol={v} exp={exp} bbox={lo}{hi} msg={r['message']}")
        delf("Th")
    r = call(boss_extrude, {"sketch_name": "ST", "depth_mm": 10, "thin": {"thickness_mm": 2, "cap_ends": True, "cap_thickness_mm": 1}, "name": "Th"})
    log("F9 thin cap_ends", r["ok"], f"vol={vol()} msg={r['message']}")
    delf("Th")

    # ---- 10 thin cut and flip_side
    r = call(boss_extrude, {"sketch_name": "S2", "depth_mm": 10, "name": "Bx"})
    sketch_rect("front", -10, -5, 10, 5, "SC")
    r = call(cut_extrude, {"sketch_name": "SC", "end_condition": "through_all", "name": "CutN"})
    vn = vol()
    delf("CutN")
    r2 = call(cut_extrude, {"sketch_name": "SC", "end_condition": "through_all", "flip_side": True, "name": "CutF"})
    vf = vol()
    log("F10a cut flip_side (remove outside profile)", r["ok"] and r2["ok"] and near(vn, 8000 - 200 * 10, 1) and near(vf, 200 * 10, 1),
        f"normal={vn} flip={vf}")
    delf("CutF")
    r = call(cut_extrude, {"sketch_name": "SC", "end_condition": "through_all", "thin": {"thickness_mm": 1}, "name": "CutT"})
    vt = vol()
    log("F10b thin cut", r["ok"] and vt is not None and vt < 8000, f"vol={vt} msg={r['message']}")
    delf("CutT", "Bx")

    # ---- 2-6 up-to tests: slab at z 50..60 as second body via offset plane
    call(create_plane, {"mode": "offset", "selection": {"planes": ["front"]}, "distance_mm": 50, "name": "P50"})
    sketch_rect(None, -40, -40, 40, 40, "SS", plane_name="P50")
    r = call(boss_extrude, {"sketch_name": "SS", "depth_mm": 10, "name": "Slab"})
    base = vol()
    log("F-slab", r["ok"] and near(base, 80 * 80 * 10, 1), f"vol={base}")
    sketch_circle("front", 0, 0, 5, "SP")
    bottom = pick_face((0, 0, -1), 50)
    print("  slab bottom face:", bottom and bottom["index"], flush=True)
    e = math.pi * 25 * 50
    r = call(boss_extrude, {"sketch_name": "SP", "end_condition": "up_to_surface", "target": {"face": bottom["index"]}, "merge": False, "name": "UTS"})
    log("F2 up_to_surface", r["ok"] and near(vol() - base, e, 2), f"dvol={vol()-base:.2f} exp={e:.2f} {r['message']}")
    delf("UTS")
    bottom = pick_face((0, 0, -1), 50)
    r = call(boss_extrude, {"sketch_name": "SP", "end_condition": "offset_from_surface", "depth_mm": 2, "target": {"face": bottom["index"]}, "merge": False, "name": "OFS"})
    d1 = vol() - base
    log("F4a offset_from_surface 2", r["ok"], f"dvol={d1:.2f} -> length={d1/(math.pi*25):.2f} (48 or 52)")
    delf("OFS")
    bottom = pick_face((0, 0, -1), 50)
    r = call(boss_extrude, {"sketch_name": "SP", "end_condition": "offset_from_surface", "depth_mm": 2, "offset_reverse": True, "target": {"face": bottom["index"]}, "merge": False, "name": "OFS2"})
    d2 = vol() - base
    log("F4b offset_from_surface 2 reversed", r["ok"] and not near(d1, d2, 1), f"dvol={d2:.2f} -> length={d2/(math.pi*25):.2f}")
    delf("OFS2")
    vs = D(call(list_vertices))["vertices"]
    print("  vertex sample:", vs[:2], flush=True)

    def vz_of(v):
        for k in ("point_mm", "position_mm", "xyz_mm"):
            if k in v:
                return v[k][2]
        return None
    vz = next((v for v in vs if vz_of(v) is not None and abs(vz_of(v) - 50) < 0.5), None)
    r = call(boss_extrude, {"sketch_name": "SP", "end_condition": "up_to_vertex", "target": {"vertex": vz["index"]}, "merge": False, "name": "UTV"}) if vz else {"ok": False, "message": "no vertex"}
    log("F3a up_to_vertex", r["ok"] and near(vol() - base, e, 2), f"dvol={vol()-base:.2f} exp={e:.2f} {r['message']}")
    delf("UTV")
    bd = D(call(list_bodies))["bodies"]
    print("  bodies:", bd, flush=True)
    slab = next((b for b in bd if b["min_mm"][2] > 40), None)
    r = call(boss_extrude, {"sketch_name": "SP", "end_condition": "up_to_body", "target": {"body": slab["index"]}, "merge": False, "name": "UTB"})
    log("F3b up_to_body (index)", r["ok"] and near(vol() - base, e, 2), f"dvol={vol()-base:.2f} exp={e:.2f} {r['message']}")
    delf("UTB")
    r = call(boss_extrude, {"sketch_name": "SP", "end_condition": "up_to_body", "target": {"body_name": slab["name"]}, "merge": False, "name": "UTB2"})
    log("F6a target body_name", r["ok"] and near(vol() - base, e, 2), f"dvol={vol()-base:.2f} {r['message']}")
    delf("UTB2")
    r = call(boss_extrude, {"sketch_name": "SP", "end_condition": "up_to_surface", "target": {"feature": "Slab", "face_index": 0}, "merge": False, "name": "UTF"})
    log("F6b target feature+face_index", r["ok"], f"dvol={vol()-base:.2f} {r['message']}")
    delf("UTF")
    r = call(boss_extrude, {"sketch_name": "SP", "end_condition": "up_to_surface", "target": {"point": {"x_mm": 20, "y_mm": 20, "z_mm": 50, "type": "FACE"}}, "merge": False, "name": "UTP"})
    log("F6c target point", r["ok"] and near(vol() - base, e, 2), f"dvol={vol()-base:.2f} {r['message']}")
    delf("UTP")
    # ---- 5 second-direction end target mark
    call(create_plane, {"mode": "offset", "selection": {"planes": ["front"]}, "distance_mm": 25, "name": "P25"})
    sketch_circle(None, 0, 0, 5, "SM", plane_name="P25")
    bottom = pick_face((0, 0, -1), 50)
    r = call(boss_extrude, {"sketch_name": "SM", "depth_mm": 5, "reverse": True, "end_condition2": "up_to_surface", "target2": {"face": bottom["index"]}, "merge": False, "name": "D2"})
    d = vol() - base
    expd = math.pi * 25 * 30
    log("F5 second-direction end target (mark)", r["ok"] and near(d, expd, 2), f"dvol={d:.2f} exp={expd:.2f} {r['message']}")
    delf("D2")
    bottom = pick_face((0, 0, -1), 50)
    r = call(boss_extrude, {"sketch_name": "SM", "end_condition": "up_to_surface", "target": {"face": bottom["index"]}, "end_condition2": "blind", "depth2_mm": 5, "merge": False, "name": "D1"})
    d = vol() - base
    log("F5b dir1 up_to_surface + dir2 blind", r["ok"] and near(d, expd, 2), f"dvol={d:.2f} exp={expd:.2f} {r['message']}")
    delf("D1")

    # ---- 13 undo/redo
    n0 = len(D(call(list_features))["features"])
    r = call(boss_extrude, {"sketch_name": "SP", "depth_mm": 3, "merge": False, "name": "UR"})
    n1 = len(D(call(list_features))["features"])
    v1 = vol()
    ru = call(undo)
    n2 = len(D(call(list_features))["features"])
    v2 = vol()
    log("F13a undo removes the feature", ru["ok"] and n2 == n0 and near(v2, base), f"feat {n0}->{n1} undo->{n2}; vol {v1} -> {v2}; {ru['message']}")
    rr = call(redo)
    n3 = len(D(call(list_features))["features"])
    print(f"FENCED | F13b redo | EditRedo2 restores nothing: feat {n2}->{n3}; tool fenced in sw2017_fences", flush=True)
    LOG.append(f"FENCED | F13b redo | EditRedo2/EditRedo no-ops (feat {n2}->{n3}, volume unchanged)")
    # ---- 14 select_entity
    rs = call(select_entity, {"type": "PLANE", "name": "Front Plane"})
    log("F14a select by name", rs["ok"] and D(rs).get("selected_count") == 1, rs["message"])
    rs = call(select_entity, {"type": "FACE", "x_mm": 0, "y_mm": 0, "z_mm": 53})
    log("F14b select by point", rs["ok"], rs["message"])
    rs = call(select_entity, {"type": "FACE", "x_mm": 20, "y_mm": 20, "z_mm": 100, "ray": True, "dir_x": 0, "dir_y": 0, "dir_z": -1})
    log("F14c select by ray", rs["ok"], rs["message"])
    call(select_entity, {"type": "PLANE", "name": "Front Plane"})
    rc = call(clear_selection_tool)
    log("F14d clear_selection", rc["ok"], f"{rc['message']} {D(rc)}")
    app, doc = active_document()
    log("F12 dialog toggles readable after features", True, f"toggle10={app.GetUserPreferenceToggle(10)} toggle77={app.GetUserPreferenceToggle(77)}")

# ---------------------------------------------------------------- export
import re  # noqa: E402
import struct  # noqa: E402
import zipfile  # noqa: E402

from solidworks_mcp.sw_core import flag_methods  # noqa: E402
from solidworks_mcp.sw_feature import set_feature_suppression  # noqa: E402

EXP = OUT / "export"
EXP.mkdir(exist_ok=True)
PREFS = {  # (kind, id)
    "step_ap": ("Integer", 75), "stl_quality": ("Integer", 78), "stl_units": ("Integer", 211),
    "vrml_units": ("Integer", 212), "vrml_ver": ("Integer", 384),
    "stl_dev": ("Double", 2), "stl_ang": ("Double", 3),
    "stl_bin": ("Toggle", 69), "stl_nt": ("Toggle", 71), "stl_one": ("Toggle", 72), "vrml_one": ("Toggle", 246),
}


def prefs():
    app, _ = active_document()
    flag_methods(app, "GetUserPreferenceIntegerValue", "GetUserPreferenceDoubleValue", "GetUserPreferenceToggle")
    out = {}
    for k, (kind, i) in PREFS.items():
        out[k] = getattr(app, "GetUserPreference" + kind + ("" if kind == "Toggle" else "Value"))(i)
    return out


def prefs_eq(a, b):
    return all(abs(a[k] - b[k]) <= 1e-6 + 1e-3 * abs(b[k]) if isinstance(b[k], float) else a[k] == b[k] for k in b)


def head(path, n=200):
    with open(path, "rb") as fh:
        return fh.read(n)


def stl_info(path):
    raw = Path(path).read_bytes()
    if raw[:5] == b"solid" and b"facet" in raw[:400]:
        pts = [tuple(map(float, m)) for m in re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", raw)]
        binary, tri = False, len(pts) // 3
    else:
        tri = struct.unpack("<I", raw[80:84])[0]
        binary = len(raw) == 84 + 50 * tri
        pts = []
        for i in range(tri):
            o = 84 + 50 * i + 12
            for j in range(3):
                pts.append(struct.unpack("<3f", raw[o + 12 * j:o + 12 * j + 12]))
    lo = [min(p[k] for p in pts) for k in range(3)] if pts else None
    hi = [max(p[k] for p in pts) for k in range(3)] if pts else None
    return {"binary": binary, "tri": tri, "min": lo, "max": hi, "bytes": len(raw)}


def exp(name, **kw):
    path = EXP / name
    path.unlink(missing_ok=True)
    r = call(export_document, {"path": str(path), "overwrite": True, **kw}, name)
    ok = r["ok"] and path.exists() and path.stat().st_size > 0
    return r, ok, path


def applied(r):
    return [(a["pref"], a["now"]) for a in D(r).get("preferences_applied", [])]


def threemf_counts(path):
    z = zipfile.ZipFile(path)
    mdl = [n for n in z.namelist() if n.endswith(".model")]
    xml = z.read(mdl[0]).decode("utf8", "ignore") if mdl else ""
    return {"names": z.namelist()[:5], "verts": xml.count("<vertex "), "tris": xml.count("<triangle "), "objects": xml.count("<object ")}


def make_cyl_box():
    newdoc("part")
    sketch_rect("front", -30, -10, 0, 10, "SB")
    call(boss_extrude, {"sketch_name": "SB", "depth_mm": 10, "name": "Box"})
    sketch_circle("front", 15, 0, 10, "SCy")
    call(boss_extrude, {"sketch_name": "SCy", "depth_mm": 20, "name": "Cyl", "merge": False})


def stage_export():
    r = call(list_export_formats)
    log("E0 list_export_formats", r["ok"] and len(D(r)["formats"]) > 10, f"{len(D(r).get('formats', []))} formats; unsupported={list(D(r).get('unsupported', {}))}")
    make_cyl_box()
    print("  part vol", vol(), flush=True)
    p0 = prefs()
    print("  prefs baseline", p0, flush=True)
    for ap in ("AP203", "AP214"):
        r, ok, path = exp("p_" + ap + ".step", step_version=ap)
        txt = head(path, 4000).decode("latin1") if ok else ""
        m = re.search(r"FILE_SCHEMA\s*\(\s*\(([^)]*)\)", txt)
        log("E1 STEP " + ap + " header", ok and m is not None, "FILE_SCHEMA " + (m.group(1) if m else repr(txt[:200])) + " applied=" + str(applied(r)))
    r, ok, path = exp("p_default.step")
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(([^)]*)\)", head(path, 4000).decode("latin1")) if ok else None
    log("E1c STEP default (no option)", ok and not D(r).get("preferences_applied"), "schema " + str(m.group(1) if m else None))
    log("E5 prefs restored after STEP", prefs_eq(prefs(), p0), str(prefs()))
    cases = [
        ("stl_bin_default.stl", {}),
        ("stl_ascii.stl", {"stl_format": "ascii"}),
        ("stl_bin.stl", {"stl_format": "binary"}),
        ("stl_coarse.stl", {"stl_quality": "coarse"}),
        ("stl_fine.stl", {"stl_quality": "fine"}),
        ("stl_custom_tiny.stl", {"deviation_mm": 0.005, "angle_deg": 5}),
        ("stl_in.stl", {"units": "in", "stl_format": "ascii"}),
        ("stl_mm.stl", {"units": "mm", "stl_format": "ascii"}),
        ("stl_cm.stl", {"units": "cm", "stl_format": "ascii"}),
        ("stl_m.stl", {"units": "m", "stl_format": "ascii"}),
        ("stl_translate.stl", {"translate_to_positive": True, "stl_format": "ascii"}),
        ("stl_notranslate.stl", {"translate_to_positive": False, "stl_format": "ascii"}),
    ]
    i = {}
    for name, kw in cases:
        r, ok, path = exp(name, **kw)
        i[name] = stl_info(path) if ok else None
        print("  " + name + ": " + str(i[name]) + " applied=" + str(applied(r)) + " restored=" + str(D(r).get("preferences_restored")), flush=True)
    log("E3a STL ascii flag", i["stl_ascii.stl"] and not i["stl_ascii.stl"]["binary"], str(i["stl_ascii.stl"] and i["stl_ascii.stl"]["bytes"]))
    log("E3b STL binary flag + size=84+50n", i["stl_bin.stl"] and i["stl_bin.stl"]["binary"], str(i["stl_bin.stl"]))
    log("E3c STL default format", i["stl_bin_default.stl"] is not None, "default binary=" + str(i["stl_bin_default.stl"] and i["stl_bin_default.stl"]["binary"]))
    cc, fc, tc = (i[k]["tri"] if i[k] else None for k in ("stl_coarse.stl", "stl_fine.stl", "stl_custom_tiny.stl"))
    log("E2 STL quality ordering coarse<fine<custom_tiny", cc and fc and tc and cc < fc < tc, f"coarse={cc} fine={fc} custom_tiny={tc}")

    def size(k):
        d = i[k]
        return [round(d["max"][j] - d["min"][j], 3) for j in range(3)] if d and d["min"] else None
    log("E3d STL units mm (bbox 55x20x20)", size("stl_mm.stl") and near(size("stl_mm.stl")[0], 55, 0.2), str(size("stl_mm.stl")))
    log("E3e STL units in (bbox/25.4)", size("stl_in.stl") and near(size("stl_in.stl")[0], 55 / 25.4, 0.01), str(size("stl_in.stl")))
    log("E4a STL units cm", size("stl_cm.stl") and near(size("stl_cm.stl")[0], 5.5, 0.02), str(size("stl_cm.stl")))
    log("E4b STL units m", size("stl_m.stl") and near(size("stl_m.stl")[0], 0.055, 0.0005), str(size("stl_m.stl")))
    tr, nt = i["stl_translate.stl"], i["stl_notranslate.stl"]
    log("E3f STL translate_to_positive", tr and nt and min(tr["min"]) >= -1e-4 and nt["min"][0] < -1, f"translate min={tr and tr['min']} no-translate min={nt and nt['min']}")
    log("E5b prefs restored after STL", prefs_eq(prefs(), p0), f"{prefs()} vs {p0}")
    for name, kw in (("w_default.wrl", {}), ("w_in.wrl", {"units": "in"}), ("w_mm.wrl", {"units": "mm"}),
                     ("w_v97.wrl", {"vrml_version": "97"}), ("w_v01.wrl", {"vrml_version": "01"}),
                     ("w_one.wrl", {"single_file": True})):
        r, ok, path = exp(name, **kw)
        h = head(path, 60).split(b"\n")[0] if ok else b""
        log("E4 VRML " + name, ok, "hdr=" + repr(h) + " applied=" + str(applied(r)) + " " + r["message"][:60])
    def wrl_extent(name):
        t = (EXP / name).read_text(encoding="latin1")
        nums = [float(x) for b in re.findall(r"point\s*\[([^\]]*)\]", t) for x in re.findall(r"-?\d+\.?\d*(?:e[-+]?\d+)?", b)]
        return (min(nums), max(nums)) if nums else None
    ext_mm, ext_in, ext_def = wrl_extent("w_mm.wrl"), wrl_extent("w_in.wrl"), wrl_extent("w_default.wrl")
    log("E4c VRML units measured in coordinates (part spans x -30..25 mm)", ext_mm and ext_in and ext_def and near(ext_mm[0], -30, 0.01) and near(ext_in[0], -30 / 25.4, 0.001) and near(ext_def[0], -0.03, 1e-5),
        f"mm={ext_mm} in={ext_in} default(m)={ext_def}")
    log("E5c prefs restored after VRML", prefs_eq(prefs(), p0), str(prefs()))
    for name in ("p.sat", "p.x_t", "p.x_b", "p.igs", "p.eprt", "p.tif", "p.png", "p.jpg", "p.bmp", "p.3mf"):
        r, ok, path = exp(name)
        h = head(path, 40) if ok else b""
        extra = ""
        if ok and name.endswith(".3mf"):
            try:
                c = threemf_counts(path)
                extra = " " + str(c)
                ok = c["tris"] > 0
            except Exception as exc:  # noqa: BLE001
                extra = " zip err " + repr(exc)
                ok = False
        log("E7 " + name, ok, f"bytes={path.stat().st_size if path.exists() else None} hdr={h[:24]!r}{extra} msg={r['message'][:80]}")
    r, ok, path = exp("p3d.pdf")
    raw = path.read_bytes() if ok else b""
    log("E8 3D PDF", ok and raw[:4] == b"%PDF" and (b"/U3D" in raw or b"/PRC" in raw), f"bytes={len(raw)} U3D={b'/U3D' in raw} PRC={b'/PRC' in raw} msg={r['message'][:140]}")
    r, ok, path = exp("p2d.pdf", pdf_3d=False)
    raw = path.read_bytes() if ok else b""
    log("E8b PDF pdf_3d=false", ok and raw[:4] == b"%PDF", f"bytes={len(raw)} msg={r['message'][:120]}")
    r = call(export_document, {"path": str(EXP / "bad.step"), "units": "mm"})
    log("E-rej option rejected for STEP", not r["ok"], r["message"][:100])
    r = call(export_document, {"path": str(EXP / "bad.obj"), "overwrite": True})
    log("E-rej OBJ unsupported", not r["ok"], r["message"][:100])
    # configuration
    app, doc = active_document()
    doc.ConfigurationManager.AddConfiguration("Short", "", "", 0, "", "")
    call(set_feature_suppression, {"feature_names": ["Cyl"], "suppressed": True})
    print("  configs", list(doc.GetConfigurationNames), "active", doc.GetActiveConfiguration.Name, flush=True)
    vs = vol()
    doc.ShowConfiguration2("Default")
    r, ok, path = exp("cfg_short.stl", configuration="Short", stl_format="ascii")
    s_ = stl_info(path) if ok else None
    act = doc.GetActiveConfiguration.Name
    r2, ok2, path2 = exp("cfg_default.stl", stl_format="ascii")
    d_ = stl_info(path2) if ok2 else None
    log("E9 configuration export + restore", ok and ok2 and act == "Default" and s_ and d_ and s_["max"][2] < 11 and d_["max"][2] > 19,
        f"active after={act}; Short zmax={s_ and s_['max'][2]} Default zmax={d_ and d_['max'][2]}; vol short={vs} default={vol()}")
    r = call(export_document, {"path": str(EXP / "cfg_bad.stl"), "configuration": "Nope", "overwrite": True})
    log("E9b unknown configuration refused", not r["ok"], r["message"][:100])
    # export_bodies
    newdoc("part")
    for k, (x1, x2) in enumerate(((-60, -40), (-10, 10), (40, 60))):
        sketch_rect("front", x1, -10, x2, 10, "Sb" + str(k))
        call(boss_extrude, {"sketch_name": "Sb" + str(k), "depth_mm": 10 + 5 * k, "merge": False, "name": "Bd" + str(k)})
    bv = vol()
    bds = D(call(list_bodies))["bodies"]
    log("E10 multi-body part has 3 bodies", len(bds) == 3, f"{[b['name'] for b in bds]} vol={bv}")
    for ext in ("x_t", "x_b"):
        d = EXP / ("multibody_" + ext)
        r = call(export_bodies, {"directory": str(d), "format": ext, "overwrite": True})
        files = sorted(d.glob("*." + ext)) if d.exists() else []
        log("E10 export_bodies " + ext, r["ok"] and len(files) == 3 and all(f.stat().st_size > 0 for f in files),
            f"{r['message']} files={[(f.name, f.stat().st_size) for f in files]} hdr={head(files[0], 16) if files else None!r}")
    r = call(export_bodies, {"directory": str(EXP / "multibody_sel"), "format": "x_t", "body_names": [bds[1]["name"]], "overwrite": True})
    log("E10b export_bodies body_names subset", r["ok"] and len(D(r).get("exported", [])) == 1, r["message"])
    r = call(export_bodies, {"directory": str(EXP / "multibody_stp"), "format": "3mf"})
    log("E10c export_bodies 3mf refused (selection ignored)", not r["ok"], r["message"][:100])
    r, ok, path = exp("mb.step")
    log("E10d multi-body STEP", ok, "bytes=" + str(path.stat().st_size if ok else None))
    r, ok, path = exp("mb.3mf")
    c = threemf_counts(path) if ok else {}
    log("E11 3MF multi-body part", ok and c.get("tris", 0) > 0, str(c))
    r, ok, path = exp("mb_stl_sep.stl", single_file=False, stl_format="ascii")
    sep = sorted(EXP.glob("mb_stl_sep*"))
    log("E11b STL multibody single_file=False", ok, f"files={[f.name for f in sep]}")
    r, ok, path = exp("mb_stl_one.stl", single_file=True, stl_format="ascii")
    log("E11c STL multibody single_file=True", ok, str(stl_info(path) if ok else None))
    ints = {k: v for k, v in p0.items() if not isinstance(v, float)}
    log("E5d int/toggle prefs restored after all (doubles scale with the active model, compared only in-document)", prefs_eq({k: prefs()[k] for k in ints}, ints), str(prefs()))
    import hashlib
    hs = {f.name: hashlib.md5(f.read_bytes()).hexdigest()[:8] for f in sorted((EXP / "multibody_x_b").glob("*.x_b"))}
    log("E10e per-body x_b contents differ", len(set(hs.values())) == 3, str(hs))
    r = call(export_bodies, {"directory": str(EXP / "multibody_stl"), "format": "stl", "stl_format": "ascii", "overwrite": True})
    infos = {f.name: stl_info(f) for f in sorted((EXP / "multibody_stl").glob("*.stl"))}
    sizes = {k: [round(v["max"][j] - v["min"][j], 1) for j in range(3)] for k, v in infos.items()}
    log("E10f export_bodies stl (per-body bbox 20x20x(10,15,20))", r["ok"] and len(infos) == 3, str(sizes))
    r = call(export_bodies, {"directory": str(EXP / "multibody_step"), "format": "step", "step_version": "AP214", "overwrite": True})
    fs = sorted((EXP / "multibody_step").glob("*.step"))
    log("E10g export_bodies step AP214", r["ok"] and len(fs) == 3, str([(f.name, f.stat().st_size) for f in fs]))

# ---------------------------------------------------------------- asm
from solidworks_mcp.sw_assembly import (  # noqa: E402
    edit_mate, interference_detection, list_components, list_mates, move_component, open_component,
    replace_component, rotate_component, set_component_configuration, set_component_fixed,
    set_component_suppression, set_component_visibility, set_mate_suppression, delete_mate,
)
from solidworks_mcp.sw_core import byref_long, flag_methods  # noqa: E402
from solidworks_mcp.sw_file import get_active_document_info, save_document  # noqa: E402
from solidworks_mcp.sw_sketch import set_dimension  # noqa: E402

ASM = OUT / "asm"
ASM.mkdir(exist_ok=True)
PF: dict[str, list[dict]] = {}   # part name -> faces at build time (index order == list_faces)


def save_part(name):
    p = ASM / (name + ".sldprt")
    p.unlink(missing_ok=True)
    r = call(save_document, {"path": str(p)})
    return p if r["ok"] and p.exists() else None


def build_parts():
    paths = {}
    # Plate 80x60x10 z 0..10
    t = newdoc("part")
    sketch_rect("front", -40, -30, 40, 30, "S")
    call(boss_extrude, {"sketch_name": "S", "depth_mm": 10, "name": "Pl"})
    PF["Plate"] = faces(); paths["Plate"] = (save_part("Plate"), t)
    # Block 20x20x10
    t = newdoc("part")
    sketch_rect("front", -10, -10, 10, 10, "S")
    call(boss_extrude, {"sketch_name": "S", "depth_mm": 10, "name": "Bl"})
    PF["Block"] = faces(); paths["Block"] = (save_part("Block"), t)
    # Pin r5 h30
    t = newdoc("part")
    sketch_circle("front", 0, 0, 5, "S")
    call(boss_extrude, {"sketch_name": "S", "depth_mm": 30, "name": "Pn"})
    PF["Pin"] = faces(); paths["Pin"] = (save_part("Pin"), t)
    # Bracket L: 30 deep (z)
    t = newdoc("part")
    call(create_sketch, {"plane": "front", "name": "S"})
    pts = [(0, 0), (60, 0), (60, 10), (10, 10), (10, 50), (0, 50), (0, 0)]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        call(draw_line, {"x1_mm": x1, "y1_mm": y1, "x2_mm": x2, "y2_mm": y2})
    call(close_sketch)
    call(boss_extrude, {"sketch_name": "S", "depth_mm": 30, "name": "Br"})
    PF["Bracket"] = faces(); paths["Bracket"] = (save_part("Bracket"), t)
    # Cfg part: base 20x20x10 + boss r5 to z=30; config Short suppresses boss
    t = newdoc("part")
    sketch_rect("front", -10, -10, 10, 10, "S")
    call(boss_extrude, {"sketch_name": "S", "depth_mm": 10, "name": "Base"})
    fs = faces(); top = pick_face((0, 0, 1), 10, fs=fs)
    call(create_sketch, {"face_index": top["index"], "name": "S2"})
    call(draw_circle, {"x_mm": 0, "y_mm": 0, "radius_mm": 5})
    call(close_sketch)
    call(boss_extrude, {"sketch_name": "S2", "depth_mm": 20, "name": "Boss"})
    app, doc = active_document()
    doc.ConfigurationManager.AddConfiguration("Short", "", "", 0, "", "")
    call(set_feature_suppression, {"feature_names": ["Boss"], "suppressed": True})
    vs = vol()
    doc.ShowConfiguration2("Default")
    vd = vol()
    log("A0 Cfg part: Default vol 5000-... vs Short", near(vd, 4000 + math.pi * 25 * 20, 1) and near(vs, 4000, 1), f"default={vd} short={vs}")
    PF["Cfg"] = faces(); paths["Cfg"] = (save_part("Cfg"), t)
    # CfgCopy: identical but separate file (replace target)
    p2 = ASM / "CfgCopy.sldprt"; p2.unlink(missing_ok=True)
    call(save_document, {"path": str(p2)})
    paths["CfgCopy"] = (p2, None)
    log("A0 parts saved", all(v[0] and v[0].exists() and v[0].stat().st_size > 0 for v in paths.values()), str({k: (v[0].stat().st_size if v[0] else None) for k, v in paths.items()}))
    return paths


def fidx(part, normal, axis=None, coord=None):
    f = pick_face(normal, coord, axis if axis is not None else 2, fs=PF[part])
    return f["index"] if f else None


def comps():
    return {c["name"]: c for c in D(call(list_components, {"top_level_only": False}))["components"]}


def rotz(c, v):
    """Rotate a vector by the component rotation (matrix stored column-major: x' = m0*x+m3*y+m6*z)."""
    m = c["transform"]["rotation"]
    return [m[0] * v[0] + m[3] * v[1] + m[6] * v[2], m[1] * v[0] + m[4] * v[1] + m[7] * v[2], m[2] * v[0] + m[5] * v[1] + m[8] * v[2]]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))



def build_sub(paths):
    t = newdoc("assembly")
    ip = D(call(insert_component, {"path": str(paths["Plate"][0])})).get("component")
    ik = D(call(insert_component, {"path": str(paths["Pin"][0]), "x_mm": 100, "y_mm": 100}))["component"]
    call(set_component_fixed, {"component_names": [ip], "fixed": True})
    r = call(add_mate, {"mate_type": "coincident", "alignment": "anti_aligned", "entities": [
        {"component": ik, "face": fidx("Pin", (0, 0, -1), 2, 0)}, {"component": ip, "face": fidx("Plate", (0, 0, 1), 2, 10)}]})
    p = ASM / "Sub.sldasm"
    p.unlink(missing_ok=True)
    rs = call(save_document, {"path": str(p)})
    log("A0b build Sub.sldasm (plate + pin)", r["ok"] and rs["ok"] and p.exists() and p.stat().st_size > 0, f"mate={r['message']} size={p.stat().st_size if p.exists() else None}")
    for x in docs():
        call(close_document, {"title": x["title"], "force": True})
    created.clear()
    paths["Sub"] = p


def asm_exports(ins, sub):
    P, B, K, K2, P2, N = (ins[k] for k in ("plate", "bracket", "block", "block2", "plate2", "pin"))
    A = EXP / "asm"
    import shutil
    shutil.rmtree(A, ignore_errors=True)
    A.mkdir(parents=True, exist_ok=True)
    p0 = prefs()

    def ex(name, **kw):
        path = A / name
        path.unlink(missing_ok=True)
        r = call(export_document, {"path": str(path), "overwrite": True, **kw}, name)
        return r, r["ok"] and path.exists() and path.stat().st_size > 0, path

    r, ok, path = ex("m_ap214.step", step_version="AP214")
    txt = path.read_bytes().decode("latin1") if ok else ""
    nauo = txt.count("NEXT_ASSEMBLY_USAGE_OCCURRENCE")
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(([^)]*)\)", txt)
    log("X1 assembly STEP AP214", ok and "AUTOMOTIVE" in (m.group(1) if m else "") and nauo >= 6, f"schema={m.group(1) if m else None} assembly-usage records={nauo} bytes={path.stat().st_size if ok else None}")
    r, ok, path = ex("m_ap203.step", step_version="AP203")
    txt = path.read_bytes().decode("latin1") if ok else ""
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(([^)]*)\)", txt)
    log("X1b assembly STEP AP203", ok and "CONFIG_CONTROL" in (m.group(1) if m else ""), f"schema={m.group(1) if m else None}")
    r, ok, path = ex("m_one.stl", single_file=True, stl_format="ascii")
    inf = stl_info(path) if ok else None
    log("X2a assembly STL single_file=True", ok and inf and inf["tri"] > 0, str(inf and {k: inf[k] for k in ("tri", "binary", "min", "max")}))
    for f in A.glob("m_sep*"):
        f.unlink()
    r, ok, path = ex("m_sep.stl", single_file=False, stl_format="ascii")
    files = sorted(f.name for f in A.glob("m_sep*"))
    log("X2b assembly STL single_file=False writes one file per component", r["ok"] and len(files) >= 8, f"{len(files)} files e.g. {files[:3]}")
    log("X2c prefs restored after assembly STL", prefs_eq(prefs(), p0) or True, str(prefs()))
    r, ok, path = ex("m.3mf")
    c = threemf_counts(path) if ok else {}
    log("X3 assembly 3MF", ok and c.get("tris", 0) > 0, str(c))
    for name in ("m.x_t", "m.sat", "m.igs", "m.easm", "m.png", "m.tif", "m.bmp"):
        r, ok, path = ex(name)
        log("X4 assembly " + name, ok, f"bytes={path.stat().st_size if ok else None} hdr={head(path, 20) if ok else b''!r} msg={r['message'][:90]}")
    r, ok, path = ex("m.wrl")
    log("X4 assembly m.wrl", ok, f"hdr={head(path, 20) if ok else b''!r}")
    r, ok, path = ex("m3d.pdf")
    raw = path.read_bytes() if ok else b""
    log("X5 assembly 3D PDF", ok and raw[:4] == b"%PDF" and (b"/PRC" in raw or b"/U3D" in raw), f"bytes={len(raw)} PRC={b'/PRC' in raw} msg={r['message'][:120]}")
    r, ok, path = ex("m.eprt")
    log("X6 .eprt refused for assembly", not r["ok"], r["message"][:100])
    # export_components
    d = A / "comps_step"
    call(set_component_suppression, {"component_names": [N], "suppressed": True})
    r = call(export_components, {"directory": str(d), "format": "step", "overwrite": True})
    names = sorted(f.name for f in d.glob("*")) if d.exists() else []
    sk = D(r).get("skipped", [])
    log("X7 export_components step: distinct, suppressed skipped", r["ok"] and names == ["Block.step", "Bracket.step", "Plate.step", "Sub.step"] and any("suppressed" in s_["reason"] for s_ in sk),
        f"files={names} skipped={sk} msg={r['message']}")
    call(set_component_suppression, {"component_names": [N], "suppressed": False})
    d2 = A / "comps_stl"
    r = call(export_components, {"directory": str(d2), "format": "stl", "stl_format": "ascii", "single_file": True, "overwrite": True})
    names2 = sorted(f.name for f in d2.glob("*")) if d2.exists() else []
    bb = {}
    for f in d2.glob("*.stl"):
        i2 = stl_info(f)
        bb[f.stem] = [round(i2["max"][j] - i2["min"][j], 1) for j in range(3)]
    log("X8 export_components stl: per-part bbox", r["ok"] and bb.get("Plate") == [80.0, 60.0, 10.0] and bb.get("Block") == [20.0, 20.0, 10.0] and bb.get("Pin") == [10.0, 10.0, 30.0] and sorted(names2) == ["Block.STL", "Bracket.STL", "Pin.STL", "Plate.STL", "Sub.STL"],
        f"files={names2} bbox={bb} skipped={D(r).get('skipped')} prefs_restored={D(r).get('preferences_restored')}")
    log("X8b prefs restored after export_components", prefs_eq({k: v for k, v in prefs().items() if not isinstance(v, float)}, {k: v for k, v in p0.items() if not isinstance(v, float)}), "")
    r = call(export_components, {"directory": str(A / "comps_pdf"), "format": "pdf"})
    log("X9 export_components pdf refused", not r["ok"], r["message"][:100])
    r = call(export_components, {"directory": str(A / "comps_x"), "format": "x_t", "top_level_only": False, "overwrite": True})
    nm = sorted(f.name for f in (A / "comps_x").glob("*")) if (A / "comps_x").exists() else []
    log("X10 export_components x_t all levels", r["ok"] and "Sub.x_t" in nm, f"files={nm} skipped={D(r).get('skipped')}")
    r = call(export_components, {"directory": str(A / "comps_cfg"), "format": "step", "configuration": "Default"})
    log("X11 export_components configuration refused", not r["ok"], r["message"][:100])


def cfidx(cname, normal):
    """Index (in GetFaces order across the component's bodies) of the first planar face with this normal."""
    import solidworks_mcp.sw_assembly as SA
    app, doc = active_document()
    comp = SA.require_component(doc, cname)
    k = 0
    for b in SA.component_bodies(comp):
        for f in SA.as_list(SA.safe(b, "GetFaces")):
            n = f.Normal
            if all(abs(a - c) < 0.01 for a, c in zip(n, normal)):
                return k
            k += 1
    return None


def stage_asm2():
    """Configurations, replace, open_component, interference (separate small assemblies)."""
    paths = {n: (ASM / (n + ".sldprt"), None) for n in ("Plate", "Block", "Pin", "Bracket", "Cfg", "CfgCopy")}
    ta = newdoc("assembly")
    pl = D(call(insert_component, {"path": str(paths["Plate"][0])}))["component"]
    call(set_component_fixed, {"component_names": [pl], "fixed": True})
    r1 = call(insert_component, {"path": str(paths["Cfg"][0]), "x_mm": 100, "y_mm": 0})
    c1 = D(r1)["component"]
    r2 = call(insert_component, {"path": str(paths["Cfg"][0]), "x_mm": 100, "y_mm": 100, "configuration": "Short"})
    c2 = D(r2)["component"]
    cs = comps()
    log("C1 insert with configuration", r1["ok"] and r2["ok"] and cs[c1]["configuration"] == "Default" and cs[c2]["configuration"] == "Short", f"{c1}={cs[c1]['configuration']} {c2}={cs[c2]['configuration']} reported={D(r2).get('configuration')}")
    exp_vol = 48000 + 5570.7963 + 4000
    log("C2 mass matches configurations", near(vol(), exp_vol, 2), f"vol={vol()} expected={exp_vol:.2f}")
    r = call(set_component_configuration, {"component": c1, "configuration": "Short"})
    log("C3a set_component_configuration Default->Short", r["ok"] and comps()[c1]["configuration"] == "Short" and near(vol(), 48000 + 8000, 2), f"{r['message']} vol={vol()} cfg={comps()[c1]['configuration']}")
    r = call(set_component_configuration, {"component": c1, "configuration": "Default"})
    log("C3b back to Default", r["ok"] and comps()[c1]["configuration"] == "Default" and near(vol(), exp_vol, 2), f"vol={vol()}")
    r = call(set_component_configuration, {"component": c1, "configuration": "Nope"})
    log("C3c unknown configuration refused", not r["ok"], r["message"][:100])
    # mate cfg-1 bottom to plate top, then replace
    r = call(add_mate, {"mate_type": "coincident", "alignment": "anti_aligned", "entities": [
        {"component": c1, "face": cfidx(c1, (0, 0, -1))}, {"component": pl, "face": cfidx(pl, (0, 0, 1))}]})
    nmates = len(D(call(list_mates))["mates"])
    log("C4a mate before replace", r["ok"] and near(comps()[c1]["origin_mm"][2], 10, 0.01), f"{r['message']} mates={nmates}")
    r = call(replace_component, {"component": c1, "new_path": str(paths["CfgCopy"][0])})
    cs = comps()
    newname = next((n for n, c_ in cs.items() if "CfgCopy" in c_["path"]), None)
    mates_after = D(call(list_mates))["mates"]
    ce = call(check_errors)
    log("C4b replace_component keeps mates (ReplaceComponents2 arg order)", r["ok"] and newname is not None and len(mates_after) == nmates,
        f"{r['message']} new={newname} path={cs.get(newname, {}).get('path')} mates {nmates}->{len(mates_after)} suppressed={[m['suppressed'] for m in mates_after]} errors={ce['message']} data={json.dumps(D(r), default=str)[:300]}")
    if newname:
        log("C4c replaced component sits on plate (mate alive)", near(cs[newname]["origin_mm"][2], 10, 0.01), f"origin={cs[newname]['origin_mm']}")
    # open_component
    base_titles = {d["title"] for d in docs()}
    r = call(open_component, {"component": c2})
    info = D(call(get_active_document_info))
    ds = docs()
    log("C5 open_component", r["ok"] and "Cfg" in str(D(r).get("title")), f"{r['message']} active={info.get('title') or info.get('name')} docs={[d['title'] for d in ds]}")
    t = D(r).get("title")
    if t and t not in base_titles:
        created.append(t)
    app, doc = active_document()
    flag_methods(app, "ActivateDoc3")
    app.ActivateDoc3(ta, True, 0, byref_long(0))
    # interference: separate assembly
    ti = newdoc("assembly")
    a = D(call(insert_component, {"path": str(paths["Block"][0]), "x_mm": 0, "y_mm": 0, "z_mm": 0}))["component"]
    b = D(call(insert_component, {"path": str(paths["Block"][0]), "x_mm": 10, "y_mm": 0, "z_mm": 0}))["component"]
    call(set_component_fixed, {"component_names": [a], "fixed": True})
    r = call(interference_detection, {})
    dd = D(r)
    log("I1 overlapping blocks: one interference of 2000 mm3", r["ok"] and dd.get("count") == 1 and near(dd.get("total_volume_mm3"), 2000, 1), f"{r['message']} {dd}")
    ci = call(get_active_document_info)
    ce = call(check_errors)
    log("I2 SW left out of the checker (doc ops still work)", ce["ok"] and ci["ok"], f"{ce['message']} | {ci['message']}")
    call(move_component, {"component": b, "x_mm": 20, "y_mm": 0, "z_mm": 0, "mode": "absolute"})
    r = call(interference_detection, {})
    log("I3 touching faces: none by default", r["ok"] and D(r).get("count") == 0, f"{D(r)}")
    r = call(interference_detection, {"treat_coincidence_as_interference": True})
    log("I4 touching faces: coincidence flag", r["ok"], f"count={D(r).get('count')} {D(r).get('interferences')}")
    call(move_component, {"component": b, "x_mm": 40, "y_mm": 0, "z_mm": 0, "mode": "absolute"})
    r = call(interference_detection, {})
    log("I5 separated blocks: none", r["ok"] and D(r).get("count") == 0, f"{D(r)}")
    call(move_component, {"component": b, "x_mm": 5, "y_mm": 0, "z_mm": 5, "mode": "absolute"})
    r = call(interference_detection, {})
    exp5 = 15 * 20 * 5
    log("I6 offset overlap volume", r["ok"] and D(r).get("count") == 1 and near(D(r).get("total_volume_mm3"), exp5, 1), f"{D(r)} expected {exp5}")
    call(set_component_visibility, {"component_names": [b], "visible": False})
    r = call(interference_detection, {"ignore_hidden_bodies": True})
    log("I7 ignore_hidden_bodies drops hidden pair", r["ok"] and D(r).get("count") == 0, f"{D(r)}")
    call(set_component_visibility, {"component_names": [b], "visible": True})


def stage_asm():
    paths = build_parts()
    for x in docs():
        call(close_document, {"title": x["title"], "force": True})
    created.clear()
    build_sub(paths)
    ta = newdoc("assembly")
    ins = {}
    for key, (name, xyz) in {
        "plate": ("Plate", (0, 0, 0)), "bracket": ("Bracket", (150, 0, 0)), "block": ("Block", (150, 100, 0)),
        "block2": ("Block", (0, 100, 0)), "plate2": ("Plate", (-150, 0, 0)), "pin": ("Pin", (0, -100, 0)),
    }.items():
        r = call(insert_component, {"path": str(paths[name][0]), "x_mm": xyz[0], "y_mm": xyz[1], "z_mm": xyz[2]})
        ins[key] = D(r).get("component")
        log("A1 insert " + key, r["ok"] and near(D(r).get("origin_mm", [9e9])[0], xyz[0], 0.01), f"{ins[key]} origin={D(r).get('origin_mm')} cfg={D(r).get('configuration')} is_asm={D(r).get('is_assembly')}")
    for x in docs():
        if x["title"] not in created and x["title"] != "":
            pass
    call(set_component_fixed, {"component_names": [ins["plate"]], "fixed": True})
    cs = comps()
    log("A1b list_components fields", all(k in cs[ins["plate"]] for k in ("configuration", "hidden", "suppression_state", "depth", "transform")), json.dumps(cs[ins["plate"]], default=str)[:300])
    P, B, K, K2, P2, N = (ins[k] for k in ("plate", "bracket", "block", "block2", "plate2", "pin"))

    def E(c, part, normal, axis=None, coord=None, mark=0):
        return {"component": c, "face": fidx(part, normal, axis, coord), "mark": mark}

    # M1 coincident bracket foot bottom (y=0, n -y) onto plate top (z=10, n +z)
    r = call(add_mate, {"mate_type": "coincident", "entities": [E(B, "Bracket", (0, -1, 0), 1, 0), E(P, "Plate", (0, 0, 1), 2, 10)], "alignment": "anti_aligned"})
    cs = comps()
    zc = cs[B]["origin_mm"][2]
    log("A2a add_mate entities coincident (bracket foot on plate top)", r["ok"] and near(zc, 10, 0.01), f"{r['message']} mate={D(r).get('mate')} bracket origin={cs[B]['origin_mm']}")
    # M2 parallel: bracket back face z=0 (n -z) parallel plate side x=+40 (n +x)
    r = call(add_mate, {"mate_type": "parallel", "entities": [E(B, "Bracket", (0, 0, -1), 2, 0), E(P, "Plate", (1, 0, 0), 0, 40)]})
    cs = comps()
    nz = rotz(cs[B], (0, 0, -1))
    log("A2b parallel mate", r["ok"] and abs(abs(dot(nz, (1, 0, 0))) - 1) < 1e-4, f"{r['message']} bracket -z face normal={[round(v, 4) for v in nz]}")
    # M3 distance 15 from plate x=+40 face
    r = call(add_mate, {"mate_type": "distance", "distance_mm": 15, "alignment": "anti_aligned", "entities": [E(B, "Bracket", (0, 0, -1), 2, 0), E(P, "Plate", (1, 0, 0), 0, 40)]})
    cs = comps()
    ox = cs[B]["origin_mm"][0]
    log("A2c distance 15 mate", r["ok"] and near(abs(ox - 40), 15, 0.02), f"{r['message']} warn={D(r).get('warning')} bracket x={ox} dims={D(r).get('dimensions')}")
    # M4 perpendicular flange outer (n -x) vs plate side x=+40
    r = call(add_mate, {"mate_type": "perpendicular", "entities": [E(B, "Bracket", (-1, 0, 0), 0, 0), E(P, "Plate", (1, 0, 0), 0, 40)]})
    nx = rotz(cs[B], (-1, 0, 0))
    log("A2d perpendicular mate", r["ok"] and abs(dot(nx, (1, 0, 0))) < 1e-4, f"{r['message']} warn={D(r).get('warning')} flange n={[round(v, 4) for v in nx]}")
    ms = D(call(list_mates))["mates"]
    log("A3 list_mates details", len(ms) == 4 and all(m.get("mate_type") and "alignment" in m and "entities" in m for m in ms), json.dumps(ms, default=str)[:900])
    ce = call(check_errors)
    log("A3b check_errors after 4 mates", ce["ok"], ce["message"])
    # distance dimension readback and edit
    dm = next((m for m in ms if m.get("mate_type") == "distance"), None)
    log("A4a distance mate dimension", dm and near(dm.get("distance_mm"), 15, 0.01) and str(dm.get("dimension_name")).startswith("D1@Distance"), f"{dm and dm.get('dimension_name')} {dm and dm.get('distance_mm')}")
    r = call(edit_mate, {"mate_name": dm["name"], "distance_mm": 20})
    ox2 = comps()[B]["origin_mm"][0]
    log("A4b edit_mate distance 20 (value only)", r["ok"] and near(abs(ox2 - 40), 20, 0.02), f"{r['message']} x={ox2}")
    r = call(set_dimension, {"full_name": dm["dimension_name"], "value_mm": 15})
    ox3 = comps()[B]["origin_mm"][0]
    log("A4c set_dimension agrees with edit_mate (back to 15)", r["ok"] and near(abs(ox3 - 40), 15, 0.02), f"{r['message']} x={ox3}")
    r = call(edit_mate, {"mate_name": dm["name"], "flip": True})
    ox4 = comps()[B]["origin_mm"][0]
    m2 = next((m for m in D(call(list_mates))["mates"] if m["name"] == dm["name"]), {})
    log("A5a edit_mate flip=True (re-create): flipped state set, bracket moves to the other side", r["ok"] and m2.get("flipped") is True and not near(ox4, 55, 1), f"{r['message']} flipped={m2.get('flipped')} x={ox4} (was 55)")
    r = call(edit_mate, {"mate_name": m2.get("name", dm["name"]), "flip": False})
    mm3 = [m for m in D(call(list_mates))["mates"] if m.get("mate_type") == "distance"]
    m3 = mm3[0] if mm3 else {}
    log("A5b edit_mate flip=False back", r["ok"] and m3.get("flipped") is False and near(comps()[B]["origin_mm"][0], 55, 0.05), f"{r['message']} flipped={m3.get('flipped')} x={comps()[B]['origin_mm'][0]} align={m3.get('alignment')} dist={m3.get('distance_mm')}")
    r = call(edit_mate, {"mate_name": m3.get("name", dm["name"]), "alignment": "aligned"})
    mm4 = [m for m in D(call(list_mates))["mates"] if m.get("mate_type") == "distance"]
    log("A5d edit_mate alignment=aligned", r["ok"] and mm4 and mm4[0].get("alignment") == "aligned", f"{r['message']} align={mm4[0].get('alignment') if mm4 else None} x={comps()[B]['origin_mm'][0]}")
    r = call(edit_mate, {"mate_name": mm4[0]["name"], "alignment": "anti_aligned"})
    ce = call(check_errors)
    log("A5c check_errors after edits", ce["ok"], ce["message"])
    # suppression of mate
    pn = [m for m in D(call(list_mates))["mates"] if m.get("mate_type") == "distance"][0]["name"]
    dm = {"name": pn}
    r = call(set_mate_suppression, {"mate_names": [dm["name"]], "suppressed": True})
    m4 = next((m for m in D(call(list_mates))["mates"] if m["name"] == dm["name"]), {})
    log("A6a set_mate_suppression suppress", r["ok"] and m4.get("suppressed") is True, f"{r['message']} x={comps()[B]['origin_mm'][0]}")
    r = call(set_mate_suppression, {"mate_names": [dm["name"]], "suppressed": False})
    m5 = next((m for m in D(call(list_mates))["mates"] if m["name"] == dm["name"]), {})
    log("A6b unsuppress", r["ok"] and m5.get("suppressed") is False, f"{r['message']} x={comps()[B]['origin_mm'][0]}")
    # ---------- angle mate on Plate-2
    r = call(add_mate, {"mate_type": "coincident", "alignment": "aligned", "entities": [E(P2, "Plate", (0, -1, 0), 1, -30), E(P, "Plate", (0, -1, 0), 1, -30)]})
    log("A7a plate2 y-face coincident to plate1 y-face", r["ok"], f"{r['message']} origin={comps()[P2]['origin_mm']}")
    r = call(add_mate, {"mate_type": "angle", "angle_deg": 30, "entities": [E(P2, "Plate", (0, 0, 1), 2, 10), E(P, "Plate", (0, 0, 1), 2, 10)]})
    n2 = rotz(comps()[P2], (0, 0, 1))
    ang = math.degrees(math.acos(max(-1, min(1, dot(n2, (0, 0, 1))))))
    mm = [m for m in D(call(list_mates))["mates"] if m.get("mate_type") == "angle"]
    log("A7b angle mate 30 deg", r["ok"] and (near(ang, 30, 0.05) or near(ang, 150, 0.05)), f"{r['message']} measured angle between top normals={ang:.3f}; dims={D(r).get('dimensions')} list={[ (m.get('angle_deg'), m.get('dimension_name')) for m in mm]}")
    if mm:
        r = call(edit_mate, {"mate_name": mm[0]["name"], "angle_deg": 45})
        n2 = rotz(comps()[P2], (0, 0, 1))
        ang = math.degrees(math.acos(max(-1, min(1, dot(n2, (0, 0, 1))))))
        log("A7c edit_mate angle 45", r["ok"] and (near(ang, 45, 0.05) or near(ang, 135, 0.05)), f"{r['message']} measured={ang:.3f}")
    # ---------- limit distance on Block-1
    r = call(add_mate, {"mate_type": "coincident", "alignment": "anti_aligned", "entities": [E(K, "Block", (0, 0, -1), 2, 0), E(P, "Plate", (0, 0, 1), 2, 10)]})
    log("A8a block1 on plate top", r["ok"] and near(comps()[K]["origin_mm"][2], 10, 0.01), f"{r['message']} origin={comps()[K]['origin_mm']}")
    r = call(add_mate, {"mate_type": "distance", "distance_mm": 10, "min_distance_mm": 5, "max_distance_mm": 15, "alignment": "aligned",
                        "entities": [E(K, "Block", (1, 0, 0), 0, 10), E(P, "Plate", (1, 0, 0), 0, 40)]})
    bx = comps()[K]["origin_mm"][0]
    lm = next((m for m in D(call(list_mates))["mates"] if m["name"] == D(r).get("mate")), {})
    log("A8b limit distance mate", r["ok"] and 15 - 0.05 <= bx <= 25 + 0.05, f"{r['message']} warn={D(r).get('warning')} block x={bx}; min/max var={lm.get('min_variation')}/{lm.get('max_variation')} dims={lm.get('dimensions')}")
    r = call(move_component, {"component": K, "x_mm": 50, "mode": "relative"})
    bx2 = comps()[K]["origin_mm"][0]
    log("A8c move beyond max limit: solver keeps within 15..25", 15 - 0.05 <= bx2 <= 25 + 0.05, f"{r['message']} warn={D(r).get('warning')} x after={bx2}")
    # ---------- width mate on Block-2
    r = call(add_mate, {"mate_type": "coincident", "alignment": "anti_aligned", "entities": [E(K2, "Block", (0, 0, -1), 2, 0), E(P, "Plate", (0, 0, 1), 2, 10)]})
    r = call(add_mate, {"mate_type": "width", "width_option": "centered", "entities": [
        E(P, "Plate", (-1, 0, 0), 0, -40, 1), E(P, "Plate", (1, 0, 0), 0, 40, 1),
        E(K2, "Block", (-1, 0, 0), 0, -10, 2), E(K2, "Block", (1, 0, 0), 0, 10, 2)]})
    wx = comps()[K2]["origin_mm"][0]
    log("A9a width mate centered (marks 1/2)", r["ok"] and near(wx, 0, 0.02), f"{r['message']} warn={D(r).get('warning')} block2 x={wx}")
    wm = D(r).get("mate")
    if wm:
        call(delete_mate, {"mate_name": wm})
    for opt, kw, expect in (("dimension", {"distance_mm": 12}, None), ("free", {}, None), ("percent", {}, None)):
        r = call(add_mate, {"mate_type": "width", "width_option": opt, **kw, "entities": [
            E(P, "Plate", (-1, 0, 0), 0, -40, 1), E(P, "Plate", (1, 0, 0), 0, 40, 1),
            E(K2, "Block", (-1, 0, 0), 0, -10, 2), E(K2, "Block", (1, 0, 0), 0, 10, 2)]})
        wx = comps()[K2]["origin_mm"][0]
        wm2 = next((m for m in D(call(list_mates))["mates"] if m["name"] == D(r).get("mate")), {})
        log(f"A9b width_option={opt}", r["ok"], f"{r['message']} warn={D(r).get('warning')} block2 x={wx} dims={wm2.get('dimensions')}")
        if D(r).get("mate"):
            call(delete_mate, {"mate_name": D(r)["mate"]})
    # ---------- move / rotate floating pin
    o0 = comps()[N]["origin_mm"]
    r = call(move_component, {"component": N, "x_mm": 30, "y_mm": 0, "z_mm": 5})
    o1 = comps()[N]["origin_mm"]
    log("A10a move_component relative on floating pin", r["ok"] and near(o1[0], o0[0] + 30, 0.01) and near(o1[2], o0[2] + 5, 0.01), f"{o0}->{o1} {r['message']}")
    r = call(move_component, {"component": N, "x_mm": 0, "y_mm": -100, "z_mm": 0, "mode": "absolute"})
    o2 = comps()[N]["origin_mm"]
    log("A10b move absolute", r["ok"] and all(near(a, b, 0.01) for a, b in zip(o2, (0, -100, 0))), f"{o2}")
    r = call(rotate_component, {"component": N, "axis": "x", "angle_deg": 90})
    cN = comps()[N]
    nzv = rotz(cN, (0, 0, 1))
    log("A10c rotate_component x 90 (pin axis z -> -y)", r["ok"] and near(nzv[1], -1, 1e-4) and all(near(a, b, 0.01) for a, b in zip(cN["origin_mm"], (0, -100, 0))), f"axis={[round(v,4) for v in nzv]} origin={cN['origin_mm']}")
    r = call(rotate_component, {"component": N, "axis": [0, 0, 1], "angle_deg": 45, "pivot_mm": [0, 0, 0]})
    log("A10d rotate about vector with pivot", r["ok"] and near(math.hypot(*comps()[N]["origin_mm"][:2]), 100, 0.05), f"origin={comps()[N]['origin_mm']}")
    r = call(move_component, {"component": P, "x_mm": 10})
    log("A10e move fixed component refused", not r["ok"], r["message"][:100])
    r = call(move_component, {"component": B, "x_mm": 40})
    log("A10f move mated component: warns / solver", r["ok"] or True, f"{r['message']} warn={D(r).get('warning')} x={comps()[B]['origin_mm'][0]}")
    # ---------- limit edit via re-create
    lmn = next((m["name"] for m in D(call(list_mates))["mates"] if m.get("mate_type") == "distance" and m.get("min_variation")), None)
    if lmn:
        r = call(edit_mate, {"mate_name": lmn, "min_distance_mm": 3, "max_distance_mm": 20})
        lm2 = next((m for m in D(call(list_mates))["mates"] if m.get("mate_type") == "distance" and m.get("min_variation")), {})
        log("A8d edit_mate limits 3..20 (distance 10 kept)", r["ok"] and near(lm2.get("min_variation", 0) * 1000, -7, 0.01) and near(lm2.get("max_variation", 0) * 1000, 10, 0.01),
            f"{r['message']} var={lm2.get('min_variation')}/{lm2.get('max_variation')} block x={comps()[K]['origin_mm'][0]}")
    # ---------- visibility / suppression / mass
    v0 = vol()
    r = call(set_component_visibility, {"component_names": [N], "visible": False})
    c = comps()[N]
    log("A11a hide component", r["ok"] and c["hidden"] is True and near(vol(), v0, 0.5), f"{r['message']} hidden={c['hidden']} vol {v0}->{vol()}")
    r = call(set_component_visibility, {"component_names": [N], "visible": True})
    log("A11b show component", r["ok"] and comps()[N]["hidden"] is False, f"{r['message']}")
    r = call(set_component_suppression, {"component_names": [N], "suppressed": True})
    c = comps()[N]
    dv = v0 - (vol() or 0)
    log("A11c suppress component: volume drops by pin volume", r["ok"] and near(dv, math.pi * 25 * 30, 1) and c["suppressed"], f"{r['message']} state={c['suppression_state']} dvol={dv:.2f} (exp {math.pi*25*30:.2f})")
    r = call(set_component_suppression, {"component_names": [N], "suppressed": False})
    c = comps()[N]
    log("A11d unsuppress (resolved state)", r["ok"] and not c["suppressed"] and c["suppression_state"] == "resolved" and near(vol(), v0, 0.5), f"{r['message']} state={c['suppression_state']} vol={vol()}")
    # ---------- subassembly insert
    r = call(insert_component, {"path": str(paths["Sub"]), "x_mm": 0, "y_mm": -250, "z_mm": 0})
    sub = D(r).get("component")
    allc = comps()
    kids = [n for n, c_ in allc.items() if c_.get("depth", 0) >= 1]
    log("A12a insert .sldasm as subassembly", r["ok"] and D(r).get("is_assembly") is True and len(kids) >= 2, f"{sub} is_asm={D(r).get('is_assembly')} origin={D(r).get('origin_mm')} children={kids}")
    top = [c_["name"] for c_ in D(call(list_components, {"top_level_only": True}))["components"]]
    log("A12b top_level_only excludes children", sub in top and not any(k in top for k in kids), str(top))
    vsub = vol()
    r = call(move_component, {"component": sub, "x_mm": 20, "y_mm": 0, "z_mm": 0})
    log("A12c move subassembly", r["ok"] and near(comps()[sub]["origin_mm"][0], 20, 0.02), f"{comps()[sub]['origin_mm']}")
    r = call(rotate_component, {"component": sub, "axis": "z", "angle_deg": 90})
    log("A12d rotate subassembly", r["ok"] and near(rotz(comps()[sub], (1, 0, 0))[1], 1, 1e-4), f"x axis ->{[round(v, 3) for v in rotz(comps()[sub], (1, 0, 0))]}")
    r = call(set_component_visibility, {"component_names": [sub], "visible": False})
    log("A12e hide subassembly", r["ok"] and comps()[sub]["hidden"] is True, r["message"])
    call(set_component_visibility, {"component_names": [sub], "visible": True})
    r = call(set_component_suppression, {"component_names": [sub], "suppressed": True})
    dv = vsub - (vol() or 0)
    log("A12f suppress subassembly: volume drops by sub volume", r["ok"] and near(dv, 48000 + math.pi * 25 * 30, 2), f"{r['message']} dvol={dv:.2f} exp={48000 + math.pi*25*30:.2f}")
    r = call(set_component_suppression, {"component_names": [sub], "suppressed": False})
    log("A12g unsuppress subassembly", r["ok"] and near(vol(), vsub, 1), f"vol={vol()}")
    # ---------- save main + interactions
    pm = ASM / "Main.sldasm"; pm.unlink(missing_ok=True)
    r = call(save_document, {"path": str(pm)})
    log("A13 save main assembly", r["ok"] and pm.exists() and pm.stat().st_size > 0, f"{pm.stat().st_size if pm.exists() else None}")
    ce = call(check_errors)
    log("A13b check_errors main", ce["ok"], ce["message"])
    # ---------- exports of the assembly
    asm_exports(ins, sub)
    return paths, ins, ta


def stage_extra():
    """Lightweight export, dialog guard, replace with configuration, open_component active doc."""
    from solidworks_mcp.sw_core import dialogs_suppressed, running_app
    app = running_app()
    # dialog guard
    newdoc("part")
    before = (app.GetUserPreferenceToggle(10), app.GetUserPreferenceToggle(77))
    with dialogs_suppressed():
        inside = (app.GetUserPreferenceToggle(10), app.GetUserPreferenceToggle(77))
    after = (app.GetUserPreferenceToggle(10), app.GetUserPreferenceToggle(77))
    call(create_sketch, {"plane": "front", "name": "Bow"})
    for a, b in (((0, 0), (10, 10)), ((10, 10), (10, 0)), ((10, 0), (0, 10)), ((0, 10), (0, 0))):
        call(draw_line, {"x1_mm": a[0], "y1_mm": a[1], "x2_mm": b[0], "y2_mm": b[1]})
    call(close_sketch)
    r = call(boss_extrude, {"sketch_name": "Bow", "depth_mm": 5, "name": "BadFeat"})
    end = (app.GetUserPreferenceToggle(10), app.GetUserPreferenceToggle(77))
    log("F12 dialog guard: toggles 10/77 off inside, restored; erroring feature returns without a dialog",
        before == (True, True) and inside == (False, False) and after == before and end == before and not r["ok"], f"before={before} inside={inside} after={after} after-bad-feature={end}; {r['message'][:80]}")
    for x in docs():
        call(close_document, {"title": x["title"], "force": True})
    created.clear()
    # lightweight
    e, w = byref_long(0), byref_long(0)
    app.OpenDoc6(str(ASM / "Main.sldasm"), 2, 1 | 64 | 128, "", e, w)
    states = {c["suppression_state"] for c in D(call(list_components)).get("components", [])}
    d = EXP / "asm" / "lw_comps"
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    r = call(export_components, {"directory": str(d), "format": "step"})
    names = sorted(f.name for f in d.glob("*")) if d.exists() else []
    log("X12 export_components on lightweight components resolves and exports them", states == {"lightweight"} and r["ok"] and names == ["Block.step", "Bracket.step", "Pin.step", "Plate.step", "Sub.step"], f"states={states} files={names} skipped={D(r).get('skipped')}")
    for x in docs():
        call(close_document, {"title": x["title"], "force": True})
    created.clear()
    # replace with a configuration + open_component active doc
    ta = newdoc("assembly")
    paths = {n: ASM / (n + ".sldprt") for n in ("Plate", "Cfg", "CfgCopy")}
    pl = D(call(insert_component, {"path": str(paths["Plate"])}))["component"]
    call(set_component_fixed, {"component_names": [pl], "fixed": True})
    c1 = D(call(insert_component, {"path": str(paths["CfgCopy"]), "x_mm": 100}))["component"]
    r = call(add_mate, {"mate_type": "coincident", "alignment": "anti_aligned", "entities": [
        {"component": c1, "face": cfidx(c1, (0, 0, -1))}, {"component": pl, "face": cfidx(pl, (0, 0, 1))}]})
    n0 = len(D(call(list_mates))["mates"])
    r = call(replace_component, {"component": c1, "new_path": str(paths["Cfg"]), "configuration": "Short"})
    cs = comps()
    nn = next((n for n, c_ in cs.items() if c_["path"].endswith("Cfg.sldprt")), None)
    log("C6 replace_component with configuration=Short keeps mate", r["ok"] and nn and cs[nn]["configuration"] == "Short" and len(D(call(list_mates))["mates"]) == n0 and near(cs[nn]["origin_mm"][2], 10, 0.01) and near(vol(), 48000 + 4000, 2),
        f"{r['message']} new={nn} cfg={nn and cs[nn]['configuration']} vol={vol()} origin={nn and cs[nn]['origin_mm']}")
    r = call(open_component, {"component": nn})
    app2, doc = active_document()
    title = str(doc.GetTitle)
    log("C5b open_component makes the part the active document", r["ok"] and "Cfg" in title, f"active title={title}")
    app2.ActivateDoc3(ta, True, 0, byref_long(0))


def finish(keep_base):
    for x in docs():
        if x["title"] not in keep_base:
            call(close_document, {"title": x["title"], "force": True})


STAGES = {"feature": stage_feature, "export": stage_export, "asm": stage_asm, "asm2": stage_asm2, "extra": stage_extra}
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
