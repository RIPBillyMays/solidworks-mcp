# Copyright 2026 JIALE LIU
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

# Added for SOLIDWORKS 2017 support (fork): Phase 3 live smoke test.

"""Live SOLIDWORKS 2017 smoke test, ordered by the tool catalog's build-up sequence.

Run only against a SOLIDWORKS that Zach launched, with no documents open:

    $env:SW_MCP_OUTPUT_ROOT="C:\\_Projects\\solidworks-mcp\\sandbox"
    .venv\\Scripts\\python.exe tests\\live_sw2017_smoke.py

Design rules (ADR-0005 and the Phase 3 brief):

* Every case calls the tool HANDLER (same code path as MCP) and then checks the
  result by MEASUREMENT (volume, face count, file size, mate count ...), never
  by "no exception".  A handler that says ok while the measurement disagrees is
  a SILENT-FAIL.
* One failing case never aborts the run; cases that depend on it become SKIP.
* COM is apartment-threaded, so a hang cannot be interrupted in-process.  Each
  case runs under a 60 s threading.Timer that dumps the partial results and
  ``os._exit(2)``.  Results JSON is rewritten after every case.
* All files go under ``sandbox\\run-<timestamp>\\``.  Nothing outside sandbox is
  opened, saved or touched.  SOLIDWORKS is never started or quit.
* The script must not be collected by ``unittest discover`` (name does not
  match ``test*.py``) and does nothing on import.
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "sandbox"

# The output-root guard reads this at import time, so it has to come first.
os.environ["SW_MCP_OUTPUT_ROOT"] = str(SANDBOX)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WATCHDOG_SECONDS = 60.0

# ---------------------------------------------------------------------------
# Result bookkeeping
# ---------------------------------------------------------------------------

PASS, FAIL, SILENT, HANG, SKIP, UNVERIFIED = "PASS", "FAIL", "SILENT-FAIL", "HANG", "SKIP", "UNVERIFIED"
GOOD = {PASS, UNVERIFIED}


class Fail(Exception):
    """The handler reported failure or raised."""


class Silent(Exception):
    """The handler said ok but the measurement disagrees."""


class Unverified(Exception):
    """The handler said ok and no independent measurement was possible."""


RESULTS: list[dict[str, Any]] = []
STATUS_BY_CASE: dict[str, str] = {}
X: dict[str, Any] = {"docs": [], "notes": []}
RUN_DIR: Path = SANDBOX
_current: dict[str, Any] = {"name": None}


def _dump() -> None:
    try:
        payload = {
            "meta": X.get("meta", {}),
            "notes": X["notes"],
            "results": RESULTS,
        }
        (RUN_DIR / "results.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _on_hang(name: str, tools: list[str]) -> None:
    RESULTS.append({
        "case": name, "tools": tools, "status": HANG, "evidence": "",
        "note": f"No return within {WATCHDOG_SECONDS:.0f} s; most likely a modal dialog in SOLIDWORKS.",
        "seconds": WATCHDOG_SECONDS,
    })
    _dump()
    print(f"HANG in {name}", flush=True)
    os._exit(2)


def step(name: str, tools: tuple[str, ...] | list[str] = (), needs: tuple[str, ...] | list[str] = ()) -> Callable:
    """Run the decorated function immediately as a named case."""

    def decorate(fn: Callable[[], Any]) -> Callable[[], Any]:
        _run_case(name, list(tools), list(needs), fn)
        return fn

    return decorate


def _run_case(name: str, tools: list[str], needs: list[str], fn: Callable[[], Any]) -> None:
    entry: dict[str, Any] = {"case": name, "tools": tools, "status": PASS, "evidence": "", "note": "", "seconds": 0.0}
    blocked = [n for n in needs if STATUS_BY_CASE.get(n) not in GOOD]
    if blocked:
        entry["status"] = SKIP
        entry["note"] = "dependency not passing: " + ", ".join(f"{n}={STATUS_BY_CASE.get(n, 'not-run')}" for n in blocked)
    else:
        timer = threading.Timer(WATCHDOG_SECONDS, _on_hang, args=(name, tools))
        timer.daemon = True
        started = time.time()
        timer.start()
        try:
            evidence = fn()
            entry["evidence"] = str(evidence or "")
        except Silent as exc:
            entry["status"], entry["note"] = SILENT, str(exc)
        except Unverified as exc:
            entry["status"], entry["note"] = UNVERIFIED, str(exc)
        except Fail as exc:
            entry["status"], entry["note"] = FAIL, str(exc)
        except Exception as exc:  # noqa: BLE001 - a case must never abort the run
            entry["status"] = FAIL
            tb = traceback.format_exc().strip().splitlines()
            entry["note"] = f"{type(exc).__name__}: {exc} [{tb[-3].strip() if len(tb) >= 3 else ''}]"
        finally:
            timer.cancel()
            entry["seconds"] = round(time.time() - started, 2)
    STATUS_BY_CASE[name] = entry["status"]
    RESULTS.append(entry)
    _dump()
    print(f"[{entry['status']:11}] {name} ({entry['seconds']}s) {entry['note'][:140]}", flush=True)


# ---------------------------------------------------------------------------
# Handler helpers
# ---------------------------------------------------------------------------


def call(tool_name: str, **args: Any) -> dict[str, Any]:
    from solidworks_mcp.sw_core import HANDLERS

    return HANDLERS[tool_name](args)


def ok(tool_name: str, **args: Any) -> dict[str, Any]:
    """Call a handler, raise Fail unless ok, return its ``data`` dict."""
    payload = call(tool_name, **args)
    if not payload.get("ok"):
        data = payload.get("data") or {}
        extra = f" problems={data['problems']}" if data.get("problems") else ""
        raise Fail(f"{tool_name}: {payload.get('message')}{extra}")
    return payload.get("data") or {}


def expect_not_ok(tool_name: str, **args: Any) -> str:
    """Return the failure message of a call that should be refused."""
    try:
        payload = call(tool_name, **args)
    except RuntimeError as exc:
        return f"RuntimeError: {exc}"
    if payload.get("ok"):
        raise Silent(f"{tool_name} accepted a call it should have refused: {payload}")
    return str(payload.get("message"))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise Silent(message)


def near(actual: float, expected: float, rel: float = 1e-3, abs_tol: float = 1e-6) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=rel, abs_tol=abs_tol)


def app() -> Any:
    from solidworks_mcp.sw_core import running_app

    return running_app()


def active_doc() -> Any:
    doc = app().ActiveDoc
    if doc is None:
        raise Fail("no active document")
    return doc


def volume() -> float:
    return float(ok("get_mass_properties")["volume_mm3"])


def n_bodies() -> int:
    return len(ok("list_bodies")["bodies"])


def faces(**kw: Any) -> list[dict[str, Any]]:
    return ok("list_faces", **kw)["faces"]


def edges(**kw: Any) -> list[dict[str, Any]]:
    return ok("list_edges", **kw)["edges"]


def feature_names() -> list[str]:
    return [f["name"] for f in ok("list_features")["features"]]


def segments(sketch_name: str | None = None) -> list[dict[str, Any]]:
    if sketch_name:
        return ok("list_sketch_segments", sketch_name=sketch_name)["segments"]
    return ok("list_sketch_segments")["segments"]


def seg_sig(seg: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in seg.items() if k not in ("index", "id")}, sort_keys=True, default=str)


def new_segments(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Segments in ``after`` not present in ``before`` (GetSketchSegments order is not creation order)."""
    from collections import Counter

    remaining = Counter(seg_sig(s) for s in before)
    out = []
    for s in after:
        sig = seg_sig(s)
        if remaining[sig] > 0:
            remaining[sig] -= 1
        else:
            out.append(s)
    return out


def find_line(segs: list[dict[str, Any]], p: tuple[float, float], q: tuple[float, float]) -> dict[str, Any]:
    for s in segs:
        if s["type"] != "line":
            continue
        a, b = s["start_mm"][:2], s["end_mm"][:2]
        fwd = near(a[0], p[0], abs_tol=1e-3) and near(a[1], p[1], abs_tol=1e-3) and near(b[0], q[0], abs_tol=1e-3) and near(b[1], q[1], abs_tol=1e-3)
        rev = near(b[0], p[0], abs_tol=1e-3) and near(b[1], p[1], abs_tol=1e-3) and near(a[0], q[0], abs_tol=1e-3) and near(a[1], q[1], abs_tol=1e-3)
        if fwd or rev:
            return s
    raise Fail(f"no line {p}-{q} in sketch")


def bbox_size() -> list[float]:
    return ok("get_bounding_box")["size_mm"]


def new_part() -> str:
    data = ok("create_new_document", kind="part")
    title = data["document"]["title"]
    X["docs"].append(title)
    return title


def draw_box_part(x1: float, y1: float, x2: float, y2: float, depth: float, tag: str, plane: str = "front") -> None:
    ok("create_sketch", plane=plane, name=f"{tag}_Sketch")
    ok("draw_rectangle", x1_mm=x1, y1_mm=y1, x2_mm=x2, y2_mm=y2)
    ok("close_sketch")
    ok("boss_extrude", sketch_name=f"{tag}_Sketch", depth_mm=depth, name=f"{tag}_Boss")


def z_edges_at(x: float, y: float) -> list[int]:
    out = []
    for e in edges():
        if e.get("curve_type") != "line":
            continue
        s, t = e.get("start_mm"), e.get("end_mm")
        if not s or not t:
            continue
        if near(s[0], x, abs_tol=1e-3) and near(t[0], x, abs_tol=1e-3) and near(s[1], y, abs_tol=1e-3) and near(t[1], y, abs_tol=1e-3):
            out.append(e["index"])
    return out


def face_index(normal: list[float]) -> int:
    found = faces(normal=normal)
    if not found:
        raise Fail(f"no planar face with normal {normal}")
    return max(found, key=lambda f: f.get("area_mm2", 0))["index"]


def file_ok(path: Path, min_bytes: int = 1) -> int:
    check(path.is_file(), f"file missing: {path}")
    size = path.stat().st_size
    check(size >= min_bytes, f"file too small: {path.name} = {size} bytes (< {min_bytes})")
    return size


def view_by_name(doc: Any, name: str) -> Any:
    from solidworks_mcp.sw_core import safe
    from solidworks_mcp.sw_drawing import _iter_views

    for v in _iter_views(doc):
        if str(safe(v, "GetName2", "")) == name:
            return v
    raise Fail(f"view '{name}' not found")


def view_annotation_types(view: Any) -> list[int]:
    """Annotation type codes inside a drawing view (best effort, [] if unreadable)."""
    from solidworks_mcp.sw_core import safe, value

    types: list[int] = []
    try:
        ann = value(view, "GetFirstAnnotation3")
    except Exception:
        return types
    guard = 0
    while ann is not None and guard < 500:
        guard += 1
        t = safe(ann, "GetType")
        types.append(int(t) if t is not None else -1)
        try:
            ann = value(ann, "GetNext3")
        except Exception:
            break
    return types


def all_view_annotation_types(doc: Any) -> list[int]:
    from solidworks_mcp.sw_drawing import _iter_views

    out: list[int] = []
    for v in _iter_views(doc):
        out.extend(view_annotation_types(v))
    return out


def list_views() -> list[dict[str, Any]]:
    return ok("list_drawing_views")["views"]


def model_views() -> list[dict[str, Any]]:
    return [v for v in list_views() if v.get("type") != "sheet"]


# ---------------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------------


def main() -> int:
    global RUN_DIR
    stamp = time.strftime("%Y%m%d-%H%M%S")
    RUN_DIR = SANDBOX / f"run-{stamp}"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    X["meta"] = {"stamp": stamp, "run_dir": str(RUN_DIR), "argv": sys.argv}

    import solidworks_mcp.server  # noqa: F401 - registers every tool module
    from solidworks_mcp import sw_core
    from solidworks_mcp.sw_core import HANDLERS, as_list, flag_methods, safe, value

    assert Path(sw_core.OUTPUT_ROOT).resolve() == SANDBOX.resolve(), f"OUTPUT_ROOT is {sw_core.OUTPUT_ROOT}"
    X["meta"]["registered_tools"] = len(HANDLERS)
    p = lambda name: str(RUN_DIR / name)  # noqa: E731

    # ---------------------------------------------------------------- 0. Preflight
    @step("0.1 status", ["solidworks_status"])
    def _():
        d = ok("solidworks_status")
        X["meta"]["sw_revision"] = d["version"]
        X["baseline_docs"] = [str(value(x, "GetTitle")) for x in as_list(value(app(), "GetDocuments"))]
        X["meta"]["baseline_docs"] = X["baseline_docs"]
        check(str(d["version"]).startswith("25."), f"unexpected revision {d['version']}")
        check(Path(d["output_root"]).resolve() == SANDBOX.resolve(), f"output_root {d['output_root']}")
        return f"revision={d['version']} docs_open={d['document_count']} output_root={d['output_root']}"

    @step("0.2 negative: no document", [], ["0.1 status"])
    def _():
        if X["baseline_docs"]:
            raise Unverified("documents already open; skipping the no-document negatives")
        msgs = [
            expect_not_ok("get_active_document_info"),
            expect_not_ok("list_features"),
            expect_not_ok("list_reference_planes"),
        ]
        return " | ".join(m[:60] for m in msgs)

    # ---------------------------------------------------------------- 1. T3 core chain
    @step("T3.1 new part", ["create_new_document", "get_active_document_info"], ["0.1 status"])
    def _():
        a = app()
        pref = a.GetUserPreferenceStringValue(8)
        fallback = sw_core.discover_template("part")
        X["meta"]["template_pref_part"] = str(pref)
        X["meta"]["template_discovered_part"] = str(fallback)
        title = new_part()
        X["t3_title"] = title
        info = ok("get_active_document_info")["document"]
        check(info["document_type"] == "part", f"document_type={info['document_type']}")
        doc = active_doc()
        ext = doc.Extension
        flag_methods(ext, "GetUserPreferenceInteger")
        unit = int(ext.GetUserPreferenceInteger(47, 0))  # swUnitsLinear, no option
        names = {0: "mm", 1: "cm", 2: "m", 3: "in", 4: "ft", 5: "ft-in"}
        X["meta"]["part_units"] = names.get(unit, f"code {unit}")
        used = str(pref) if pref and Path(str(pref)).is_file() else f"{fallback} (fallback scan; default pref '{pref}' not a file)"
        X["meta"]["template_used_part"] = used
        X["notes"].append(f"create_new_document template used: {used}; document linear units: {names.get(unit, unit)} (R-008 expects mm)")
        return f"title={title} template={used} units={names.get(unit, unit)}"

    @step("T3.2 reference planes", ["list_reference_planes"], ["T3.1 new part"])
    def _():
        d = ok("list_reference_planes")
        check(len(d["planes"]) == 3, f"planes={d['planes']}")
        return f"planes={d['planes']} axes={d.get('axes')}"

    @step("T3.3 sketch rectangle", ["create_sketch", "draw_rectangle", "list_sketch_segments"], ["T3.1 new part"])
    def _():
        ok("create_sketch", plane="front", name="T3_Base")
        d = ok("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=20, y2_mm=10)
        segs = segments()
        check(len(segs) == 4 and all(s["type"] == "line" for s in segs), f"segments={len(segs)} {[s['type'] for s in segs]}")
        xs = [c for s in segs for c in (s["start_mm"][0], s["end_mm"][0])]
        ys = [c for s in segs for c in (s["start_mm"][1], s["end_mm"][1])]
        check(near(min(xs), 0, abs_tol=1e-4) and near(max(xs), 20, abs_tol=1e-4) and near(min(ys), 0, abs_tol=1e-4) and near(max(ys), 10, abs_tol=1e-4),
              f"extents x[{min(xs)},{max(xs)}] y[{min(ys)},{max(ys)}]")
        return f"4 lines, extents x 0..20 y 0..10, segments_added={d.get('segments_added')}"

    @step("T3.4 close sketch", ["close_sketch", "list_sketches"], ["T3.3 sketch rectangle"])
    def _():
        ok("close_sketch")
        d = ok("list_sketches")
        check("T3_Base" in d["sketches"] and not d["sketch_open"], f"sketches={d}")
        return f"sketches={d['sketches']} open={d['sketch_open']}"

    @step("T3.5 boss extrude", ["boss_extrude", "get_bounding_box", "list_bodies"], ["T3.4 close sketch"])
    def _():
        d = ok("boss_extrude", sketch_name="T3_Base", depth_mm=5, name="T3_Boss")
        v, nb, size = volume(), n_bodies(), bbox_size()
        check(near(v, 1000.0, rel=1e-3), f"volume {v} != 1000 (+-0.1%)")
        check(nb == 1, f"bodies={nb}")
        check(all(near(a, b, abs_tol=0.01) for a, b in zip(sorted(size), [5, 10, 20])), f"bbox {size}")
        return f"volume={v} bodies={nb} bbox={size}"

    @step("T3.6 sketch circle", ["draw_circle"], ["T3.5 boss extrude"])
    def _():
        ok("create_sketch", plane="front", name="T3_CutSketch")
        ok("draw_circle", x_mm=10, y_mm=5, radius_mm=2)
        segs = segments()
        check(len(segs) == 1 and near(segs[0].get("radius_mm", -1), 2.0, abs_tol=1e-4), f"segments={segs}")
        c = segs[0].get("center_mm")
        check(c is not None and near(c[0], 10, abs_tol=1e-4) and near(c[1], 5, abs_tol=1e-4), f"center {c}")
        ok("close_sketch")
        return "circle r=2 at (10,5)"

    @step("T3.7 cut extrude", ["cut_extrude"], ["T3.6 sketch circle"])
    def _():
        X["t3_faces_before_cut"] = len(faces())
        ok("cut_extrude", sketch_name="T3_CutSketch", end_condition="through_all", name="T3_Cut")
        expected = 1000.0 - math.pi * 4 * 5
        v = volume()
        check(near(v, expected, rel=1e-3), f"volume {v} != {expected:.3f}")
        check(n_bodies() == 1, "bodies != 1")
        nf = len(faces())
        check(nf > X["t3_faces_before_cut"], f"faces {X['t3_faces_before_cut']} -> {nf}")
        return f"volume={v} expected={expected:.3f} faces {X['t3_faces_before_cut']}->{nf}"

    @step("T3.8 fillet", ["fillet", "list_edges"], ["T3.7 cut extrude"])
    def _():
        picks = []
        for cx, cy in ((0, 0), (20, 0), (20, 10), (0, 10)):
            found = z_edges_at(cx, cy)
            check(len(found) == 1, f"expected one Z edge at ({cx},{cy}), got {found}")
            picks.extend(found)
        before_faces = len(faces())
        ok("fillet", radius_mm=1, selection={"edges": picks}, name="T3_Fillet")
        expected = (1000.0 - math.pi * 4 * 5) - 4 * (1 - math.pi / 4) * 5
        v, nf = volume(), len(faces())
        check(near(v, expected, rel=1e-3), f"volume {v} != {expected:.3f}")
        check(nf == before_faces + 4, f"faces {before_faces} -> {nf}, expected +4")
        X["t3_expected_volume"] = expected
        return f"volume={v} expected={expected:.3f} faces {before_faces}->{nf}"

    @step("T3.9 mass properties", ["get_mass_properties"], ["T3.8 fillet"])
    def _():
        d = ok("get_mass_properties")
        exp_area = 700 + (2 * math.pi * 2 * 5 - 2 * math.pi * 4) - 4 * (0.4292 + 10 - math.pi / 2 * 5)
        com = d["center_of_mass_mm"]
        check(near(d["volume_mm3"], X["t3_expected_volume"], rel=1e-3), f"volume {d['volume_mm3']}")
        check(near(d["surface_area_mm2"], exp_area, rel=5e-3), f"area {d['surface_area_mm2']} != {exp_area:.2f}")
        check(near(com[0], 10, abs_tol=0.02) and near(com[1], 5, abs_tol=0.02) and near(abs(com[2]), 2.5, abs_tol=0.02), f"COM {com}")
        X["t3_mass"] = d
        return f"volume={d['volume_mm3']} area={d['surface_area_mm2']} (exp {exp_area:.2f}) com={com} mass_g={d['mass_g']} inertia_keys={'moments_of_inertia_kg_m2' in d}"

    @step("T3.10 save", ["save_document"], ["T3.8 fillet"])
    def _():
        target = Path(p("T3_core.sldprt"))
        X["t3_path"] = target
        ok("save_document", path=str(target))
        size = file_ok(target, 1000)
        info = ok("get_active_document_info")["document"]
        check(Path(info["path"]).resolve() == target.resolve(), f"doc path now {info['path']}")
        X["t3_title"] = info["title"]
        # Overwrite protection is part of the contract.
        refusal = expect_not_ok("save_document", path=str(target))
        return f"{target.name} {size} bytes; overwrite refused: {refusal[:60]}"

    @step("T3.11 export STEP", ["export_document"], ["T3.10 save"])
    def _():
        target = Path(p("T3_core.step"))
        ok("export_document", path=str(target))
        size = file_ok(target, 1024)
        head = target.read_bytes()[:20]
        check(head.startswith(b"ISO-10303-21"), f"STEP header {head!r}")
        refusal = expect_not_ok("export_document", path=str(target))
        return f"{target.name} {size} bytes header ok; overwrite refused: {refusal[:50]}"

    # ---------------------------------------------------------------- 2. Inspect / appearance / save / export on the T3 part
    @step("2.1 list_features", ["list_features"], ["T3.8 fillet"])
    def _():
        names = feature_names()
        for needed in ("T3_Base", "T3_Boss", "T3_CutSketch", "T3_Cut", "T3_Fillet"):
            check(needed in names, f"{needed} missing from {names}")
        return f"{len(names)} features: {names}"

    @step("2.2 topology lists", ["list_faces", "list_edges", "list_vertices", "list_bodies", "get_bounding_box"], ["T3.8 fillet"])
    def _():
        fs, es = faces(), edges()
        vs = ok("list_vertices")["vertices"]
        nb = n_bodies()
        euler = len(vs) - len(es) + len(fs)
        top = faces(normal=[0, 0, 1])
        bottom = faces(normal=[0, 0, -1])
        X["t3_faces"] = len(fs)
        check(nb == 1, f"bodies={nb}")
        check(len(top) == 1 and len(bottom) == 1, f"planar +Z faces={len(top)} -Z faces={len(bottom)}")
        expected_face = 200 - math.pi * 4 - 4 * (1 - math.pi / 4)
        areas = sorted([top[0]["area_mm2"], bottom[0]["area_mm2"]])
        check(all(near(a, expected_face, rel=5e-3) for a in areas), f"cap areas {areas} != {expected_face:.2f}")
        # SOLIDWORKS stores a full circle as a vertex-less closed edge and a hole wall as one seamless
        # periodic face.  Block with 4 rounded corners: V=16 E=24 F=10 -> 2; the hole adds 2 edges
        # and 1 face but no vertices, so the consistent total is 1.
        check(euler == 1, f"Euler V-E+F = {len(vs)}-{len(es)}+{len(fs)} = {euler}, expected 1 (rounded block 2, minus 1 for a seamless hole)")
        size = bbox_size()
        check(all(near(a, b, abs_tol=0.01) for a, b in zip(sorted(size), [5, 10, 20])), f"bbox {size}")
        cyl = faces(surface_type="cylinder")
        check(len(cyl) >= 1, "no cylindrical faces found")
        circles = edges(curve_type="circle")
        check(len(circles) >= 2, f"circle edges={len(circles)}")
        return f"F={len(fs)} E={len(es)} V={len(vs)} Euler={euler} cap_area={areas[0]} cyl_faces={len(cyl)} circle_edges={len(circles)} bbox={size}"

    @step("2.3 measure", ["measure"], ["T3.8 fillet"])
    def _():
        top_i, bot_i = face_index([0, 0, 1]), face_index([0, 0, -1])
        d = ok("measure", selection={"faces": [top_i, bot_i]})
        dist = d.get("normal_distance_mm", d.get("distance_mm"))
        check(dist is not None and near(dist, 5.0, abs_tol=0.01), f"measure faces -> {d}")
        # A straight 18 mm edge (20 less two 1 mm fillets) along X.
        cand = [e for e in edges() if e.get("curve_type") == "line" and near(e.get("length_mm", 0), 18, abs_tol=0.01)]
        check(len(cand) >= 1, "no 18 mm line edge found")
        d2 = ok("measure", selection={"edges": [cand[0]["index"]]})
        check(near(d2.get("length_mm", -1), 18.0, abs_tol=0.01), f"edge length -> {d2}")
        d3 = ok("measure", selection={"faces": [top_i]})
        exp_face = 200 - math.pi * 4 - 4 * (1 - math.pi / 4)
        check(near(d3.get("area_mm2", -1), exp_face, rel=5e-3), f"face area -> {d3}")
        return f"face gap={dist} edge={d2['length_mm']} face_area={d3['area_mm2']}"

    @step("2.4 set_material", ["set_material"], ["T3.8 fillet"])
    def _():
        d = ok("set_material", name="AISI 1020")
        check(d.get("material") == "AISI 1020", f"readback {d}")
        mp = ok("get_mass_properties")
        density = mp.get("density_g_per_cm3")
        check(density is not None and 7.7 <= density <= 8.0, f"density {density} g/cm3 not steel-like")
        exp_mass = X["t3_expected_volume"] / 1000.0 * density
        check(near(mp["mass_g"], exp_mass, rel=2e-3), f"mass {mp['mass_g']} g vs vol*density {exp_mass:.4f}")
        return f"material={d['material']} density={density} mass_g={mp['mass_g']}"

    @step("2.5 set_appearance", ["set_appearance"], ["T3.8 fillet"])
    def _():
        ok("set_appearance", red=255, green=0, blue=0, transparency=0.0)
        vals = active_doc().MaterialPropertyValues
        check(vals is not None and len(vals) >= 3, f"MaterialPropertyValues={vals}")
        check(near(vals[0], 1.0, abs_tol=0.01) and near(vals[1], 0.0, abs_tol=0.01) and near(vals[2], 0.0, abs_tol=0.01), f"rgb readback {vals[:3]}")
        return f"rgb readback {tuple(round(v, 3) for v in vals[:3])}"

    @step("2.6 check_errors / rebuild", ["check_errors", "rebuild_document"], ["T3.8 fillet"])
    def _():
        d = ok("check_errors")
        check(not d.get("problems"), f"problems={d['problems']}")
        r1 = ok("rebuild_document", force_all=True)
        r2 = ok("rebuild_document")
        v = volume()
        check(near(v, X["t3_expected_volume"], rel=1e-3), f"volume after rebuild {v}")
        return f"no problems; force_all rebuild ok; volume stable {v}"

    @step("2.7 set_view + shaded-with-edges [verify-live #5]", ["set_view"], ["T3.8 fillet"])
    def _():
        doc = active_doc()
        mv = doc.ActiveView
        mv.DisplayMode = 3  # swViewDisplayMode_Shaded, so the tool's effect is distinguishable
        before = int(mv.DisplayMode)
        check(before == 3, f"could not preset display mode (got {before})")
        ok("set_view", view="isometric", zoom_to_fit=True, shaded_with_edges=True)
        after = int(active_doc().ActiveView.DisplayMode)
        X["verify_setview"] = {"before": before, "after": after}
        check(after == 5, f"set_view(shaded_with_edges=True) left DisplayMode={after}; expected 5 (ShadedWithEdges)")
        for v in ("front", "top", "right", "back", "bottom", "left", "trimetric", "dimetric"):
            ok("set_view", view=v, zoom_to_fit=True, shaded_with_edges=False)
        ok("set_view", view="isometric")
        return f"DisplayMode {before} -> {after} (5 = shaded with edges); 9 named views accepted"

    @step("2.8 capture_screenshot", ["capture_screenshot"], ["T3.8 fillet"])
    def _():
        payload = call("capture_screenshot", view="isometric", width_px=800)
        check(payload.get("ok"), f"not ok: {payload.get('message')}")
        raw = base64.b64decode(payload["_image_png_base64"])
        out = RUN_DIR / "T3_screenshot.png"
        out.write_bytes(raw)
        check(raw[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG")
        from PIL import Image, ImageStat
        import io

        with Image.open(io.BytesIO(raw)) as im:
            width, height = im.size
            stdev = max(ImageStat.Stat(im.convert("L")).stddev)
        check(len(raw) > 2000 and stdev > 5, f"image looks blank: {len(raw)} bytes, stddev {stdev:.1f}")
        check(width <= 800, f"width {width} > requested 800")
        return f"{out.name} {len(raw)} bytes {width}x{height} stddev={stdev:.1f}"

    @step("2.9 save_active_document", ["save_active_document"], ["T3.10 save"])
    def _():
        target = X["t3_path"]
        before_m = target.stat().st_mtime
        dirty = ok("get_active_document_info")["document"]["dirty"]
        time.sleep(1.1)
        ok("save_active_document")
        file_ok(target, 1000)
        after = ok("get_active_document_info")["document"]
        check(target.stat().st_mtime > before_m, "file mtime did not advance after save_active_document")
        check(not after["dirty"], "document still dirty after save")
        return f"dirty_before={dirty}; mtime advanced; dirty_after={after['dirty']}; size={target.stat().st_size}"

    for ext, minb, magic in (("x_t", 400, None), ("igs", 400, None), ("png", 2000, b"\x89PNG"), ("jpg", 1500, b"\xff\xd8")):
        @step(f"2.10 export .{ext}", ["export_document"], ["T3.10 save"])
        def _(ext=ext, minb=minb, magic=magic):
            target = Path(p(f"T3_core.{ext}"))
            ok("export_document", path=str(target))
            size = file_ok(target, minb)
            if magic:
                check(target.read_bytes()[: len(magic)] == magic, f"bad magic {target.read_bytes()[:8]!r}")
            return f"{target.name} {size} bytes"

    # ---------------------------------------------------------------- 3. Feature part ("Block")
    @step("3.1 new part + base boss", ["create_new_document", "boss_extrude"], ["0.1 status"])
    def _():
        new_part()
        draw_box_part(-30, -20, 30, 20, 20, "Block")
        v = volume()
        check(near(v, 48000, rel=1e-3) and n_bodies() == 1, f"volume {v}")
        X["blk_v"] = v
        return f"volume={v}"

    @step("3.2 rename_feature", ["rename_feature"], ["3.1 new part + base boss"])
    def _():
        ok("rename_feature", feature_name="Block_Boss", new_name="Base_Block")
        names = feature_names()
        check("Base_Block" in names and "Block_Boss" not in names, f"features {names}")
        return "Block_Boss -> Base_Block"

    @step("3.3 chamfer", ["chamfer"], ["3.2 rename_feature"])
    def _():
        picks = z_edges_at(30, 20)
        check(len(picks) == 1, f"Z edge at (30,20): {picks}")
        nf = len(faces())
        ok("chamfer", distance_mm=2, selection={"edges": picks}, mode="equal_distance", name="Block_Chamfer")
        expected = 48000 - 0.5 * 2 * 2 * 20
        v = volume()
        nf2 = len(faces())
        X["blk_v"] = v
        check(near(v, expected, rel=1e-4), f"chamfer feature created but volume {v} != {expected} (faces {nf} -> {nf2}); no geometry change")
        check(nf2 == nf + 1, f"faces {nf} -> {nf2}")
        return f"volume={v} expected={expected} faces {nf}->{nf + 1}"

    @step("3.3b chamfer angle_distance (workaround)", ["chamfer"], ["3.2 rename_feature"])
    def _():
        picks = z_edges_at(30, 20)
        check(len(picks) == 1, f"Z edge at (30,20): {picks}")
        nf = len(faces())
        v0 = volume()
        ok("chamfer", distance_mm=2, selection={"edges": picks}, mode="angle_distance", angle_deg=45, name="Block_Chamfer2")
        expected = v0 - 0.5 * 2 * 2 * 20
        v = volume()
        X["blk_v"] = v
        check(near(v, expected, rel=1e-4), f"volume {v} != {expected}")
        check(len(faces()) == nf + 1, f"faces {nf} -> {len(faces())}")
        return f"volume {v0} -> {v} (expected {expected}); faces +1"

    @step("3.4 fillet", ["fillet"], ["3.2 rename_feature"])
    def _():
        picks = z_edges_at(-30, -20)
        check(len(picks) == 1, f"Z edge at (-30,-20): {picks}")
        nf = len(faces())
        ok("fillet", radius_mm=3, selection={"edges": picks}, name="Block_Fillet")
        expected = X["blk_v"] - (9 - 9 * math.pi / 4) * 20
        v = volume()
        check(near(v, expected, rel=1e-4), f"volume {v} != {expected:.3f}")
        check(len(faces()) == nf + 1, f"faces {nf} -> {len(faces())}")
        X["blk_v"] = v
        return f"volume={v} expected={expected:.3f}"

    @step("3.5 sketch on face + cut blind", ["create_sketch", "cut_extrude"], ["3.4 fillet"])
    def _():
        top = face_index([0, 0, 1])
        ok("create_sketch", face_index=top, name="Block_PocketSketch")
        ok("draw_circle", x_mm=0, y_mm=0, radius_mm=5)
        ok("close_sketch")
        ok("cut_extrude", sketch_name="Block_PocketSketch", depth_mm=10, end_condition="blind", name="Block_Pocket")
        expected = X["blk_v"] - math.pi * 25 * 10
        v = volume()
        check(near(v, expected, rel=1e-3), f"volume {v} != {expected:.3f} (cut direction?)")
        X["blk_v"] = v
        return f"volume={v} expected={expected:.3f}"

    @step("3.6 simple_hole", ["simple_hole"], ["3.5 sketch on face + cut blind"])
    def _():
        ok("simple_hole", diameter_mm=6, depth_mm=8, end_condition="blind",
           selection={"points": [{"x_mm": 0, "y_mm": 12, "z_mm": 20, "type": "FACE"}]}, name="Block_Hole")
        expected = X["blk_v"] - math.pi * 9 * 8
        v = volume()
        check(near(v, expected, rel=1e-3), f"volume {v} != {expected:.3f}")
        X["blk_v"] = v
        return f"volume={v} expected={expected:.3f}"

    @step("3.7 linear_pattern", ["linear_pattern"], ["3.6 simple_hole"])
    def _():
        xedges = [e for e in edges() if e.get("curve_type") == "line" and e.get("length_mm", 0) >= 40
                  and e.get("start_mm") and near(e["start_mm"][1], e["end_mm"][1], abs_tol=1e-3) and near(e["start_mm"][2], e["end_mm"][2], abs_tol=1e-3)]
        check(xedges, "no long X-parallel edge to use as direction")
        ok("linear_pattern", selection={"features": ["Block_Hole"]}, direction1_selection={"edges": [xedges[0]["index"]]},
           count1=3, spacing1_mm=10, name="Block_Pattern")
        expected = X["blk_v"] - 2 * math.pi * 9 * 8
        v = volume()
        check(near(v, expected, rel=1e-3), f"volume {v} != {expected:.3f} (3 holes)")
        X["blk_v_pattern"] = v
        return f"volume={v} expected={expected:.3f}"

    @step("3.8 create_plane offset", ["create_plane", "list_reference_planes"], ["3.1 new part + base boss"])
    def _():
        before = len(ok("list_reference_planes")["planes"])
        d = ok("create_plane", mode="offset", selection={"planes": ["front"]}, distance_mm=30, name="Block_Plane30")
        planes = ok("list_reference_planes")["planes"]
        check(len(planes) == before + 1 and "Block_Plane30" in planes, f"planes {planes}")
        return f"planes {before}->{len(planes)} {planes[-1]}"

    @step("3.9 create_axis", ["create_axis"], ["3.5 sketch on face + cut blind"])
    def _():
        cyl = [f for f in faces(surface_type="cylinder") if near(f.get("radius_mm", 0), 5, abs_tol=0.01)]
        check(cyl, "no r=5 cylinder face (pocket wall)")
        before = len(ok("list_reference_planes")["axes"])
        ok("create_axis", selection={"faces": [cyl[0]["index"]]}, name="Block_Axis")
        axes = ok("list_reference_planes")["axes"]
        check(len(axes) == before + 1, f"axes {axes}")
        return f"axes {before}->{len(axes)}: {axes}"

    @step("3.10 suppress / unsuppress", ["set_feature_suppression"], ["3.5 sketch on face + cut blind"])
    def _():
        v0 = volume()
        ok("set_feature_suppression", feature_names=["Block_Pocket"], suppressed=True)
        v1 = volume()
        check(near(v1 - v0, math.pi * 25 * 10, rel=2e-3), f"suppress changed volume by {v1 - v0:.3f}, expected {math.pi * 250:.3f}")
        ok("set_feature_suppression", feature_names=["Block_Pocket"], suppressed=False)
        v2 = volume()
        check(near(v2, v0, rel=1e-4), f"unsuppress volume {v2} != {v0}")
        return f"{v0} -> {v1} -> {v2}"

    @step("3.11 delete_feature", ["delete_feature"], ["3.7 linear_pattern"])
    def _():
        ok("delete_feature", feature_names=["Block_Pattern"])
        check("Block_Pattern" not in feature_names(), "pattern still in tree")
        v = volume()
        check(near(v, X["blk_v"], rel=1e-3), f"volume {v} != {X['blk_v']} after deleting pattern")
        return f"pattern deleted; volume back to {v}"

    @step("3.12 edit_sketch", ["edit_sketch", "close_sketch"], ["3.1 new part + base boss"])
    def _():
        ok("edit_sketch", sketch_name="Block_Sketch")
        check(ok("list_sketches")["sketch_open"], "sketch not open after edit_sketch")
        ok("close_sketch")
        check(not ok("list_sketches")["sketch_open"], "sketch still open")
        return "reopened and closed Block_Sketch"

    @step("3.13 convert_entities", ["convert_entities"], ["3.5 sketch on face + cut blind"])
    def _():
        top = face_index([0, 0, 1])
        ok("create_sketch", face_index=top, name="Block_Convert")
        before = len(segments())
        ok("convert_entities", selection={"face_edges": [top]})
        n = len(segments())
        check(n - before >= 4, f"segments {before} -> {n}")
        ok("close_sketch")
        return f"segments {before} -> {n}"

    # ---------------------------------------------------------------- 4. Sketch tools document
    @step("4.1 sketch doc", ["create_new_document"], ["0.1 status"])
    def _():
        new_part()
        ok("create_sketch", plane="front", name="SK_Draw")
        return "sketch SK_Draw open"

    def draw_case(label: str, tool_name: str, args: dict[str, Any], check_fn: Callable[[list[dict[str, Any]]], str]) -> None:
        @step(f"4.2 {label}", [tool_name], ["4.1 sketch doc"])
        def _():
            before = segments()
            ok(tool_name, **args)
            new = new_segments(before, segments())
            check(len(new) > 0, "sketch gained no segments")
            return check_fn(new)

    def chk_line(new: list) -> str:
        s = new[0]
        pts = sorted([tuple(round(c, 3) for c in s["start_mm"][:2]), tuple(round(c, 3) for c in s["end_mm"][:2])])
        check(len(new) == 1 and s["type"] == "line" and pts == [(0.0, 0.0), (30.0, 10.0)], f"{new}")
        return f"1 line {pts}"

    def chk_center(new: list) -> str:
        check(len(new) == 1 and new[0]["construction"], f"centerline: {new}")
        return "1 construction line"

    def chk_radius(r: float) -> Callable:
        def inner(new: list) -> str:
            check(len(new) == 1 and near(new[0].get("radius_mm", -1), r, abs_tol=1e-3), f"expected one segment with radius {r}: {new}")
            return f"1 segment radius={new[0]['radius_mm']}"
        return inner

    def chk_type(kind: str) -> Callable:
        def inner(new: list) -> str:
            check(len(new) == 1 and new[0]["type"] == kind, f"expected one {kind}: {[s['type'] for s in new]}")
            return f"1 {kind}"
        return inner

    def chk_real(n: int) -> Callable:
        def inner(new: list) -> str:
            real = [s for s in new if not s["construction"]]
            check(len(real) == n, f"{len(real)} real segments (+{len(new) - len(real)} construction), expected {n}")
            return f"{len(real)} real + {len(new) - len(real)} construction segments"
        return inner

    draw_case("draw_line", "draw_line", dict(x1_mm=0, y1_mm=0, x2_mm=30, y2_mm=10), chk_line)
    draw_case("draw_centerline", "draw_centerline", dict(x1_mm=0, y1_mm=-50, x2_mm=0, y2_mm=50), chk_center)
    draw_case("draw_circle", "draw_circle", dict(x_mm=50, y_mm=0, radius_mm=5), chk_radius(5))
    draw_case("draw_rectangle", "draw_rectangle", dict(x1_mm=60, y1_mm=-10, x2_mm=80, y2_mm=10), chk_real(4))
    draw_case("draw_arc", "draw_arc", dict(center_x_mm=100, center_y_mm=0, start_x_mm=110, start_y_mm=0, end_x_mm=100, end_y_mm=10, direction=1), chk_radius(10))
    draw_case("draw_3point_arc", "draw_3point_arc", dict(x1_mm=120, y1_mm=0, x2_mm=130, y2_mm=10, x3_mm=140, y3_mm=0), chk_radius(10))
    draw_case("draw_ellipse", "draw_ellipse", dict(center_x_mm=170, center_y_mm=0, major_x_mm=180, major_y_mm=0, minor_x_mm=170, minor_y_mm=5), chk_type("ellipse"))
    draw_case("draw_polygon", "draw_polygon", dict(center_x_mm=200, center_y_mm=0, point_x_mm=205, point_y_mm=0, sides=6), chk_real(6))
    draw_case("draw_slot", "draw_slot", dict(x1_mm=230, y1_mm=0, x2_mm=250, y2_mm=0, width_mm=6), chk_real(4))
    draw_case("draw_spline", "draw_spline", dict(points=[{"x_mm": 270, "y_mm": 0}, {"x_mm": 275, "y_mm": 5}, {"x_mm": 280, "y_mm": -5}, {"x_mm": 290, "y_mm": 0}]), chk_type("spline"))

    @step("4.2 draw_point", ["draw_point"], ["4.1 sketch doc"])
    def _():
        from solidworks_mcp.sw_core import sketch_point_objects

        doc = active_doc()
        before = len(sketch_point_objects(doc))
        ok("draw_point", x_mm=300, y_mm=0)
        after = len(sketch_point_objects(doc))
        check(after == before + 1, f"sketch points {before} -> {after}")
        return f"sketch points {before} -> {after}"

    @step("4.3 set_construction_geometry", ["set_construction_geometry"], ["4.1 sketch doc"])
    def _():
        segs = segments()
        circle = next(s for s in segs if s["type"] == "arc" and near(s.get("radius_mm", 0), 5, abs_tol=1e-3) and near(s["center_mm"][0], 50, abs_tol=1e-3))
        ok("set_construction_geometry", selection={"sketch_segments": [circle["index"]]}, construction=True)
        check(segments()[circle["index"]]["construction"], "construction flag not set")
        ok("set_construction_geometry", selection={"sketch_segments": [circle["index"]]}, construction=False)
        check(not segments()[circle["index"]]["construction"], "construction flag not cleared")
        return "toggled on and off, read back both"

    @step("4.4 dimension / relation / status", ["add_dimension", "list_dimensions", "set_dimension", "add_relation", "get_sketch_status"], ["4.1 sketch doc"])
    def _():
        segs = segments()
        line = next(s for s in segs if s["type"] == "line" and not s["construction"] and near(s["start_mm"][0], 0, abs_tol=1e-3) and near(s["end_mm"][0], 30, abs_tol=1e-3))
        status0 = ok("get_sketch_status")["sketch_status"]
        ok("add_relation", relation="horizontal", selection={"sketch_segments": [line["index"]]})
        s1 = segments()[line["index"]]
        check(near(s1["start_mm"][1], s1["end_mm"][1], abs_tol=1e-4), f"horizontal relation did not level the line: {s1}")
        d = ok("add_dimension", selection={"sketch_segments": [line["index"]]}, kind="auto", value_mm=40, name="SK_Len")
        s2 = segments()[line["index"]]
        check(near(s2["length_mm"], 40, abs_tol=1e-3), f"line length {s2['length_mm']} != 40 after add_dimension")
        dims = ok("list_dimensions")["dimensions"]
        mine = [x for x in dims if near(x.get("value_mm", -1), 40, abs_tol=1e-3)]
        check(mine, f"list_dimensions does not show the 40 mm dimension: {dims}")
        full = mine[0]["full_name"]
        ok("set_dimension", full_name=full, value_mm=25)
        s3 = segments()[line["index"]]
        check(near(s3["length_mm"], 25, abs_tol=1e-3), f"line length {s3['length_mm']} != 25 after set_dimension")
        status1 = ok("get_sketch_status")["sketch_status"]
        return f"status {status0}->{status1}; horizontal ok; dim {full}: 40 -> 25"

    @step("4.5 close SK_Draw", ["close_sketch"], ["4.1 sketch doc"])
    def _():
        ok("close_sketch")
        return "closed"

    @step("4.6 sketch edit sketch", ["create_sketch"], ["4.1 sketch doc"])
    def _():
        ok("create_sketch", plane="front", name="SK_Edit")
        # fillet corner, chamfer corner, offset circle, mirror pair, trim cross
        ok("draw_line", x1_mm=0, y1_mm=0, x2_mm=30, y2_mm=0)
        ok("draw_line", x1_mm=0, y1_mm=0, x2_mm=0, y2_mm=30)
        ok("draw_line", x1_mm=100, y1_mm=0, x2_mm=130, y2_mm=0)
        ok("draw_line", x1_mm=100, y1_mm=0, x2_mm=100, y2_mm=30)
        ok("draw_circle", x_mm=200, y_mm=0, radius_mm=10)
        ok("draw_centerline", x1_mm=300, y1_mm=-50, x2_mm=300, y2_mm=50)
        ok("draw_line", x1_mm=310, y1_mm=0, x2_mm=330, y2_mm=20)
        ok("draw_line", x1_mm=380, y1_mm=0, x2_mm=420, y2_mm=0)
        ok("draw_line", x1_mm=400, y1_mm=-20, x2_mm=400, y2_mm=20)
        check(len(segments()) == 9, f"segments={len(segments())}")
        return "9 segments"

    @step("4.7 sketch_fillet", ["sketch_fillet"], ["4.6 sketch edit sketch"])
    def _():
        segs0 = segments()
        before = len(segs0)
        pair = [find_line(segs0, (0, 0), (30, 0))["index"], find_line(segs0, (0, 0), (0, 30))["index"]]
        ok("sketch_fillet", radius_mm=5, selection={"sketch_segments": pair})
        segs = segments()
        arcs = [s for s in segs if s["type"] == "arc" and near(s.get("radius_mm", 0), 5, abs_tol=1e-3)]
        check(len(segs) == before + 1 and arcs, f"segments {before} -> {len(segs)}, r5 arcs={len(arcs)}")
        return f"segments {before} -> {len(segs)}, arc r=5"

    @step("4.8 sketch_chamfer", ["sketch_chamfer"], ["4.6 sketch edit sketch"])
    def _():
        segs = segments()
        pair = [find_line(segs, (100, 0), (130, 0))["index"], find_line(segs, (100, 0), (100, 30))["index"]]
        before = len(segs)
        ok("sketch_chamfer", distance_mm=5, mode="equal_distance", selection={"sketch_segments": pair})
        after = segments()
        diag = [s for s in after if s["type"] == "line" and near(s.get("length_mm", 0), 5 * math.sqrt(2), abs_tol=0.01)]
        check(len(after) == before + 1 and diag, f"segments {before} -> {len(after)}; 7.07 mm lines={len(diag)}")
        return f"segments {before} -> {len(after)}, chamfer line {diag[0]['length_mm']}"

    @step("4.9 sketch_offset", ["sketch_offset"], ["4.6 sketch edit sketch"])
    def _():
        segs = segments()
        circle = next(s for s in segs if s["type"] == "arc" and near(s.get("radius_mm", 0), 10, abs_tol=1e-3) and near(s["center_mm"][0], 200, abs_tol=1e-3))
        before = len(segs)
        ok("sketch_offset", distance_mm=3, selection={"sketch_segments": [circle["index"]]})
        after = segments()
        radii = sorted(round(s["radius_mm"], 3) for s in after if s["type"] == "arc" and near(s["center_mm"][0], 200, abs_tol=1e-3))
        check(len(after) == before + 1 and any(near(r, 13, abs_tol=0.01) or near(r, 7, abs_tol=0.01) for r in radii), f"radii {radii}")
        return f"segments {before} -> {len(after)}, radii at x=200: {radii}"

    @step("4.10 sketch_mirror", ["sketch_mirror"], ["4.6 sketch edit sketch"])
    def _():
        segs = segments()
        cl = next(s for s in segs if s["construction"] and near(s["start_mm"][0], 300, abs_tol=1e-3))
        src = next(s for s in segs if s["type"] == "line" and not s["construction"] and near(s["start_mm"][0], 310, abs_tol=1e-3))
        before = len(segs)
        ok("sketch_mirror", selection={"sketch_segments": [src["index"]]}, mirror_segment=cl["index"])
        after = segments()
        mirrored = [s for s in after if s["type"] == "line" and not s["construction"] and near(s["start_mm"][0], 290, abs_tol=1e-3) and near(s["end_mm"][0], 270, abs_tol=1e-3)]
        check(len(after) == before + 1 and mirrored, f"segments {before} -> {len(after)}; mirrored lines={len(mirrored)}")
        return f"segments {before} -> {len(after)}; mirrored line x 290..270"

    @step("4.11 sketch_trim", ["sketch_trim"], ["4.6 sketch edit sketch"])
    def _():
        segs = segments()
        horiz = next(s for s in segs if s["type"] == "line" and near(s["start_mm"][1], 0, abs_tol=1e-3) and near(s["end_mm"][1], 0, abs_tol=1e-3) and near(s["start_mm"][0], 380, abs_tol=1e-3))
        ok("sketch_trim", selection={"sketch_segments": [horiz["index"]]}, x_mm=390, y_mm=0, mode="closest")
        after = segments()
        lines = [s for s in after if s["type"] == "line" and near(s["start_mm"][1], 0, abs_tol=1e-3) and near(s["end_mm"][1], 0, abs_tol=1e-3) and max(s["start_mm"][0], s["end_mm"][0]) >= 399 and min(s["start_mm"][0], s["end_mm"][0]) >= 379]
        xs = sorted({round(c, 3) for s in lines for c in (s["start_mm"][0], s["end_mm"][0])})
        check(380.0 not in xs or 400.0 in xs and min(xs) >= 399.0, f"trim left x-range {xs}")
        check(not any(near(min(s["start_mm"][0], s["end_mm"][0]), 380, abs_tol=1e-3) and near(max(s["start_mm"][0], s["end_mm"][0]), 420, abs_tol=1e-3) for s in after if s["type"] == "line"), "horizontal line still full length")
        return f"horizontal line endpoints after trim: {xs}"

    @step("4.12 close SK_Edit", ["close_sketch"], ["4.6 sketch edit sketch"])
    def _():
        ok("close_sketch")
        return "closed"

    # ---------------------------------------------------------------- 5. Other features, each in a small part
    @step("5.1 revolve mid-plane [verify-live #1]", ["revolve", "draw_centerline"], ["0.1 status"])
    def _():
        new_part()
        ok("create_sketch", plane="front", name="Rev_A")
        ok("draw_rectangle", x1_mm=10, y1_mm=0, x2_mm=30, y2_mm=20)
        ok("draw_centerline", x1_mm=0, y1_mm=-5, x2_mm=0, y2_mm=25)
        ok("close_sketch")
        ok("revolve", sketch_name="Rev_A", angle_deg=90, mid_plane=True, name="Rev_A_Revolve")
        full = math.pi * (900 - 100) * 20
        v = volume()
        bb = ok("get_bounding_box")
        mn, mx = bb["min_mm"], bb["max_mm"]
        X["verify_revolve"] = {"volume": v, "min": mn, "max": mx}
        check(near(v, full / 4, rel=5e-3), f"volume {v} != quarter of full revolve {full / 4:.1f}")
        check(near(mn[2], -mx[2], abs_tol=0.3) and mx[2] > 15, f"not symmetric about the sketch plane: z {mn[2]}..{mx[2]}")
        check(near(mx[2], 30 * math.sin(math.radians(45)), abs_tol=0.3), f"z extent {mx[2]} != 21.21")
        return f"volume={v} (quarter={full / 4:.1f}); bbox z {mn[2]:.2f}..{mx[2]:.2f} (symmetric, +-21.21 expected); x {mn[0]:.2f}..{mx[0]:.2f}"

    @step("5.2 revolve 360 + revolve cut", ["revolve"], ["0.1 status"])
    def _():
        new_part()
        ok("create_sketch", plane="front", name="Rev_B")
        ok("draw_rectangle", x1_mm=10, y1_mm=0, x2_mm=30, y2_mm=20)
        ok("draw_centerline", x1_mm=0, y1_mm=-5, x2_mm=0, y2_mm=25)
        ok("close_sketch")
        ok("revolve", sketch_name="Rev_B", angle_deg=360, name="Rev_B_Revolve")
        full = math.pi * (900 - 100) * 20
        v = volume()
        check(near(v, full, rel=2e-3), f"360 revolve volume {v} != {full:.1f}")
        ok("create_sketch", plane="front", name="Rev_B_Groove")
        ok("draw_rectangle", x1_mm=20, y1_mm=8, x2_mm=25, y2_mm=12)
        ok("draw_centerline", x1_mm=0, y1_mm=-5, x2_mm=0, y2_mm=25)
        ok("close_sketch")
        ok("revolve", sketch_name="Rev_B_Groove", angle_deg=360, cut=True, name="Rev_B_GrooveCut")
        expected = full - math.pi * (625 - 400) * 4
        v2 = volume()
        check(near(v2, expected, rel=2e-3), f"after revolve-cut volume {v2} != {expected:.1f}")
        return f"boss {v} (exp {full:.1f}); after cut {v2} (exp {expected:.1f})"

    @step("5.3 shell", ["shell"], ["0.1 status"])
    def _():
        new_part()
        draw_box_part(-15, -15, 15, 15, 30, "Shell")
        top = face_index([0, 0, 1])
        ok("shell", thickness_mm=2, selection={"faces": [top]}, name="Shell_Feature")
        expected = 27000 - 26 * 26 * 28
        v = volume()
        check(near(v, expected, rel=1e-3), f"volume {v} != {expected}")
        return f"volume={v} expected={expected}"

    @step("5.4 draft", ["draft"], ["0.1 status"])
    def _():
        new_part()
        draw_box_part(-10, -10, 10, 10, 20, "Draft")
        bottom = face_index([0, 0, -1])
        sides = [f["index"] for f in faces() if f.get("normal") and abs(f["normal"][2]) < 0.01]
        check(len(sides) == 4, f"side faces {sides}")
        ok("draft", angle_deg=5, selection={"faces": sides}, neutral_selection={"faces": [bottom]}, name="Draft_Feature")
        t = math.tan(math.radians(5))
        a = 20.0
        def frustum(b: float) -> float:
            return 20 / 3 * (a * a + a * b + b * b)
        inward, outward = frustum(a - 40 * t), frustum(a + 40 * t)
        v = volume()
        check(near(v, inward, rel=5e-3) or near(v, outward, rel=5e-3), f"volume {v} matches neither inward {inward:.1f} nor outward {outward:.1f} (unchanged would be 8000)")
        return f"volume={v}; {'inward' if near(v, inward, rel=5e-3) else 'outward'} draft (inward {inward:.1f}, outward {outward:.1f})"

    @step("5.5a rib bracket", ["boss_extrude"], ["0.1 status"])
    def _():
        new_part()
        ok("create_sketch", plane="front", name="Rib_L")
        pts = [(0, 0), (40, 0), (40, 5), (5, 5), (5, 40), (0, 40), (0, 0)]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            ok("draw_line", x1_mm=x1, y1_mm=y1, x2_mm=x2, y2_mm=y2)
        ok("close_sketch")
        ok("boss_extrude", sketch_name="Rib_L", depth_mm=40, end_condition="mid_plane", name="Rib_Bracket")
        v0 = volume()
        check(near(v0, 15000, rel=1e-3), f"bracket volume {v0}")
        ok("create_sketch", plane="front", name="Rib_Profile")
        ok("draw_line", x1_mm=25, y1_mm=5, x2_mm=5, y2_mm=25)
        ok("close_sketch")
        X["rib_v0"] = v0
        return f"bracket volume {v0}; gusset line sketch ready"

    @step("5.5 rib (default arguments)", ["rib"], ["5.5a rib bracket"])
    def _():
        ok("rib", thickness_mm=4, sketch_name="Rib_Profile", two_sided=True, name="Rib_Gusset")
        v1 = volume()
        check(near(v1 - X["rib_v0"], 800, rel=1e-2), f"rib added {v1 - X['rib_v0']:.2f} mm3, expected 800 (triangle 200 x 4)")
        return f"rib added {v1 - X['rib_v0']:.2f} (expected 800)"

    @step("5.5b rib reverse_material=True", ["rib"], ["5.5a rib bracket"])
    def _():
        v_before = volume()
        ok("rib", thickness_mm=4, sketch_name="Rib_Profile", two_sided=True, reverse_material=True, name="Rib_Gusset2")
        v1 = volume()
        check(near(v1 - v_before, 800, rel=1e-2), f"rib added {v1 - v_before:.2f} mm3, expected 800 (triangle 200 x 4)")
        return f"rib added {v1 - v_before:.2f} (expected 800)"

    @step("5.6 sweep", ["sweep"], ["0.1 status"])
    def _():
        new_part()
        ok("create_sketch", plane="front", name="Sweep_Profile")
        ok("draw_circle", x_mm=0, y_mm=0, radius_mm=3)
        ok("close_sketch")
        ok("create_sketch", plane="top", name="Sweep_Path")
        ok("draw_line", x1_mm=0, y1_mm=0, x2_mm=0, y2_mm=40)
        ok("close_sketch")
        ok("sweep", profile_sketch="Sweep_Profile", path_sketch="Sweep_Path", name="Sweep_Feature")
        expected = math.pi * 9 * 40
        v = volume()
        check(near(v, expected, rel=5e-3), f"volume {v} != {expected:.2f}")
        return f"volume={v} expected={expected:.2f}"

    @step("5.7 loft + offset plane", ["loft", "create_plane"], ["0.1 status"])
    def _():
        new_part()
        ok("create_sketch", plane="front", name="Loft_1")
        ok("draw_rectangle", x1_mm=-10, y1_mm=-10, x2_mm=10, y2_mm=10)
        ok("close_sketch")
        d = ok("create_plane", mode="offset", selection={"planes": ["front"]}, distance_mm=30, name="Loft_Plane")
        ok("create_sketch", plane_name="Loft_Plane", name="Loft_2")
        ok("draw_rectangle", x1_mm=-5, y1_mm=-5, x2_mm=5, y2_mm=5)
        ok("close_sketch")
        ok("loft", profile_sketches=["Loft_1", "Loft_2"], name="Loft_Feature")
        expected = 30 / 3 * (400 + 200 + 100)
        v = volume()
        check(near(v, expected, rel=5e-3), f"volume {v} != {expected}")
        return f"volume={v} expected={expected}"

    @step("5.8 circular_pattern", ["circular_pattern", "create_axis"], ["0.1 status"])
    def _():
        new_part()
        ok("create_sketch", plane="front", name="Disc_Sketch")
        ok("draw_circle", x_mm=0, y_mm=0, radius_mm=30)
        ok("close_sketch")
        ok("boss_extrude", sketch_name="Disc_Sketch", depth_mm=10, name="Disc_Boss")
        ok("create_sketch", plane="front", name="Disc_HoleSketch")
        ok("draw_circle", x_mm=20, y_mm=0, radius_mm=2)
        ok("close_sketch")
        ok("cut_extrude", sketch_name="Disc_HoleSketch", end_condition="through_all", name="Disc_Hole")
        outer = [f for f in faces(surface_type="cylinder") if near(f.get("radius_mm", 0), 30, abs_tol=0.01)]
        check(outer, "outer cylinder face not found")
        ok("create_axis", selection={"faces": [outer[0]["index"]]}, name="Disc_Axis")
        ok("circular_pattern", selection={"features": ["Disc_Hole"]}, axis_selection={"axes": ["Disc_Axis"]}, count=6, angle_deg=360, equal_spacing=True, name="Disc_Pattern")
        expected = math.pi * 900 * 10 - 6 * math.pi * 4 * 10
        v = volume()
        check(near(v, expected, rel=2e-3), f"volume {v} != {expected:.2f} (6 holes)")
        return f"volume={v} expected={expected:.2f}"

    @step("5.9 mirror_feature", ["mirror_feature"], ["0.1 status"])
    def _():
        new_part()
        draw_box_part(-20, -10, 20, 10, 10, "Mir")
        ok("create_sketch", plane="front", name="Mir_HoleSketch")
        ok("draw_circle", x_mm=10, y_mm=0, radius_mm=2)
        ok("close_sketch")
        ok("cut_extrude", sketch_name="Mir_HoleSketch", end_condition="through_all", name="Mir_Hole")
        v0 = volume()
        ok("mirror_feature", selection={"features": ["Mir_Hole"]}, plane_selection={"planes": ["right"]}, name="Mir_Mirror")
        expected = 8000 - 2 * math.pi * 4 * 10
        v = volume()
        check(near(v0, 8000 - math.pi * 40, rel=1e-3), f"pre-mirror volume {v0}")
        check(near(v, expected, rel=1e-3), f"volume {v} != {expected:.2f}")
        return f"before {v0:.2f}; after {v} (expected {expected:.2f})"

    # ---------------------------------------------------------------- 6. Drawing model part
    @step("6.1 drawing model part", ["add_dimension"], ["0.1 status"])
    def _():
        new_part()
        ok("create_sketch", plane="front", name="Drw_Sketch")
        ok("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=20)
        segs = segments()
        bottom = next(s for s in segs if near(s["start_mm"][1], 0, abs_tol=1e-3) and near(s["end_mm"][1], 0, abs_tol=1e-3))
        left = next(s for s in segs if near(s["start_mm"][0], 0, abs_tol=1e-3) and near(s["end_mm"][0], 0, abs_tol=1e-3))
        ok("add_dimension", selection={"sketch_segments": [bottom["index"]]}, kind="horizontal", value_mm=40, place_x_mm=20, place_y_mm=-8, name="Drw_W")
        ok("add_dimension", selection={"sketch_segments": [left["index"]]}, kind="vertical", value_mm=20, place_x_mm=-8, place_y_mm=10, name="Drw_H")
        dims = ok("list_dimensions")["dimensions"]
        check(len(dims) >= 2, f"dimensions {dims}")
        ok("close_sketch")
        ok("boss_extrude", sketch_name="Drw_Sketch", depth_mm=10, name="Drw_Boss")
        ok("create_sketch", plane="front", name="Drw_HoleSketch")
        ok("draw_circle", x_mm=20, y_mm=10, radius_mm=3)
        ok("close_sketch")
        ok("cut_extrude", sketch_name="Drw_HoleSketch", end_condition="through_all", name="Drw_Hole")
        v = volume()
        expected = 8000 - math.pi * 9 * 10
        check(near(v, expected, rel=1e-3), f"volume {v} != {expected:.2f}")
        path = Path(p("DRW.sldprt"))
        ok("save_document", path=str(path))
        file_ok(path, 1000)
        X["drw_path"] = path
        return f"volume={v}; dims={[d['full_name'] for d in dims]}; saved {path.name}"

    # ---------------------------------------------------------------- 7. Assembly (T3 part twice)
    @step("7.1 new assembly", ["create_new_document"], ["T3.10 save"])
    def _():
        a = app()
        data = ok("create_new_document", kind="assembly")
        X["docs"].append(data["document"]["title"])
        check(data["document"]["document_type"] == "assembly", f"{data['document']}")
        X["asm_title"] = data["document"]["title"]
        return f"title={data['document']['title']}"

    @step("7.2 insert_component x2 (relative placement)", ["insert_component", "list_components"], ["7.1 new assembly"])
    def _():
        ok("insert_component", path=str(X["t3_path"]), x_mm=0, y_mm=0, z_mm=0)
        comps = ok("list_components")["components"]
        check(len(comps) == 1, f"components {comps}")
        ok("insert_component", path=str(X["t3_path"]), x_mm=100, y_mm=0, z_mm=20)
        comps = sorted(ok("list_components")["components"], key=lambda c: c["name"])
        check(len(comps) == 2, f"components {[c['name'] for c in comps]}")
        o1, o2 = comps[0]["origin_mm"], comps[1]["origin_mm"]
        X["asm_comps"] = [c["name"] for c in comps]
        X["asm_origins"] = [o1, o2]
        delta = [o2[i] - o1[i] for i in range(3)]
        check(all(near(a, b, abs_tol=0.01) for a, b in zip(delta, [100, 0, 20])), f"origin delta {delta}, expected (100,0,20)")
        return f"components={[(c['name'], c['origin_mm'], c['fixed']) for c in comps]} delta={delta}"

    @step("7.2c insert_component absolute origin", ["insert_component"], ["7.2 insert_component x2 (relative placement)"])
    def _():
        o1 = X["asm_origins"][0]
        check(all(near(c, 0.0, abs_tol=0.01) for c in o1), f"component inserted at (0,0,0) has origin {o1}; the x/y/z arguments do not place the component origin")
        return f"origin {o1}"

    @step("7.3 assembly topology", ["list_bodies", "list_faces"], ["7.2 insert_component x2 (relative placement)"])
    def _():
        nb = n_bodies()
        nf = len(faces())
        check(nb == 2, f"bodies {nb}")
        check(nf == 2 * X["t3_faces"], f"faces {nf} != 2 x {X['t3_faces']}")
        return f"bodies={nb} faces={nf} (2 x {X['t3_faces']})"

    @step("7.4 add_mate + list_mates", ["add_mate", "list_mates"], ["7.2 insert_component x2 (relative placement)"])
    def _():
        before = len(ok("list_mates")["mates"])
        bottoms = faces(normal=[0, 0, -1])
        check(len(bottoms) == 2, f"-Z faces across components: {len(bottoms)}")
        ok("add_mate", mate_type="coincident", selection={"faces": [bottoms[0]["index"], bottoms[1]["index"]]}, alignment="aligned")
        mates = ok("list_mates")["mates"]
        check(len(mates) == before + 1, f"mates {before} -> {len(mates)}")
        check(mates[-1].get("mate_type") == "coincident", f"mate {mates[-1]}")
        comps = ok("list_components")["components"]
        zs = [c["origin_mm"][2] for c in comps]
        check(near(zs[0], zs[1], abs_tol=0.01), f"mate did not bring origins to the same z: {zs}")
        return f"mates {before} -> {len(mates)} {mates[-1]}; origins after mate {[(c['name'], c['origin_mm']) for c in comps]}"

    @step("7.5 set_component_fixed", ["set_component_fixed"], ["7.4 add_mate + list_mates"])
    def _():
        name = X["asm_comps"][1]
        before = {c["name"]: c["fixed"] for c in ok("list_components")["components"]}
        ok("set_component_fixed", component_names=[name], fixed=True)
        mid = {c["name"]: c["fixed"] for c in ok("list_components")["components"]}
        check(mid[name] is True, f"{name} not fixed: {mid}")
        ok("set_component_fixed", component_names=[name], fixed=False)
        end = {c["name"]: c["fixed"] for c in ok("list_components")["components"]}
        check(end[name] is False, f"{name} still fixed: {end}")
        return f"fixed flags before={before} after fix={mid} after float={end}"

    @step("7.6 assembly bbox + save", ["get_bounding_box", "save_document"], ["7.4 add_mate + list_mates"])
    def _():
        size = bbox_size()
        bodies = ok("list_bodies")["bodies"]
        lo = [min(b["min_mm"][i] for b in bodies) for i in range(3)]
        hi = [max(b["max_mm"][i] for b in bodies) for i in range(3)]
        union = [round(hi[i] - lo[i], 4) for i in range(3)]
        path = Path(p("T3_asm.sldasm"))
        ok("save_document", path=str(path))
        n = file_ok(path, 1000)
        check(all(near(a, b, abs_tol=0.05) for a, b in zip(size, union)), f"get_bounding_box {size} disagrees with the union of list_bodies boxes {union} (body boxes: {[(b['min_mm'], b['max_mm']) for b in bodies]})")
        return f"bbox={size} union_of_body_boxes={union}; {path.name} {n} bytes"

    # ---------------------------------------------------------------- 8. Drawing
    @step("8.1 create_drawing", ["create_drawing", "list_sheets"], ["6.1 drawing model part"])
    def _():
        d = ok("create_drawing", paper_size="A3", first_angle=False)
        X["docs"].append(d["document"]["title"])
        sh = ok("list_sheets")
        check(len(sh["sheets"]) == 1, f"sheets {sh['sheets']}")
        check(sh.get("first_angle") is False, f"first_angle={sh.get('first_angle')}")
        size = sh.get("sheet_size_mm")
        check(size is not None and near(size[0], 420, abs_tol=1) and near(size[1], 297, abs_tol=1), f"sheet size {size}")
        X["sheet1"] = sh["active_sheet"]
        X["meta"]["template_used_drawing"] = str(app().GetUserPreferenceStringValue(10))
        return f"sheets={sh['sheets']} size={size} first_angle={sh['first_angle']} scale={sh.get('scale')}"

    @step("8.2 add_sheet / activate_sheet", ["add_sheet", "activate_sheet"], ["8.1 create_drawing"])
    def _():
        ok("add_sheet", name="Sheet_Two", paper_size="A4", first_angle=False)
        names = [s["name"] for s in ok("list_sheets")["sheets"]]
        check(len(names) == 2 and "Sheet_Two" in names, f"sheets {names}")
        ok("activate_sheet", name=X["sheet1"])
        check(ok("list_sheets")["active_sheet"] == X["sheet1"], "sheet1 not active")
        return f"sheets={names}, reactivated {X['sheet1']}"

    @step("8.3 insert_standard_views", ["insert_standard_views", "list_drawing_views"], ["8.1 create_drawing"])
    def _():
        before = len(model_views())
        d = ok("insert_standard_views", model_path=str(X["drw_path"]), first_angle=False)
        views = model_views()
        added = len(views) - before
        check(added >= 3, f"views {before} -> {len(views)}")
        check(all(v.get("model", "").lower().endswith("drw.sldprt") for v in views), f"view models {[v.get('model') for v in views]}")
        X["std_views"] = views
        front = min(views, key=lambda v: v["position_mm"][0] + v["position_mm"][1])
        X["front_view"] = front["name"]
        X["front_pos"] = front["position_mm"]
        return f"+{added} views: {[(v['name'], v['type'], v['position_mm']) for v in views]}"

    @step("8.4 insert_model_view + shaded-with-edges [verify-live #2]", ["insert_model_view"], ["8.3 insert_standard_views"])
    def _():
        doc = active_doc()
        before = len(model_views())
        d = ok("insert_model_view", view="isometric", x_mm=330, y_mm=60, scale=0.5, display_mode="shaded_with_edges", model_path=str(X["drw_path"]))
        views = model_views()
        check(len(views) == before + 1, f"views {before} -> {len(views)}")
        entry = d["view"]
        name = entry["name"]
        X["iso_view"] = name
        check(near(entry.get("scale", 0), 0.5, rel=1e-3), f"scale {entry.get('scale')} != 0.5")
        v = view_by_name(active_doc(), name)
        mode = safe(v, "GetDisplayMode")
        edges_flag = safe(v, "GetDisplayEdgesInShadedMode")
        X["verify_dispmode"] = {"mode": mode, "edges_in_shaded": edges_flag}
        if not ((mode == 3 and edges_flag) or mode == 7):
            # Diagnostic only: does the documented alternative work?
            try:
                flag_methods(v, "SetDisplayMode3").SetDisplayMode3(False, 7, False, False)
                alt = (safe(v, "GetDisplayMode"), safe(v, "GetDisplayEdgesInShadedMode"))
            except Exception as exc:  # noqa: BLE001
                alt = f"alt call raised {exc}"
            X["verify_dispmode"]["alt_swSHADED_EDGES_7"] = str(alt)
            raise Silent(f"display_mode=shaded_with_edges gave GetDisplayMode={mode}, EdgesInShadedMode={edges_flag}; alternative mode 7 -> {alt}")
        return f"+1 view '{name}' scale={entry['scale']} GetDisplayMode={mode} EdgesInShadedMode={edges_flag}"

    @step("8.5 insert_projected_view", ["insert_projected_view"], ["8.3 insert_standard_views"])
    def _():
        before = len(model_views())
        d = ok("insert_projected_view", parent_view=X["iso_view"], direction="right", offset_mm=60)
        views = model_views()
        check(len(views) == before + 1, f"views {before} -> {len(views)}")
        check(d["view"].get("type") == "projected", f"type {d['view'].get('type')}")
        X["proj_from_iso"] = d["view"]["name"]
        return f"+1 view {d['view']['name']} type={d['view']['type']} pos={d['view'].get('position_mm')}"

    @step("8.6 set_drawing_view display/tangent [verify-live #2b]", ["set_drawing_view"], ["8.4 insert_model_view + shaded-with-edges [verify-live #2]"])
    def _():
        name = X["iso_view"]
        d = ok("set_drawing_view", name=name, x_mm=320, y_mm=70, scale=0.4, display_mode="hidden_lines_removed", tangent_edges="visible")
        v = view_by_name(active_doc(), name)
        pos = safe(v, "Position")
        scale = safe(v, "ScaleDecimal")
        mode = safe(v, "GetDisplayMode")
        tangent = safe(v, "GetDisplayTangentEdges2")
        X["verify_tangent"] = {"tangent": tangent, "mode": mode}
        check(pos is not None and near(pos[0] * 1000, 320, abs_tol=0.5) and near(pos[1] * 1000, 70, abs_tol=0.5), f"position {pos}")
        check(near(scale, 0.4, rel=1e-3), f"scale {scale}")
        check(mode == 2, f"GetDisplayMode={mode}, expected 2 (hidden lines removed)")
        if tangent is None:
            raise Unverified(f"position/scale/mode verified (pos={pos}, scale={scale}, mode={mode}); tangent-edge mode could not be read back")
        check(int(tangent) == 2, f"GetDisplayTangentEdges2={tangent}, expected 2 (visible)")
        return f"pos=({pos[0] * 1000:.1f},{pos[1] * 1000:.1f}) scale={scale} mode={mode} tangent={tangent}"

    @step("8.7 insert_section_view [verify-live #3]", ["insert_section_view"], ["8.3 insert_standard_views"])
    def _():
        cx, cy = X["front_pos"]
        before = len(model_views())
        d = ok("insert_section_view", x1_mm=cx, y1_mm=cy - 16, x2_mm=cx, y2_mm=cy + 16, place_x_mm=cx + 150, place_y_mm=cy + 100, parent_view=X["front_view"], label="A")
        views = model_views()
        check(len(views) == before + 1, f"views {before} -> {len(views)}")
        check(d["view"].get("type") == "section", f"type {d['view'].get('type')}")
        X["section_view"] = d["view"]["name"]
        sv = view_by_name(active_doc(), d["view"]["name"])
        X["verify_section"] = {"entry": d["view"]}
        return f"+1 section view '{d['view']['name']}' type=section scale={d['view'].get('scale')} pos={d['view'].get('position_mm')} (cut line at x={cx:.1f}, y {cy - 16:.1f}..{cy + 16:.1f})"

    @step("8.8 section with depth_mm (Partial question) [verify-live #3b]", ["insert_section_view"], ["8.3 insert_standard_views"])
    def _():
        cx, cy = X["front_pos"]
        before = len(model_views())
        d = ok("insert_section_view", x1_mm=cx, y1_mm=cy - 16, x2_mm=cx, y2_mm=cy + 16, place_x_mm=cx + 150, place_y_mm=cy - 60, parent_view=X["front_view"], label="B", depth_mm=3)
        views = model_views()
        check(len(views) == before + 1, f"views {before} -> {len(views)}")
        check(d["view"].get("type") == "section", f"type {d['view'].get('type')}")
        raise Unverified(f"section view created with depth_mm=3 ('{d['view']['name']}'); whether depth was honoured (swCreateSectionView_Partial=16) cannot be measured through the API; eyeball in the screenshot")

    @step("8.9 insert_detail_view [verify-live #4]", ["insert_detail_view"], ["8.3 insert_standard_views"])
    def _():
        cx, cy = X["front_pos"]
        before = len(model_views())
        d = ok("insert_detail_view", center_x_mm=cx, center_y_mm=cy, radius_mm=7, place_x_mm=360, place_y_mm=250, parent_view=X["front_view"], label="D", scale_numerator=4, scale_denominator=1)
        views = model_views()
        check(len(views) == before + 1, f"views {before} -> {len(views)}")
        check(d["view"].get("type") == "detail", f"type {d['view'].get('type')}")
        check(near(d["view"].get("scale", 0), 4.0, rel=1e-2), f"detail scale {d['view'].get('scale')} != 4")
        return f"+1 detail view '{d['view']['name']}' scale={d['view']['scale']} pos={d['view'].get('position_mm')}"

    @step("8.10 activate_drawing_view / create_drawing_sketch", ["activate_drawing_view", "create_drawing_sketch"], ["8.3 insert_standard_views"])
    def _():
        ok("activate_drawing_view", name=X["front_view"])
        ok("create_drawing_sketch", view_name=X["front_view"])
        doc = active_doc()
        sk = doc.SketchManager.ActiveSketch
        check(sk is not None, "no active sketch in the view")
        ok("draw_line", x1_mm=0, y1_mm=0, x2_mm=5, y2_mm=5)
        n = len(segments())
        check(n >= 1, f"segments {n}")
        ok("close_sketch")
        return f"sketch opened in '{X['front_view']}', {n} segment drawn, closed"

    @step("8.11 insert_model_annotations", ["insert_model_annotations"], ["8.3 insert_standard_views"])
    def _():
        doc = active_doc()
        before = all_view_annotation_types(doc).count(4)
        d = ok("insert_model_annotations", types=["dimensions"], all_views=False, view_name=X["front_view"])
        after = all_view_annotation_types(doc).count(4)
        added = d.get("dimensions_added", 0)
        check(added > 0, f"dimensions_added={added}")
        if after - before <= 0:
            raise Silent(f"handler reports {added} dimensions added, but display-dimension annotations went {before} -> {after}")
        return f"handler dimensions_added={added}; display dimensions {before} -> {after}"

    @step("8.12 auto_dimension_view", ["auto_dimension_view"], ["8.3 insert_standard_views"])
    def _():
        doc = active_doc()
        target = next(v["name"] for v in model_views() if v.get("type") == "projected" and v["name"] != X.get("proj_from_iso"))
        before = all_view_annotation_types(doc).count(4)
        d = ok("auto_dimension_view", view_name=target, horizontal_scheme="baseline", vertical_scheme="baseline")
        after = all_view_annotation_types(doc).count(4)
        if after - before <= 0:
            raise Silent(f"handler claims +{d.get('dimensions_added')} dims but annotation count {before} -> {after}")
        return f"view {target}: handler +{d['dimensions_added']}; display dimensions {before} -> {after}"

    @step("8.13 insert_center_marks", ["insert_center_marks"], ["8.3 insert_standard_views"])
    def _():
        doc = active_doc()
        before = all_view_annotation_types(doc).count(13)
        d = ok("insert_center_marks", view_name=X["front_view"])
        after = all_view_annotation_types(doc).count(13)
        if after - before <= 0:
            raise Silent(f"handler ok but center-mark annotations {before} -> {after}")
        return f"center-mark annotations {before} -> {after}; legacy={d.get('legacy_center_mark_features')}"

    @step("8.14 insert_centerlines", ["insert_centerlines"], ["8.3 insert_standard_views"])
    def _():
        doc = active_doc()
        target = [v["name"] for v in model_views() if v.get("type") == "projected" and v["name"] != X.get("proj_from_iso")][-1]
        types_before = all_view_annotation_types(doc)
        d = ok("insert_centerlines", view_name=target)
        types_after = all_view_annotation_types(doc)
        gained = len(types_after) - len(types_before)
        # A top/side view of a through hole shows hidden lines only; nothing to add is legitimate.
        if gained <= 0:
            raise Unverified(f"handler ok ({d.get('centerline_kind')}) on '{target}' but no annotation gained; the view may have no circular edges")
        return f"annotations {len(types_before)} -> {len(types_after)} on {target}"

    @step("8.15 add_note", ["add_note"], ["8.1 create_drawing"])
    def _():
        doc = active_doc()
        before = all_view_annotation_types(doc).count(6)
        ok("add_note", text="SMOKE TEST NOTE", x_mm=30, y_mm=30, height_mm=5)
        after = all_view_annotation_types(doc).count(6)
        check(after == before + 1, f"note annotations (all views) {before} -> {after}")
        return f"note annotations (all views) {before} -> {after}"

    @step("8.16 final view list", ["list_drawing_views"], ["8.3 insert_standard_views"])
    def _():
        views = list_views()
        check(views and views[0].get("type") == "sheet", f"first entry {views[:1]}")
        return f"{len(views)} entries: {[(v['name'], v['type'], v.get('scale')) for v in views]}"

    @step("8.17 save drawing", ["save_document"], ["8.3 insert_standard_views"])
    def _():
        path = Path(p("DRW.slddrw"))
        ok("save_document", path=str(path))
        n = file_ok(path, 1000)
        return f"{path.name} {n} bytes"

    @step("8.18 drawing screenshot", ["capture_screenshot"], ["8.3 insert_standard_views"])
    def _():
        payload = call("capture_screenshot", view="current", width_px=1200)
        check(payload.get("ok"), f"not ok: {payload.get('message')}")
        raw = base64.b64decode(payload["_image_png_base64"])
        out = RUN_DIR / "DRW_screenshot.png"
        out.write_bytes(raw)
        check(raw[:4] == b"\x89PNG" and len(raw) > 2000, f"{len(raw)} bytes")
        return f"{out.name} {len(raw)} bytes"

    # ---------------------------------------------------------------- 9. open_document, then risky exports last
    @step("9.1 open_document (sandbox file)", ["open_document"], ["T3.10 save"])
    def _():
        a = app()
        title = X["t3_title"]
        # Close the T3 part (our own document) so the open really loads from disk.
        # Close the assembly that references it first.
        for doc_obj in as_list(value(a, "GetDocuments")):
            t = str(value(doc_obj, "GetTitle"))
            if t not in X["baseline_docs"] and int(value(doc_obj, "GetType")) in (2, 3):
                a.CloseDoc(t)
        a.CloseDoc(title)
        names = [str(value(x, "GetTitle")) for x in as_list(value(a, "GetDocuments"))]
        check(title not in names, f"T3 part still open: {names}")
        d = ok("open_document", path=str(X["t3_path"]))
        info = d["document"]
        check(Path(info["path"]).resolve() == X["t3_path"].resolve() and info["document_type"] == "part", f"{info}")
        v = volume()
        check(near(v, X["t3_expected_volume"], rel=1e-3), f"reopened volume {v}")
        return f"reopened {Path(info['path']).name}; volume {v}"

    for ext, minb in (("stl", 500),):
        @step(f"9.2 export .{ext} (dialog risk, run last)", ["export_document"], ["9.1 open_document (sandbox file)"])
        def _(ext=ext, minb=minb):
            target = Path(p(f"T3_core.{ext}"))
            ok("export_document", path=str(target))
            n = file_ok(target, minb)
            return f"{target.name} {n} bytes"

    @step("9.3 export .3mf (dialog risk, run last)", ["export_document"], ["9.1 open_document (sandbox file)"])
    def _():
        target = Path(p("T3_core.3mf"))
        payload = call("export_document", path=str(target))
        exists = target.is_file()
        size = target.stat().st_size if exists else 0
        if not payload.get("ok"):
            raise Fail(f"export_document: {payload.get('message')} (file on disk afterwards: {exists}, {size} bytes)")
        n = file_ok(target, 500)
        return f"{target.name} {n} bytes"

    # ---------------------------------------------------------------- Cleanup (own documents only, never saving)
    @step("99 cleanup own documents", [])
    def _():
        a = app()
        closed, left = [], []
        for _ in range(3):
            docs = as_list(value(a, "GetDocuments"))
            mine = [d for d in docs if str(value(d, "GetTitle")) not in X["baseline_docs"]]
            if not mine:
                break
            mine.sort(key=lambda d: -int(value(d, "GetType")))  # drawings, assemblies, then parts
            for d in mine:
                t = str(value(d, "GetTitle"))
                try:
                    a.CloseDoc(t)
                    closed.append(t)
                except Exception as exc:  # noqa: BLE001
                    left.append(f"{t}: {exc}")
        remaining = [str(value(x, "GetTitle")) for x in as_list(value(a, "GetDocuments"))]
        X["meta"]["docs_remaining"] = remaining
        check(sorted(remaining) == sorted(X["baseline_docs"]), f"documents still open: {remaining} (baseline {X['baseline_docs']}); errors {left}")
        return f"closed {len(closed)} documents without saving; session back to baseline {X['baseline_docs']}"

    return finish()


def finish() -> int:
    counts: dict[str, int] = {}
    for r in RESULTS:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    X["meta"]["case_counts"] = counts
    _dump()
    print("CASE COUNTS:", counts, flush=True)
    print("Results:", RUN_DIR / "results.json", flush=True)
    return 0 if not any(r["status"] in (FAIL, SILENT, HANG) for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
