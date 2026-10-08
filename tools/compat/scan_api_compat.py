"""Scan repos for SolidWorks API member calls that are absent from the SW2017 type library."""
import io, sys as _sys
_sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")
import re, sys, collections, pathlib
members_file, repos_dir = sys.argv[1], pathlib.Path(sys.argv[2])
by_iface = collections.defaultdict(set); bare = set()
for line in open(members_file):
    iface, _, m = line.strip().partition(".")
    by_iface[iface].add(m); bare.add(m)
ACCESSOR = {"Extension": "IModelDocExtension", "FeatureManager": "IFeatureManager",
            "SketchManager": "ISketchManager", "SelectionManager": "ISelectionMgr",
            "ConfigurationManager": "IConfigurationManager"}
NOISE = set("""Dispatch DispatchEx EnsureDispatch GetActiveObject CoInitialize CoInitializeEx CoUninitialize
VARIANT Missing GetObject ToString Add Count Length Parse Invoke Marshal Equals GetType Run Main Get Set Close Value
Name Path Text Keys Values Items TryParse Format Join Split Trim Exists Combine Sleep Start Stop Wait Result Contains
Remove Clear Insert Dispose Write WriteLine ReadLine Read Error Warning Info Debug Field BaseModel Config Enum Optional List Dict Any Literal Union
Tool FastMCP Server Context Path Exception ValueError Version ReleaseComObject GetTypeFromProgID CreateInstance InvokeMember
""".split())
SRC = {".py", ".ts", ".js", ".cs"}
pat = re.compile(r"(?:\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*)?\.?\b([A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*)\s*\(")
pat = re.compile(r"(?:([A-Za-z_][A-Za-z0-9_]*)\.)([A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*\d?)\b")
gate = re.compile(r"(SldWorks\.Application\.\d+|RevisionNumber|swVersion|sw_version|MIN_SW|SUPPORTED_VERSION|version_year|\b20(1[0-9]|2[0-9])\b.*(sw|solid)|(sw|solid).*\b20(1[0-9]|2[0-9])\b)", re.I)
for repo in sorted(p for p in repos_dir.iterdir() if p.is_dir()):
    hits = collections.Counter(); newer = collections.Counter(); where = {}; gates = []
    for f in repo.rglob("*"):
        if f.suffix not in SRC or "node_modules" in f.parts or "test" in f.name.lower(): continue
        try: txt = f.read_text(encoding="utf-8", errors="ignore")
        except Exception: continue
        for ln, line in enumerate(txt.splitlines(), 1):
            if gate.search(line) and len(gates) < 12:
                gates.append(f"{f.relative_to(repo)}:{ln}: {line.strip()[:140]}")
            for recv, m in pat.findall(line):
                if m in NOISE: continue
                iface = ACCESSOR.get(recv)
                if iface:
                    if m in by_iface[iface]: continue
                elif m in bare: continue
                base = re.sub(r"\d+$", "", m)
                key = f"{recv}.{m}" if iface else m
                if (base != m and (base in bare or any(re.sub(r'\d+$','',x)==base for x in (by_iface[iface] if iface else ())))) or iface:
                    newer[key] += 1
                else:
                    hits[key] += 1
                where.setdefault(key, f"{f.relative_to(repo)}:{ln}")
    print(f"\n=== {repo.name} ===")
    print("  NEWER-THAN-2017 numbered variants / accessor misses:", ", ".join(f"{k}x{v} ({where[k]})" for k, v in newer.most_common(25)) or "none")
    print("  other names not in 2017 TLB (likely non-SW noise, top 25):", ", ".join(f"{k}x{v}" for k, v in hits.most_common(25)))
    print("  version-gate-ish lines:"); [print("    ", g) for g in gates]
