# Verification: phase 5 file/inspect fixes (#10, #18, #19, #21)

Offline review. Full suite: 609 tests OK (the earlier _oleobj_ compat failures are gone).

- (a) #10 PASS. Other whats_wrong callers (sw_edit 280/353, sw_feature 1361, sw_inspect 449, feature_result) are untouched. Warnings split by is_warning. ForceRebuild3 and ForceRebuildAll are in the compat list, called as ForceRebuild3(False) via flag_methods under dialogs_suppressed. ok = no errors AND (EditRebuild3 ok OR force ran). A failed rebuild with no problems stays ok:false when ForceRebuild3 raises.
  - Minor: the ForceRebuild3 return value is ignored (sw_file.py rebuild_document, `forced = True`), so a False return still counts as success.
  - Minor: whats_wrong swallows exceptions and returns [], so a failed read could hide errors after a forced rebuild.
- (b) #18 PASS. Default limit is 200. Keys total, truncated, offset, total_faces and total_edges are present. Entry "index" is assigned before filtering, so indices stay absolute. Internal callers use enumerate_faces/enumerate_edges, which are not paginated, so nothing breaks at 200. within_box is in mm and uses the same mm_point values. Feature filter uses IFeature.GetFaces and IFace2.GetEdges (both in the compat list) with COM ==; it is untestable offline, so it needs a live check.
  - Minor: limit=0 silently becomes 200 (`args.get("limit") or 200`), so the limit<1 check is dead for 0.
  - Faces are matched on a single point only.
- (c) screenshot save_as PASS. It rejects "/", "\", "..", ":" (so absolute paths and drive letters), and anything where name != Path(name).name. Output is always OUTPUT_ROOT/screenshots/<name>. It validates before touching SW.
  - Minor: Windows reserved names (CON, NUL.png) are not rejected.
  - Minor: a stale file with the same name would pass the is_file check if the SW write failed.
- (d) #21 PASS. The docs state ~\Documents\solidworks-mcp, matching sw_core.py:139-141, including the empty-variable case. The claim that clients are already configured was not verifiable here.
- (e) PASS. ForceRebuild3, ForceRebuildAll, EditRebuild3, IFeature.GetFaces and IFace2.GetEdges are all in sw2017_api_members.txt.
