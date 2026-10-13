r"""Print SOLIDWORKS 2017 typelib signatures for Interface.Member names (offline).

Usage:  .venv\Scripts\python.exe tools/compat/probe_signatures.py [--out report.md] Interface.Member ...
        Special items:  owner:Member          which interfaces declare Member
                        members:Interface:substr[,substr]   members of Interface containing any substring
                        enum:swEnumName       all values of an enum
Loads the registered typelibs with LoadRegTypeLib(guid, 0x19, 0) (0x19 hex = SW2017);
never connects to SOLIDWORKS.
"""
import sys
import pythoncom

LIBS = {
    "sldworks": ("{83A33D31-27C5-11CE-BFD4-00400513BB57}", 0x19, 0),
    "swconst": ("{4687F359-55D0-4CD3-B6CF-2EB42C11F989}", 0x19, 0),
}
INVOKE = {pythoncom.INVOKE_FUNC: "FUNC", pythoncom.INVOKE_PROPERTYGET: "PROPGET",
          pythoncom.INVOKE_PROPERTYPUT: "PROPPUT", pythoncom.INVOKE_PROPERTYPUTREF: "PROPPUTREF"}
VT = {getattr(pythoncom, n): n[3:] for n in dir(pythoncom) if n.startswith("VT_")}
PF = [(1, "in"), (2, "out"), (4, "lcid"), (8, "retval"), (16, "opt"), (32, "hasdefault")]


def load():
    infos = {}
    for tag, (guid, ma, mi) in LIBS.items():
        tlb = pythoncom.LoadRegTypeLib(guid, ma, mi, 0)
        for i in range(tlb.GetTypeInfoCount()):
            infos.setdefault(tlb.GetDocumentation(i)[0], []).append(tlb.GetTypeInfo(i))
    return infos


def vt_name(td, ti):
    if isinstance(td, int):
        return VT.get(td, str(td))
    if isinstance(td[0], tuple):
        td = td[0]
    vt = td[0]
    if vt in (pythoncom.VT_PTR, pythoncom.VT_SAFEARRAY):
        inner = td[1]
        prefix = "PTR->" if vt == pythoncom.VT_PTR else "SAFEARRAY of "
        return prefix + vt_name(inner, ti)
    if vt == pythoncom.VT_USERDEFINED:
        try:
            ref = ti.GetRefTypeInfo(td[1])
            return "UD:" + ref.GetDocumentation(-1)[0]
        except Exception:
            return "UD:?"
    return VT.get(vt, str(vt))


def funcs_of(ti):
    ta = ti.GetTypeAttr()
    for f in range(ta.cFuncs):
        yield ti.GetFuncDesc(f)


def describe(infos, iname, member):
    out = []
    for ti in infos.get(iname, []):
        for fd in funcs_of(ti):
            names = ti.GetNames(fd.memid)
            if names[0] != member:
                continue
            ret = vt_name(fd.rettype, ti)
            out.append(f"### {iname}.{member}  ({INVOKE.get(fd.invkind, fd.invkind)}, returns {ret}, {len(fd.args)} params)")
            out.append("| pos | name | type | flags |")
            out.append("|---|---|---|---|")
            for pos, a in enumerate(fd.args):
                flags = a[1] or 0
                fl = [n for b, n in PF if flags & b]
                pname = names[pos + 1] if pos + 1 < len(names) else "?"
                t = vt_name(a[0], ti)
                if t.startswith("PTR->") and "byref" not in fl:
                    fl.append("byref")
                out.append(f"| {pos + 1} | {pname} | {t} | {', '.join(fl) or '-'} |")
            out.append("")
    if not out:
        out.append(f"### {iname}.{member}\nNOT FOUND in typelib.\n")
    return out


def owners(infos, member):
    return sorted(n for n, tis in infos.items() for ti in tis for fd in funcs_of(ti) if ti.GetNames(fd.memid)[0] == member)


def main(argv):
    out_path = None
    if argv[:1] == ["--out"]:
        out_path, argv = argv[1], argv[2:]
    infos = load()
    lines = []
    for item in argv:
        if item.startswith("owner:"):
            m = item[6:]
            lines += [f"### owners of {m}", ", ".join(owners(infos, m)) or "NOT FOUND", ""]
        elif item.startswith("members:"):
            _, iname, subs = item.split(":", 2)
            subs = subs.split(",")
            found = sorted({ti.GetNames(fd.memid)[0] for ti in infos.get(iname, []) for fd in funcs_of(ti)
                            if any(s in ti.GetNames(fd.memid)[0] for s in subs)})
            lines += [f"### {iname} members matching {subs}", ", ".join(found) or "none", ""]
        elif item.startswith("enum:"):
            ename = item[5:]
            vals = []
            for ti in infos.get(ename, []):
                ta = ti.GetTypeAttr()
                for v in range(ta.cVars):
                    vd = ti.GetVarDesc(v)
                    vals.append((vd.value, ti.GetNames(vd.memid)[0]))
            lines += [f"### enum {ename}", ", ".join(f"{n}={v}" for v, n in sorted(vals)) or "NOT FOUND", ""]
        else:
            iname, member = item.split(".", 1)
            lines += describe(infos, iname, member)
    text = "\n".join(lines)
    if out_path:
        open(out_path, "w", encoding="utf-8").write(text)
    else:
        print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
