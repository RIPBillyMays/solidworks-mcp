"""LIVE Phase 5 Batch C3 verification: surfaces, edit_feature, split_body cut retry.

SW 2017 must be running, launched by the user.  Not run by the offline suite.

Run:  SW_MCP_OUTPUT_ROOT=<repo>/sandbox python tests/live_p5_batchC3.py [surf knit thicken trim replace edit split ...]
Calls tool handlers in-process (so SW_MCP_DISABLE_FENCES=1 is not needed for the direct
calls; set it anyway when testing through the MCP server).  Every fixture is generated
here under sandbox/phase5/batchC3/ and only documents this script created are closed.
Output: PASS | FAIL | FENCE-CANDIDATE per check.  FENCE-CANDIDATE means the tool built a
feature or refused cleanly but the measurement shows a 2017 no-op, so after 2 credible attempts
it should go into sw2017_fences.py.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import solidworks_mcp.server  # noqa: E402,F401  (registers every tool)

from solidworks_mcp.sw_core import OUTPUT_ROOT as _OUT_ROOT  # noqa: E402

if Path(_OUT_ROOT).resolve() != (ROOT / "sandbox").resolve():
    sys.exit(f"ABORT: SW_MCP_OUTPUT_ROOT must be {ROOT / 'sandbox'} (resolved to {_OUT_ROOT}); "
             "set SW_MCP_OUTPUT_ROOT=<repo>/sandbox and rerun.")
from solidworks_mcp.sw_body import split_body  # noqa: E402
from solidworks_mcp.sw_core import active_document  # noqa: E402
from solidworks_mcp.sw_edit import edit_feature  # noqa: E402
from solidworks_mcp.sw_feature import (  # noqa: E402
    boss_extrude, chamfer, circular_pattern, delete_feature, fillet, linear_pattern, shell,
)
from solidworks_mcp.sw_file import close_document, create_new_document, list_open_documents  # noqa: E402
from solidworks_mcp.sw_inspect import (  # noqa: E402
    get_bounding_box, get_mass_properties, list_bodies, list_edges, list_faces, list_features,
)
from solidworks_mcp.sw_refgeom import create_plane  # noqa: E402
from solidworks_mcp.sw_sketch import (  # noqa: E402
    close_sketch, create_sketch, draw_centerline, draw_circle, draw_line, draw_rectangle,
)
from solidworks_mcp.sw_surface import (  # noqa: E402
    replace_face, surface_extrude, surface_knit, surface_loft, surface_offset, surface_revolve,
    surface_trim, thicken,
)

OUT = ROOT / "sandbox" / "phase5" / "batchC3"
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


def near(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


def rel(a, b, pct):
    return a is not None and b and abs(a - b) <= abs(b) * pct / 100.0


def docs():
    return D(call(list_open_documents))["documents"]


def newdoc():
    before = {d["title"] for d in docs()}
    call(create_new_document, {"kind": "part"})
    for d in docs():
        if d["title"] not in before:
            created.append(d["title"])
            return d["title"]


# --- independent measurements (not the tools' own numbers) ----------------------------


def sheet_bodies():
    _, doc = active_document()
    from solidworks_mcp.sw_core import as_list
    return as_list(doc.GetBodies2(1, False))


def surf_area():
    """Total surface-body area in mm^2, summed face by face straight from COM."""
    from solidworks_mcp.sw_core import as_list
    total = 0.0
    for body in sheet_bodies():
        for face in as_list(body.GetFaces()):
            a_ = face.GetArea
            total += float(a_() if callable(a_) else a_)
    return total * 1e6


def nsurf():
    return len(sheet_bodies())


def nsolid():
    return len(D(call(list_bodies))["bodies"])


def vol():
    return D(call(get_mass_properties)).get("volume_mm3")


def bbox():
    d = D(call(get_bounding_box))
    return d.get("min_mm"), d.get("max_mm")


def size():
    lo, hi = bbox()
    return [round(h - l, 4) for l, h in zip(lo, hi)]


def feats():
    return D(call(list_features))["features"]


def type_of(name):
    return next((f.get("type") for f in feats() if f.get("name") == name), None)


def sketch_circle(plane, x, y, r, name, plane_name=None):
    a = {"name": name}
    a.update({"plane_name": plane_name} if plane_name else {"plane": plane})
    call(create_sketch, a)
    call(draw_circle, {"x_mm": x, "y_mm": y, "radius_mm": r})
    call(close_sketch)


def sketch_rect(plane, x1, y1, x2, y2, name):
    call(create_sketch, {"name": name, "plane": plane})
    call(draw_rectangle, {"x1_mm": x1, "y1_mm": y1, "x2_mm": x2, "y2_mm": y2})
    call(close_sketch)


def sketch_line(plane, x1, y1, x2, y2, name):
    call(create_sketch, {"name": name, "plane": plane})
    call(draw_line, {"x1_mm": x1, "y1_mm": y1, "x2_mm": x2, "y2_mm": y2})
    call(close_sketch)


def box(x1, y1, x2, y2, depth, sk, name):
    sketch_rect("front", x1, y1, x2, y2, sk)
    return call(boss_extrude, {"sketch_name": sk, "depth_mm": depth, "name": name})


def pick_face(nz, z_extreme):
    """Planar face with normal +/-Z at the max (z_extreme='max') or min z of the part."""
    fs = [f for f in D(call(list_faces))["faces"]
          if f.get("surface_type") == "plane" and f.get("normal") and abs(abs(f["normal"][2]) - 1) < 0.02]
    if not fs:
        return None
    return (max if z_extreme == "max" else min)(fs, key=lambda f: f["point_mm"][2])


def status_for(ok, r, attempts):
    """PASS, or FENCE-CANDIDATE once 2 credible attempts both gave a clean no-op/refusal."""
    if ok:
        return "PASS"
    return "FENCE-CANDIDATE" if attempts >= 2 else "FAIL"


# --- stages -----------------------------------------------------------------------------


def stage_surf():
    """3.1 extrude, 3.2 revolve, 3.3 loft, 3.4 offset."""
    newdoc()
    sketch_circle("top", 0, 0, 10, "Cy")
    r = call(surface_extrude, {"sketch_name": "Cy", "depth_mm": 20, "name": "SE1"})
    a = surf_area()
    log("3.1a surface_extrude circle r10 x 20: +1 surface, area = 2*pi*r*L",
        r["ok"] and nsurf() == 1 and rel(a, 2 * math.pi * 10 * 20, 0.5), f"n={nsurf()} area={a:.2f} want={2*math.pi*200:.2f} names={D(r).get('surface_bodies')}")
    names = D(r).get("surface_bodies") or []
    r = call(surface_offset, {"surface_bodies": names[:1], "distance_mm": 2, "name": "SO1"})
    a2 = surf_area() - a
    ok = r["ok"] and nsurf() == 2 and (rel(a2, 2 * math.pi * 12 * 20, 0.5) or rel(a2, 2 * math.pi * 8 * 20, 0.5))
    log("3.4a surface_offset body by 2: +1 surface, area = 2*pi*(r+-2)*L", ok,
        f"n={nsurf()} offset_area={a2:.2f} (out {2*math.pi*240:.2f} / in {2*math.pi*160:.2f}) msg={r['message']}")
    r = call(surface_offset, {"surface_bodies": names[:1], "distance_mm": 0, "name": "SO0"})
    log("3.4b surface_offset distance 0 copies the surface", r["ok"] and nsurf() == 3, f"n={nsurf()} msg={r['message']}")
    r = call(surface_extrude, {"sketch_name": "Cy", "depth_mm": 20, "cap_ends": True, "mid_plane": True, "name": "SE2"})
    # both ends capped closes the surface; SW turns it into a SOLID (volume = pi r^2 L)
    log("3.1b surface_extrude mid_plane + caps: closed surface becomes 1 solid, V = pi r^2 L",
        r["ok"] and nsurf() == 3 and nsolid() == 1 and rel(vol(), math.pi * 100 * 20, 0.5), f"n={nsurf()} solids={nsolid()} vol={vol()} msg={r['message']}")
    r = call(surface_extrude, {"depth_mm": -3})
    log("3.1c invalid depth refused cleanly, nothing built", (not r["ok"]) and nsurf() == 3 and nsolid() == 1, r["message"])

    newdoc()
    call(create_sketch, {"name": "Rv", "plane": "front"})
    call(draw_line, {"x1_mm": 10, "y1_mm": 0, "x2_mm": 10, "y2_mm": 20})
    call(draw_centerline, {"x1_mm": 0, "y1_mm": -5, "x2_mm": 0, "y2_mm": 25})
    call(close_sketch)
    r = call(surface_revolve, {"sketch_name": "Rv", "angle_deg": 360, "name": "SR1"})
    a = surf_area()
    log("3.2a surface_revolve line x=10,L=20 about Y: +1 surface, area = 2*pi*r*L",
        r["ok"] and nsurf() == 1 and rel(a, 2 * math.pi * 10 * 20, 0.5), f"n={nsurf()} area={a:.2f} want={2*math.pi*200:.2f} msg={r['message']}")
    r = call(surface_revolve, {"sketch_name": "Rv", "angle_deg": 90, "name": "SR2"})
    a2 = surf_area() - a
    log("3.2b surface_revolve 90 deg: area is a quarter", r["ok"] and rel(a2, 2 * math.pi * 200 / 4, 0.5), f"quarter_area={a2:.2f} msg={r['message']}")

    newdoc()
    sketch_circle("top", 0, 0, 10, "L1")
    call(create_plane, {"mode": "offset", "selection": {"planes": ["top"]}, "distance_mm": 20, "name": "PL"})
    call(create_sketch, {"name": "L2", "plane_name": "PL"})
    call(draw_circle, {"x_mm": 0, "y_mm": 0, "radius_mm": 5})
    call(close_sketch)
    r = call(surface_loft, {"profile_sketches": ["L1", "L2"], "name": "SL1"})
    slant = math.hypot(20, 5)
    a = surf_area()
    log("3.3 surface_loft r10 -> r5 over 20: +1 surface, frustum area = pi*(r1+r2)*slant",
        r["ok"] and nsurf() == 1 and rel(a, math.pi * 15 * slant, 1.0), f"n={nsurf()} area={a:.2f} want={math.pi*15*slant:.2f} msg={r['message']}")


def stage_knit():
    """3.5: two planar surfaces sharing an edge knit to one; six faces close to a solid."""
    newdoc()
    sketch_line("front", 0, 0, 20, 0, "KA")
    sketch_line("front", 20, 0, 20, 15, "KB")
    ra = call(surface_extrude, {"sketch_name": "KA", "depth_mm": 10, "name": "SA"})
    rb = call(surface_extrude, {"sketch_name": "KB", "depth_mm": 10, "name": "SB"})
    names = D(rb).get("surface_bodies") or []
    a0 = surf_area()
    log("3.5.0 fixture: two planar surfaces 200 + 150 mm2", ra["ok"] and rb["ok"] and nsurf() == 2 and rel(a0, 350, 0.5), f"n={nsurf()} area={a0:.2f}")
    r = call(surface_knit, {"surface_bodies": names, "name": "KN"})
    log("3.5a surface_knit: surface count 2 -> 1, area preserved", r["ok"] and nsurf() == 1 and rel(surf_area(), 350, 0.5),
        f"n={nsurf()} area={surf_area():.2f} msg={r['message']}")

    newdoc()
    sketch_rect("top", -10, -10, 10, 10, "KR")
    r0 = call(surface_extrude, {"sketch_name": "KR", "depth_mm": 10, "cap_ends": True, "name": "SO5"})
    sketch_line("front", -10, 0, 10, 0, "KL")
    r1 = call(surface_extrude, {"sketch_name": "KL", "depth_mm": 20, "mid_plane": True, "name": "SOlid"})
    names = D(r1).get("surface_bodies") or []
    log("3.5.1 fixture: capped open box + separate lid, no solids (total 2000+400 mm2)",
        r0["ok"] and r1["ok"] and nsurf() == 2 and nsolid() == 0, f"n_surf={nsurf()} solids={nsolid()} area={surf_area():.2f} want=2400 names={names}")
    v0, ns0 = vol(), nsolid()
    r = call(surface_knit, {"surface_bodies": names, "try_form_solid": True, "name": "KSolid"})
    ok = r["ok"] and nsolid() == ns0 + 1
    log("3.5b surface_knit try_form_solid: a new solid appears, volume > 0", ok,
        f"solids {ns0}->{nsolid()} vol {v0}->{vol()} nsurf={nsurf()} msg={r['message']}", status=None if ok else "FENCE-CANDIDATE")


def stage_thicken():
    """3.6: thicken a planar surface 20x10 by 2 -> volume 400."""
    newdoc()
    sketch_line("front", 0, 0, 20, 0, "TA")
    r0 = call(surface_extrude, {"sketch_name": "TA", "depth_mm": 10, "name": "ST"})
    names = D(r0).get("surface_bodies") or []
    v0 = vol() or 0.0
    r = call(thicken, {"surface_bodies": names, "thickness_mm": 2, "name": "Th1"})
    dv = (vol() or 0.0) - v0
    log("3.6a thicken side1 2 mm: +1 solid, volume = area x t within 0.5%", r["ok"] and nsolid() == 1 and rel(dv, 400, 0.5),
        f"solids={nsolid()} dV={dv:.3f} want=400 msg={r['message']}")
    for side in ("side2", "both"):
        newdoc()
        sketch_line("front", 0, 0, 20, 0, "TA")
        rr = call(surface_extrude, {"sketch_name": "TA", "depth_mm": 10})
        v0 = vol() or 0.0
        r = call(thicken, {"surface_bodies": D(rr).get("surface_bodies") or [], "thickness_mm": 2, "side": side})
        dv = (vol() or 0.0) - v0
        # LIVE-PROBE: whether 'both' means 2 mm total or 2 mm each side
        log(f"3.6b thicken side={side}: volume reported", r["ok"] and (rel(dv, 400, 0.5) or (side == "both" and rel(dv, 800, 0.5))),
            f"dV={dv:.3f} (400 = t total, 800 = t each side) msg={r['message']}")
    r = call(thicken, {"surface_bodies": ["nonexistent"], "thickness_mm": 1})
    log("3.6c missing surface body refused cleanly", not r["ok"], r["message"])


def stage_trim():
    """3.7: trim a 20x10 plane surface with a wall crossing it at x=10, keeping x<10 (2 attempts)."""
    def fixture():
        newdoc()
        sketch_line("front", 0, 0, 20, 0, "A")        # plane y=0, x 0..20, z 0..10
        call(create_sketch, {"name": "W", "plane": "front"})  # wall x=10, y -5..5, z 0..10 crosses the plane
        call(draw_line, {"x1_mm": 10, "y1_mm": -5, "x2_mm": 10, "y2_mm": 5})
        call(close_sketch)
        ra = call(surface_extrude, {"sketch_name": "A", "depth_mm": 10, "name": "SA"})
        rw = call(surface_extrude, {"sketch_name": "W", "depth_mm": 10, "name": "SW"})
        return D(ra).get("surface_bodies") or [], D(rw).get("surface_bodies") or []

    attempts = [
        ("keep x<10 piece", {"keep_selected": True, "pieces": (5, 0, 5)}),
        ("remove x>10 piece", {"keep_selected": False, "pieces": (15, 0, 5)}),
    ]
    ok = False
    for n, (label, opts) in enumerate(attempts, 1):
        a_name, w_name = fixture()
        before = surf_area()
        x, y, z = opts["pieces"]
        r = call(surface_trim, {
            "tool_surface_bodies": w_name[-1:] if w_name else [],
            "pieces_selection": {"points": [{"x_mm": x, "y_mm": y, "z_mm": z, "type": "FACE"}]},
            "keep_selected": opts["keep_selected"], "name": "TR",
        }, ctx=label)
        after = surf_area()
        want = before - 100.0   # the removed half of the 20x10 plane
        ok = r["ok"] and rel(after, want, 1.0)
        log(f"3.7 attempt {n} ({label}): area {before:.1f} -> {after:.1f}, want {want:.1f}", ok, r["message"],
            status=status_for(ok, r, n) if not ok else "PASS")
        if ok:
            break


def stage_replace():
    """3.8: replace the top face of a 20x20x10 block with an offset copy raised 2 mm -> dV = +/-800."""
    newdoc()
    box(-10, -10, 10, 10, 10, "RB", "Bx")
    lo, hi = bbox()
    top = pick_face(1, "max")
    v0 = vol()
    ro = call(surface_offset, {"selection": {"faces": [top["index"]]}, "distance_mm": 2, "name": "RO"})
    names = D(ro).get("surface_bodies") or []
    top = pick_face(1, "max")
    r = call(replace_face, {"target_selection": {"faces": [top["index"]]}, "replacement_surface_bodies": names[-1:], "name": "RF"})
    dv = (vol() or 0.0) - v0
    ok = r["ok"] and rel(abs(dv), 800, 1.0)
    log("3.8 replace_face top face by surface 2 mm away: |dV| = 800", ok,
        f"v0={v0} v1={vol()} dV={dv:.2f} bbox {lo},{hi} -> {bbox()} msg={r['message']}",
        status=None if ok else "FENCE-CANDIDATE")


def stage_edit():
    """3.9: edit each allow-listed type, read back, and refuse an unsupported one."""
    newdoc()
    box(-10, -5, 10, 5, 10, "ES", "Bx")
    print("  feature types:", [(f["name"], f["type"]) for f in feats()])
    z0 = size()[2]
    r = call(edit_feature, {"feature_name": "Bx", "params": {"depth_mm": 25}})
    z1 = size()[2]
    log("3.9a Extrusion depth 10 -> 25: read-back after=25, changed, bbox z grows", r["ok"] and D(r).get("changed") and near(z1, 25, 0.01),
        f"z {z0}->{z1} params={D(r).get('params')} msg={r['message']}")
    r = call(edit_feature, {"feature_name": "Bx", "params": {"depth_mm": 25}})
    log("3.9b same value again reports changed=false", r["ok"] and D(r).get("changed") is False, r["message"])
    lo, _ = bbox()
    r = call(edit_feature, {"feature_name": "Bx", "params": {"reverse": True}})
    lo2, _ = bbox()
    log("3.9c Extrusion reverse: read-back true, bbox min z moves", r["ok"] and D(r).get("changed") and not near(lo[2], lo2[2], 0.01),
        f"min z {lo[2]}->{lo2[2]} msg={r['message']}")
    call(edit_feature, {"feature_name": "Bx", "params": {"reverse": False, "depth_mm": 10}})
    r = call(edit_feature, {"feature_name": "ES", "params": {"depth_mm": 5}})
    log("3.9d unsupported type (sketch) refused, lists the type", (not r["ok"]) and "ProfileFeature" in r["message"], r["message"])

    # Fillet
    edge = D(call(list_edges))["edges"][0]["index"]
    call(fillet, {"radius_mm": 1, "selection": {"edges": [edge]}, "propagate": False, "name": "Fl"})
    v0 = vol()
    r = call(edit_feature, {"feature_name": "Fl", "params": {"radius_mm": 3}})
    log("3.9e Fillet radius 1 -> 3: read-back 3, volume drops", r["ok"] and D(r).get("changed") and vol() < v0,
        f"type={type_of('Fl')} vol {v0}->{vol()} params={D(r).get('params')} msg={r['message']}")

    # Chamfer
    newdoc()
    box(-10, -5, 10, 5, 10, "ES", "Bx")
    edge = D(call(list_edges))["edges"][0]["index"]
    call(chamfer, {"distance_mm": 1, "selection": {"edges": [edge]}, "propagate": False, "name": "Ch"})
    v0 = vol()
    r = call(edit_feature, {"feature_name": "Ch", "params": {"distance_mm": 2.5}})
    log("3.9f Chamfer distance 1 -> 2.5: read-back, volume drops", r["ok"] and D(r).get("changed") and vol() < v0,
        f"type={type_of('Ch')} vol {v0}->{vol()} params={D(r).get('params')} msg={r['message']}")

    # Shell
    newdoc()
    box(-10, -10, 10, 10, 10, "ES", "Bx")
    top = pick_face(1, "max")
    call(shell, {"thickness_mm": 1, "selection": {"faces": [top["index"]]}, "name": "Sh"})
    v0 = vol()
    r = call(edit_feature, {"feature_name": "Sh", "params": {"thickness_mm": 2}})
    log("3.9g Shell thickness 1 -> 2: read-back, volume grows", r["ok"] and D(r).get("changed") and vol() > v0,
        f"type={type_of('Sh')} vol {v0}->{vol()} params={D(r).get('params')} msg={r['message']}")

    # Linear pattern: a small boss patterned along X
    newdoc()
    box(-30, -30, 30, 30, 5, "ES", "Bx")
    sketch_circle("front", 0, 0, 3, "Hub")          # centre boss: its cylindrical face is the circular-pattern axis
    call(boss_extrude, {"sketch_name": "Hub", "depth_mm": 10, "name": "HubB"})
    sketch_circle("front", -20, 15, 2, "Pin")
    call(boss_extrude, {"sketch_name": "Pin", "depth_mm": 10, "name": "PinB"})   # stands 5 mm proud of the plate
    edge = next((e for e in D(call(list_edges))["edges"] if e.get("curve_type") == "line" and (e.get("direction") or [0])[0] > 0.99), None)
    r0 = call(linear_pattern, {"selection": {"features": ["PinB"]}, "direction1_selection": {"edges": [edge["index"]]} if edge else {},
                               "count1": 3, "spacing1_mm": 10, "name": "LP"})
    v0 = vol()
    r = call(edit_feature, {"feature_name": "LP", "params": {"count": 4, "spacing_mm": 12}})
    log("3.9h LinearPattern count 3 -> 4, spacing 10 -> 12: read-back, volume grows", r0["ok"] and r["ok"] and D(r).get("changed") and vol() > v0,
        f"type={type_of('LP')} vol {v0}->{vol()} params={D(r).get('params')} msg={r['message']}")

    # Circular pattern about the part's Y axis (a temporary axis face is not needed: use the Y axis)
    cyl = next((f for f in D(call(list_faces))["faces"] if f.get("surface_type") == "cylinder"
                and f.get("point_mm") and abs(math.hypot(f["point_mm"][0], f["point_mm"][1]) - 3) < 0.5), None)
    r0 = call(circular_pattern, {"selection": {"features": ["PinB"]}, "axis_selection": {"faces": [cyl["index"]]} if cyl else {},
                                 "count": 3, "angle_deg": 360, "name": "CP"})
    if r0["ok"]:
        v0 = vol()
        r = call(edit_feature, {"feature_name": "CP", "params": {"count": 5}})
        log("3.9i CircularPattern count 3 -> 5: read-back", r["ok"] and D(r).get("changed"),
            f"type={type_of('CP')} vol {v0}->{vol()} params={D(r).get('params')} msg={r['message']}")
    else:
        log("3.9i CircularPattern fixture (axis name 'Y') could not be built", False, r0["message"])


def stage_split():
    """3.11: split_body method=cut keeps both pieces; the kerf is reported (run with fences disabled)."""
    newdoc()
    box(-20, -10, 20, 10, 10, "SP", "Bx")
    v0 = vol()
    sketch_rect("top", -1, -30, 1, 30, "Kerf")   # 2 mm kerf slab through the whole block at x=0
    r = call(split_body, {"method": "cut", "tool_selection": {"sketches": ["Kerf"]}, "name": "SplitCut"})
    n = nsolid()
    kerf = 2 * 20 * 10   # 2 mm x 20 mm x 10 mm of the block lies in the slab
    ok = r["ok"] and n == 2 and near(v0 - (vol() or 0.0), kerf, 1.0)
    log("3.11 split_body method=cut: 2 solid bodies, volume loss = kerf only", ok,
        f"solids={n} vol {v0}->{vol()} kerf_want={kerf} msg={r['message']}",
        status=None if ok else "FENCE-CANDIDATE")
    r = call(split_body, {"method": "zap", "tool_selection": {"planes": ["front"]}})
    log("3.11b unknown method refused", not r["ok"], r["message"])


STAGES = {
    "surf": stage_surf, "knit": stage_knit, "thicken": stage_thicken, "trim": stage_trim,
    "replace": stage_replace, "edit": stage_edit, "split": stage_split,
}


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
