# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for details.

"""Verify an isolated wheel install, offline tests and actual MCP stdio discovery.

SOLIDWORKS must already be running. --scratch exercises geometry calls on a new
part and closes it afterwards; default calls only read the active document.
"""

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import sys
import unittest


async def protocol(install, expected, catalog, scratch):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ, PYTHONPATH=str(install))
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "solidworks_mcp.server"],
                                       env=env, cwd=str(install.parent))
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            response = await session.list_tools()
            if len(response.tools) != expected or len({tool.name for tool in response.tools}) != expected:
                raise RuntimeError("MCP tool count or uniqueness differs from the expected release.")
            async def call(name, arguments=None):
                output = await session.call_tool(name, arguments or {})
                payload = json.loads(output.content[0].text)
                if not payload["ok"]:
                    raise RuntimeError(f"Installed MCP call failed: {name}: {payload}")
                return payload.get("data", {})
            connections = await call("list_solidworks_sessions")
            attached = connections["attached_process_id"]
            if attached is None:
                raise RuntimeError("Cannot identify the installed MCP SolidWorks connection.")
            selected = await call("select_solidworks_session", {"process_id": attached})
            if selected["attached_process_id"] != attached:
                raise RuntimeError("Installed MCP instance selection differs.")
            initial = await call("list_open_documents")
            original = initial["active_title"]
            title = None
            try:
                if scratch:
                    title = (await call("create_new_document", {"kind": "part"}))["document"]["title"]
                    points = [[0, 0, 0], [10, 5, 2], [20, 0, 4]]
                    await call("create_curve_through_points", {"name": "InstalledCurve", "points_mm": points})
                    actual = await call("get_curve_points", {"name": "InstalledCurve"})
                    if actual["curve"]["points_mm"] != points:
                        raise RuntimeError("Installed MCP curve coordinate readback differs.")
                    await call("create_coordinate_system", {"name": "InstalledCS", "origin_mm": [2, 3, 4]})
                    await call("create_sketch", {"plane": "front", "name": "InstalledRevolveProfile"})
                    await call("draw_line", {"x1_mm": 5, "y1_mm": 0, "x2_mm": 5, "y2_mm": 10})
                    await call("draw_centerline", {"x1_mm": 0, "y1_mm": 0, "x2_mm": 0, "y2_mm": 10})
                    await call("close_sketch")
                    await call("surface_revolve", {"sketch_name": "InstalledRevolveProfile"})
                    surfaces = await call("list_surface_bodies")
                    area = sum(body["area_mm2"] for body in surfaces["surface_bodies"])
                    if not math.isclose(area, 2 * math.pi * 5 * 10, rel_tol=1e-7):
                        raise RuntimeError("Installed MCP revolved surface area differs.")
                    edges = await call("list_edges", {"body_type": "surface"})
                    if len(edges["edges"]) != 2:
                        raise RuntimeError("Installed MCP surface-edge enumeration differs.")
                    await call("extend_surface", {"selection": {"surface_edges": [edges["edges"][0]["index"]]}, "distance_mm": 5})
                    surfaces = await call("list_surface_bodies")
                    actual_area = sum(body["area_mm2"] for body in surfaces["surface_bodies"])
                    if not math.isclose(actual_area, 2 * math.pi * 5 * 15, rel_tol=1e-6, abs_tol=0.05):
                        raise RuntimeError(f"Installed MCP surface extension area differs: {actual_area}; edges={edges['edges']}.")
                    await call("create_sketch", {"plane": "front", "name": "InstalledHoleProfile"})
                    await call("draw_rectangle", {"x1_mm": 20, "y1_mm": 20, "x2_mm": 30, "y2_mm": 30})
                    await call("draw_circle", {"x_mm": 25, "y_mm": 25, "radius_mm": 1})
                    await call("close_sketch")
                    await call("planar_surface", {"sketch_name": "InstalledHoleProfile"})
                    faces = await call("list_faces", {"body_type": "surface", "surface_type": "plane"})
                    if len(faces["faces"]) != 1:
                        raise RuntimeError("Installed MCP surface-face enumeration differs.")
                    await call("untrim_surface", {"selection": {"surface_faces": [faces["faces"][0]["index"]]}, "face_mode": "internal"})
                    faces = await call("list_faces", {"body_type": "surface", "surface_type": "plane"})
                    if not math.isclose(faces["faces"][0]["area_mm2"], 100, rel_tol=1e-7):
                        raise RuntimeError("Installed MCP internal untrim area differs.")
                    await call("create_sketch", {"plane": "front", "name": "InstalledFillProfile"})
                    await call("draw_rectangle", {"x1_mm": 60, "y1_mm": 60, "x2_mm": 70, "y2_mm": 70})
                    await call("close_sketch")
                    filled = await call("fill_surface", {"boundaries": [{"selection": {"sketches": ["InstalledFillProfile"]}}]})
                    if filled["native_continuity_controls"] != [0]:
                        raise RuntimeError("Installed MCP filled-surface continuity readback differs.")
                    faces = await call("list_faces", {"body_type": "surface", "surface_type": "plane"})
                    filled_face = next(face for face in faces["faces"] if face["point_mm"][0] >= 50)
                    if not math.isclose(filled_face["area_mm2"], 100, rel_tol=1e-7):
                        raise RuntimeError("Installed MCP filled-surface area differs.")
                    edges = await call("list_edges", {"body_type": "surface"})
                    boundary = next(edge["index"] for edge in edges["edges"] if edge["body_index"] == filled_face["body_index"])
                    await call("ruled_surface", {"selection": {"surface_edges": [boundary]}, "mode": "tapered",
                               "length_mm": 5, "angle_deg": 30, "direction_selection": {"planes": ["front"]}})
                    faces = await call("list_faces", {"body_type": "surface"})
                    patch = next(face for face in faces["faces"] if math.isclose(face["area_mm2"], 50, rel_tol=1e-7))
                    if not math.isclose(abs(patch["normal"][2]), 0.5, abs_tol=1e-6):
                        raise RuntimeError("Installed MCP ruled-surface taper inclination differs.")
                    await call("create_sketch", {"plane": "front", "name": "InstalledSelectiveHoles"})
                    await call("draw_rectangle", {"x1_mm": 90, "y1_mm": 90, "x2_mm": 100, "y2_mm": 100})
                    for x in (93, 97):
                        await call("draw_circle", {"x_mm": x, "y_mm": 95, "radius_mm": 1})
                    await call("close_sketch")
                    await call("planar_surface", {"sketch_name": "InstalledSelectiveHoles"})
                    faces = (await call("list_faces", {"body_type": "surface"}))["faces"]
                    hole_face = next(face for face in faces if face["point_mm"][0] >= 90)
                    edges = (await call("list_edges", {"body_type": "surface"}))["edges"]
                    holes = [edge["index"] for edge in edges
                             if edge["body_index"] == hole_face["body_index"] and edge["curve_type"] == "circle"]
                    if len(holes) != 2:
                        raise RuntimeError("Installed MCP hole fixture topology differs.")
                    await call("delete_surface_holes", {"selection": {"surface_edges": [holes[0]]}})
                    faces = (await call("list_faces", {"body_type": "surface"}))["faces"]
                    hole_face = next(face for face in faces if face["point_mm"][0] >= 90)
                    if not math.isclose(hole_face["area_mm2"], 100 - math.pi, rel_tol=1e-7):
                        raise RuntimeError("Installed MCP selective hole removal changed an unselected hole.")
                    await call("create_sketch", {"plane": "front", "name": "InstalledSweepProfile"})
                    await call("draw_line", {"x1_mm": -5, "y1_mm": 200, "x2_mm": 5, "y2_mm": 200})
                    await call("close_sketch")
                    await call("create_sketch", {"plane": "right", "name": "InstalledSweepPath"})
                    await call("draw_line", {"x1_mm": 0, "y1_mm": 200, "x2_mm": -10, "y2_mm": 200})
                    await call("close_sketch")
                    swept = await call("surface_sweep", {"profile_sketch": "InstalledSweepProfile", "path_sketch": "InstalledSweepPath",
                                       "twist_control": "constant_twist", "twist_angle_deg": 90, "reverse_twist": True})
                    if not math.isclose(swept["native_settings"]["twist_angle_deg"], -90, abs_tol=1e-8):
                        raise RuntimeError("Installed MCP signed sweep twist readback differs.")
                    edges = (await call("list_edges", {"body_type": "surface"}))["edges"]
                    midpoints = [edge["point_mm"] for edge in edges if edge.get("point_mm")
                                 and edge["point_mm"][1] > 190 and math.isclose(edge["point_mm"][2], 5, abs_tol=0.02)]
                    if len(midpoints) != 2 or any(p[0] * (p[1] - 200) >= 0 for p in midpoints):
                        raise RuntimeError(f"Installed MCP reversed sweep geometry differs: {midpoints}.")
                    await call("create_sketch", {"plane": "front", "name": "InstalledMidProfile"})
                    await call("draw_rectangle", {"x1_mm": 300, "y1_mm": 300, "x2_mm": 320, "y2_mm": 310})
                    await call("close_sketch")
                    await call("boss_extrude", {"sketch_name": "InstalledMidProfile", "depth_mm": 2})
                    middle = (await call("mid_surface", {"name": "InstalledMid"}))["midsurface"]
                    if middle["face_pair_count"] != 1 or middle["sheet_count"] != 1:
                        raise RuntimeError("Installed MCP midsurface topology differs.")
                    if not math.isclose(middle["area_mm2"], 200, abs_tol=1e-7) or not math.isclose(middle["face_pairs"][0]["thickness_mm"], 2, abs_tol=1e-7):
                        raise RuntimeError("Installed MCP midsurface area/thickness differs.")
                    if not math.isclose(middle["faces"][0]["point_mm"][2], 1, abs_tol=1e-7):
                        raise RuntimeError("Installed MCP midsurface placement differs.")
                    if (await call("get_mid_surface_data", {"name": "InstalledMid"}))["midsurface"] != middle:
                        raise RuntimeError("Installed MCP read-only midsurface inspection differs.")
                    await call("create_sketch", {"plane": "front", "name": "InstalledTrimProfile"})
                    await call("draw_rectangle", {"x1_mm": 400, "y1_mm": 400, "x2_mm": 410, "y2_mm": 410})
                    await call("close_sketch")
                    await call("planar_surface", {"sketch_name": "InstalledTrimProfile", "name": "InstalledTrimSource"})
                    bodies = (await call("list_surface_bodies"))["surface_bodies"]
                    source = next(body["index"] for body in bodies if body["name"] == "InstalledTrimSource")
                    await call("create_plane", {"mode": "offset", "selection": {"planes": ["right"]}, "distance_mm": 404, "name": "InstalledKnife"})
                    trim_args = {"surface_body_indices": [source], "trim_selection": {"planes": ["InstalledKnife"]}}
                    before = await call("list_features")
                    regions = (await call("preview_surface_trim", trim_args))["regions"]
                    if before != await call("list_features") or [round(r["area_mm2"]) for r in regions] != [40, 60]:
                        raise RuntimeError("Installed MCP trim preview changed features or returned wrong regions.")
                    trimmed = await call("trim_surface", {**trim_args, "region_indices": [0], "name": "InstalledTrim"})
                    bodies = (await call("list_surface_bodies"))["surface_bodies"]
                    actual = next(body for body in bodies if body["name"] == "InstalledTrim")
                    if not math.isclose(actual["area_mm2"], 40, abs_tol=1e-7):
                        raise RuntimeError("Installed MCP trim retained the wrong sheet area.")
                    if (await call("get_surface_trim_data", {"name": "InstalledTrim"}))["trim"] != trimmed["trim"]:
                        raise RuntimeError("Installed MCP trim definition readback differs.")
                await call("list_reference_points")
                systems = await call("list_coordinate_systems")
                if scratch and systems["coordinate_systems"][0]["origin_mm"] != [2, 3, 4]:
                    raise RuntimeError("Installed MCP coordinate-system origin readback differs.")
            finally:
                if title:
                    await call("close_document", {"name": title, "discard_changes": True})
                if scratch and original:
                    await call("activate_document", {"name": original})
            if catalog:
                catalog.parent.mkdir(parents=True, exist_ok=True)
                catalog.write_text(json.dumps([tool.model_dump(mode="json") for tool in response.tools],
                                              ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--tool-count", type=int, required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--scratch", action="store_true", help="Verify geometry calls on a new temporary part, then close it.")
    args = parser.parse_args()
    install = args.install.resolve()
    sys.path.insert(0, str(install))
    from solidworks_mcp import server

    if not Path(server.__file__).resolve().is_relative_to(install):
        raise RuntimeError("Imported source checkout instead of the isolated installation.")
    if len(server.TOOLS) != args.tool_count:
        raise RuntimeError("Installed tool count differs from the expected release.")
    repo = Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(str(repo / "tests"), pattern="test_*.py")
    checks = unittest.TextTestRunner(verbosity=1).run(suite)
    if not checks.wasSuccessful():
        raise RuntimeError("Installed-package offline checks failed.")
    asyncio.run(protocol(install, args.tool_count, args.catalog, args.scratch))
    print(f"Installed wheel: {checks.testsRun} offline checks and MCP stdio discovery/native calls passed; {args.tool_count} tools.")


if __name__ == "__main__":
    main()
