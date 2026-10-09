# Phase 2.4: tlb_probe output against the SOLIDWORKS 2017 type libraries

Generated 2026-10-08 by driving upstream `tools/tlb_probe.py` (`inspect_methods` / `inspect_enums`) against `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldworks.tlb` and `swconst.tlb`. SOLIDWORKS was not running and was not attached to: `tlb_probe.candidate_roots()` calls `GetActiveObject` even when `SW_MCP_INSTALL_DIR` is set, so the driver replaces it with the install directory (equivalent CLI: `SW_MCP_INSTALL_DIR=... python tools\tlb_probe.py methods '<iface>' '<member>'`).

`parameters=N` is the argument count; `invkind` 1 = method, 2 = property get, 4 = property put. Every enum argument below is declared as a plain `long` in the typelib (VT 3), so which enum a parameter uses comes from `sldworksapi.chm`, not the tlb; see `phase2-static-compat.md` for those quotes.

## Methods

### `^IFeatureManager$` / `^FeatureRevolve2$`
_revolve: Dir1Type is a long (enum identity comes from the help text, swEndConditions_e)_

```
IFeatureManager.FeatureRevolve2(SingleDir, IsSolid, IsThin, IsCut, ReverseDir, BothDirectionUpToSameEntity, Dir1Type, Dir2Type, Dir1Angle, Dir2Angle, OffsetReverse1, OffsetReverse2, OffsetDistance1, OffsetDistance2, ThinType, ThinThickness1, ThinThickness2, Merge, UseFeatScope, UseAutoSelect)
  parameters=20 invkind=1 flags=0
```

### `^IView$` / `^(SetDisplayMode3|GetDisplayMode2|SetDisplayTangentEdges2|GetDisplayTangentEdges2|TangentEdgeDisplay)$`
_drawing display / tangent edges_

```
IView.GetDisplayTangentEdges2()
  parameters=0 invkind=1 flags=0
IView.SetDisplayTangentEdges2(DisplayIn)
  parameters=1 invkind=1 flags=0
IView.GetDisplayMode2()
  parameters=0 invkind=1 flags=0
IView.SetDisplayMode3(UseParent, Mode, Facetted, Edges)
  parameters=4 invkind=1 flags=0
```

### `^IDrawingDoc$` / `^(CreateSectionViewAt5|CreateDetailViewAt3|CreateDetailViewAt4)$`
_section / detail view_

```
IDrawingDoc.CreateDetailViewAt3(X, Y, Z, Style, Scale1, Scale2, LabelIn, Showtype, FullOutline)
  parameters=9 invkind=1 flags=0
IDrawingDoc.CreateSectionViewAt5(X, Y, Z, SectionLabel, Options, ExcludedComponents, SectionDepth)
  parameters=7 invkind=1 flags=0
IDrawingDoc.CreateDetailViewAt4(X, Y, Z, Style, Scale1, Scale2, LabelIn, Showtype, FullOutline, JaggedOutline, NoOutline, ShapeIntensity)
  parameters=12 invkind=1 flags=0
```

### `^IModelDocExtension$` / `^(DeleteSelection2|SaveAs\d*|CreateMassProperty\d*)$`
_DeleteSelection2 + confirmed-absent SaveAs2/SaveAs3/CreateMassProperty2_

```
IModelDocExtension.CreateMassProperty()
  parameters=0 invkind=1 flags=0
IModelDocExtension.DeleteSelection2(DeleteOptions)
  parameters=1 invkind=1 flags=0
IModelDocExtension.SaveAs(Name, Version, Options, ExportData, Errors, Warnings)
  parameters=6 invkind=1 flags=0
```

### `^IModelDoc2$` / `^(ViewDisplay.*|ActiveView|ShowNamedView2)$`
_set_view: ViewDisplayShadedwithedges vs the members that exist_

```
IModelDoc2.ActiveView()
  parameters=0 invkind=2 flags=0
IModelDoc2.ActiveView()
  parameters=1 invkind=4 flags=0
IModelDoc2.ViewDisplayHiddenremoved()
  parameters=0 invkind=1 flags=0
IModelDoc2.ViewDisplayWireframe()
  parameters=0 invkind=1 flags=0
IModelDoc2.ViewDisplayShaded()
  parameters=0 invkind=1 flags=0
IModelDoc2.ViewDisplayHiddengreyed()
  parameters=0 invkind=1 flags=0
IModelDoc2.ViewDisplayFaceted()
  parameters=0 invkind=1 flags=0
IModelDoc2.ViewDisplayCurvature()
  parameters=0 invkind=1 flags=0
IModelDoc2.ShowNamedView2(VName, ViewId)
  parameters=2 invkind=1 flags=0
```

### `^IModelView$` / `^DisplayMode$`
_set_view fix candidate: IModelView.DisplayMode (swViewDisplayMode_e)_

```
IModelView.DisplayMode()
  parameters=0 invkind=2 flags=0
IModelView.DisplayMode()
  parameters=1 invkind=4 flags=0
```

### `^IMeasure$` / `^Calculate$`
_measure (A fixed to pass Entities)_

```
IMeasure.Calculate(Entities)
  parameters=1 invkind=1 flags=0
```

### `^ISheet$` / `^GetSize$`
_create_drawing sheet size_

```
ISheet.GetSize(Width, Height)
  parameters=2 invkind=1 flags=0
```

### `^ISldWorks$` / `^GetUserPreferenceStringValue$`
_new_document template preference_

```
ISldWorks.GetUserPreferenceStringValue(UserPreference)
  parameters=1 invkind=1 flags=0
```

## Enums

### `^swEndConditions_e$`

```
swEndConditions_e
  swEndCondBlind = 0
  swEndCondThroughAll = 1
  swEndCondThroughNext = 2
  swEndCondUpToVertex = 3
  swEndCondUpToSurface = 4
  swEndCondOffsetFromSurface = 5
  swEndCondMidPlane = 6
  swEndCondUpToBody = 7
  swEndCondThroughAllBoth = 9
```

### `^swRevolveType_e$`

```
swRevolveType_e
  swRevolveTypeOneDirection = 0
  swRevolveTypeMidPlane = 1
  swRevolveTypeTwoDirection = 2
  swRevolveTypeOneDirection360Degrees = 3
  swRevolveTypeMidPlane360Degrees = 4
  swRevolveTypeTwoDirection360Degrees = 5
```

### `^swCreateSectionViewAtOptions_e$`

```
swCreateSectionViewAtOptions_e
  swCreateSectionView_NotAligned = 1
  swCreateSectionView_OffsetSection = 2
  swCreateSectionView_ChangeDirection = 4
  swCreateSectionView_ScaleWithModel = 8
  swCreateSectionView_Partial = 16
  swCreateSectionView_DisplaySurfaceCut = 32
  swCreateSectionView_ExcludeFasteners = 64
  swCreateSectionView_CutSurfaceBodies = 128
```

### `^swDetViewStyle_e$`

```
swDetViewStyle_e
  swDetViewSTANDARD = 0
  swDetViewBROKEN = 1
  swDetViewLEADER = 2
  swDetViewNOLEADER = 3
  swDetViewCONNECTED = 4
```

### `^swDetCircleShowType_e$`

```
swDetCircleShowType_e
  swDetCirclePROFILE = 0
  swDetCircleCIRCLE = 1
  swDetCircleDONTSHOW = 2
```

### `^swDisplayMode_e$`

```
swDisplayMode_e
  swDisplayModeUNKNOWN = -1
  swWIREFRAME = 0
  swHIDDEN_GREYED = 1
  swHIDDEN = 2
  swSHADED = 3
  swFACETED_WIREFRAME = 4
  swFACETED_HIDDEN_GREYED = 5
  swFACETED_HIDDEN = 6
  swSHADED_EDGES = 7
  swDisplayModeDEFAULT = 8
```

### `^swViewDisplayMode_e$`

```
swViewDisplayMode_e
  swViewDisplayMode_Wireframe = 1
  swViewDisplayMode_HiddenLinesRemoved = 2
  swViewDisplayMode_HiddenLinesGrayed = 3
  swViewDisplayMode_Shaded = 4
  swViewDisplayMode_ShadedWithEdges = 5
  swViewDisplayMode_ShadedCurvatureOn = 6
  swViewDisplayMode_ShadedCurvatureOFF = 7
  swViewDisplayMode_StripesOn = 8
  swViewDisplayMode_StripesOff = 9
  swViewDisplayMode_PerspectiveOn = 10
  swViewDisplayMode_PerspectiveOff = 11
  swViewDisplayMode_Faceted = 12
  swViewDisplayMode_IntegratedPreview = 13
```

### `^swDisplayTangentEdges_e$`

```
swDisplayTangentEdges_e
  swTangentEdgesHidden = 0
  swTangentEdgesVisibleAndFonted = 1
  swTangentEdgesVisible = 2
```

### `^swEdgesTangentEdgeDisplay_e$`

```
swEdgesTangentEdgeDisplay_e
  swEdgesTangentEdgeDisplayVisible = 1
  swEdgesTangentEdgeDisplayPhantom = 2
  swEdgesTangentEdgeDisplayRemoved = 3
```

### `^swDeleteSelectionOptions_e$`

```
swDeleteSelectionOptions_e
  swDelete_Children = 1
  swDelete_Absorbed = 2
  swDelete_Advanced = 4
```

### `^swUserPreferenceStringValue_e$`

```
swUserPreferenceStringValue_e
  swFileLocationsDocuments = 1
  swFileLocationsPaletteFeatures = 2
  swFileLocationsPaletteParts = 3
  swFileLocationsPaletteFormTools = 4
  swFileLocationsBlocks = 5
  swFileLocationsDocumentTemplates = 6
  swFileLocationsSheetFormat = 7
  swDefaultTemplatePart = 8
  swDefaultTemplateAssembly = 9
  swDefaultTemplateDrawing = 10
  swBackupDirectory = 11
  swFileLocationsBendTable = 12
  swMaterialPropertyCrosshatchPattern = 13
  swDrawingAreaHatchPattern = 14
  swDetailingNextDatumFeatureLabel = 15
  swFileSaveAsCoordinateSystem = 16
  swFileLocationsPaletteAssemblies = 17
  swCustomPropertyUsedAsComponentDescription = 18
  swFileLocationsLibraryFeatures = 19
  swFileLocationsMacroFeatures = 20
  swFileLocationsWebFolders = 21
  swFileLocationsBOMTemplates = 22
  swFileLocationsMacros = 23
  swFileLocationsJournalFile = 24
  swFileLocationsCustomPropertyFile = 25
  swFileLocationsHoleCalloutFormatFile = 26
  swFileLocationsDimensionFavorites = 27
  swFileLocationsMaterialDatabases = 28
  swFileLocationsWeldmentProfiles = 29
  swFileLocationsColorSwatches = 30
  swFileLocationsTextures = 31
  swFileLocationsWeldmentPropertyFile = 32
  swFileLocationsHoleTableTemplates = 33
  swFileLocationsWeldmentCutListTemplates = 34
  swFileLocationsRevisionTableTemplates = 35
  swDrawingCustomPropertyUsedAsRevision = 36
  swFileLocationsRouteComponentLibrary = 37
  swFileLocationsDesignLibrary = 38
  swFileLocationsLineStyleDefinitions = 39
  swFileLocationsDesignJournalTemplate = 40
  swFileLocationsRouteCableLibrary = 41
  swFileLocationsAppearances = 42
  swFileLocationsScenes = 43
  swFileLocationsLights = 44
  swFileLocationsBendNoteFormatFile = 45
  swSeparatorCharacterForDims = 46
  swFileLocationsRouteCoveringLibrary = 47
  swFileLocationsDesignCheckerFile = 48
  swReferenceTriadXLabel = 49
  swReferenceTriadYLabel = 50
  swReferenceTriadZLabel = 51
  swHoleWizardToolBoxFolder = 52
  swAutoSaveDirectory = 53
  swColorsBackgroundImageFile = 54
  swDetailingBOMUpperCustomProperty = 55
  swDetailingBOMLowerCustomProperty = 56
  swFileLocationsTxCalloutFormatFile = 57
  swFileLocations3DCCModelFolder = 58
  swFileLocationsHoleWizardFavoritesDB = 59
  swFileLocationsSearchPaths = 60
  swFileLocationsSheetMetalGaugeTable = 61
  swFileLocationsSpellingFolders = 62
  swDetailingLayer = 63
  swFileLocationsDraftingStandard = 64
  swDetailingDimensionStandardName = 65
  swOverriddenQuantityColumnName = 66
  swFileLocationsCustomAppearances = 67
  swFileLocationsCustomDecals = 68
  swFileLocationsCustomScenes = 69
  swFileLocationsTitleBlockTableTemplate = 70
  swFileLocationsBendCalculationTable = 71
  swFileLocationsThemeFolder = 72
  swExportIFCType = 73
  swFileLocationsFuncBldrSegTypeDefinitions = 74
  swFileLocationsSustainabilityReportTemplateFolder = 75
  swFileLocationsCostingReportTemplateFolder = 76
  swFileLocationsCostingTemplates = 77
  swFileLocationsWeldTableTemplate = 78
  swFileLocationsBendTableTemplate = 79
  swFileLocationsPunchTableTemplate = 80
  swDetailingDetailViewLabels_CustomName = 81
  swDetailingDetailViewLabels_CustomScale = 82
  swDetailingSectionViewLabels_CustomName = 83
  swDetailingSectionViewLabels_CustomScale = 84
  swDetailingAuxViewLabels_CustomName = 85
  swDetailingAuxViewLabels_CustomScale = 86
  swCenterLineLayer = 87
  swCenterMarkLayer = 88
  swSheetMetalBendNotesLayer = 89
  swSearchDissectionLocation = 91
  swFileLocationsSymbolLibraryFolder = 92
  swFileLocationsNewSheetFormat = 93
  swDetailingMiscView_CustomName = 94
  swDetailingMiscView_CustomScale = 95
  swDraftStandardExclusionList = 96
  swDetailingOrthoView_CustomName = 97
  swDetailingOrthoView_CustomScale = 98
  swElecDuctingDuctName = 99
  swElecCableTrayDuctName = 100
  swHvacRectDuctName = 101
  swHvacCirDuctName = 102
  swElecDuctingElbowName = 102
  swElecCableTrayElbowName = 103
  swHvacRectElbowName = 104
  swHvacCirElbowName = 105
  swBorderLayer = 106
  swFileLocationsThreadProfiles = 107
```

