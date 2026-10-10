# Phase 5 tools (offline)
Added: list_open_documents, close_document (sw_file.py); delete_mate (sw_assembly.py).
Skipped: edit_mate_value. set_dimension already calls doc.Parameter(name).SetSystemValue3, which in principle
accepts mate dimension names such as "D1@Distance1", but that is unverified live; list_dimensions walks only
top-level features so mate dimensions are not listed, and list_mates does not expose dimension names. Needs a live probe.
Members used (all in sw2017_api_members.txt): ISldWorks.GetDocuments, CloseDoc; IModelDoc2.GetTitle/GetPathName/GetSaveFlag/GetType/Save3;
IFeature.GetSpecificFeature2 (existing), Select2, GetFirstSubFeature/GetNextSubFeature; IModelDocExtension.DeleteSelection2.
Tests: tests/test_sw2017_phase5_tools.py (12 tests). Full suite 114 OK. Smoke client: 95 tools (was 92).
