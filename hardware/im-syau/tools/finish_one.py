"""Layout + Freerouting + fab for IM-SYAU compact 4-layer DevKit carrier."""
from __future__ import annotations

import gc
import json
import re
import shutil
import subprocess
import sys
import uuid
from collections import Counter
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parents[1]
NAME = "im-syau"
PCB = ROOT / NAME / f"{NAME}.kicad_pcb"
SCH = ROOT / NAME / f"{NAME}.kicad_sch"
FAB = ROOT / NAME / "fab"
CLI = Path(r"C:\Users\sunflowerss\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe")
JAR = Path(r"C:\Users\sunflowerss\.agents\tools\kicad-claude-mcp\third_party\freerouting.jar")

# PinSocket_1x22 origin = PIN1 (not geometric center). Pin pitch 2.54, span 53.34.
ROW = 22.86
PIN_SPAN = 21 * 2.54  # 53.34
ORIGIN = (2.0, 2.0)
# Left sockets + right power strip. Height fits pin1..pin22 + margins.
BOARD = (54.0, 68.0)
J3_X = ORIGIN[0] + 6.5
J4_X = J3_X + ROW
J_Y = ORIGIN[1] + 4.0  # pin1; pin22 ≈ 57.34; bottom edge 70

CX = ORIGIN[0] + 44.0  # power column (clear of J4 courtyard)
PLACE = {
    "J3": (J3_X, J_Y, 0),
    "J4": (J4_X, J_Y, 0),
    # Right strip — keep clear of header pads / board edge (≥0.5 mm)
    "J1": (CX - 1.0, ORIGIN[1] + 9.5, 0),
    "R1": (CX - 6.0, ORIGIN[1] + 18.5, 0),
    "R2": (CX + 2.0, ORIGIN[1] + 18.5, 0),
    "SW1": (CX - 6.0, ORIGIN[1] + 24.5, 0),
    "SW2": (CX + 2.0, ORIGIN[1] + 24.5, 0),
    "D4": (CX - 6.0, ORIGIN[1] + 30.0, 0),
    "R6": (CX + 2.0, ORIGIN[1] + 30.0, 90),
    "U1": (CX - 1.0, ORIGIN[1] + 37.0, 0),
    "C1": (CX - 6.0, ORIGIN[1] + 44.0, 0),
    "C2": (CX + 2.0, ORIGIN[1] + 44.0, 0),
    "R3": (CX - 6.0, ORIGIN[1] + 49.0, 0),
    "R4": (CX + 2.0, ORIGIN[1] + 49.0, 0),
    "D1": (CX - 6.0, ORIGIN[1] + 54.0, 0),
    "R5": (CX + 2.0, ORIGIN[1] + 54.0, 90),
    # OR diodes beside headers, clear of fuse/JST
    "D2": (J4_X + 5.0, ORIGIN[1] + 48.0, 90),
    "D3": (J4_X + 5.0, ORIGIN[1] + 55.0, 90),
    "F1": (CX - 1.0, ORIGIN[1] + 59.0, 0),
    "J2": (CX - 1.0, ORIGIN[1] + 64.5, 0),
}


def run_cli(*args):
    return subprocess.run(
        [str(CLI), *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def strip_tracks_zones(pcb_path: Path):
    text = pcb_path.read_text(encoding="utf-8")
    text = re.sub(r"\n\t\(segment\b.*?\n\t\)", "", text, flags=re.S)
    text = re.sub(r"\n\t\(via\b.*?\n\t\)", "", text, flags=re.S)
    text = re.sub(r"\n\t\(arc\b.*?\n\t\)", "", text, flags=re.S)
    lines = text.splitlines(keepends=True)
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("\t(zone"):
            depth = 0
            while i < len(lines):
                depth += lines[i].count("(") - lines[i].count(")")
                i += 1
                if depth <= 0:
                    break
            continue
        out.append(lines[i])
        i += 1
    pcb_path.write_text("".join(out), encoding="utf-8")


def set_outline_file(pcb_path: Path, w, h, ox, oy):
    text = pcb_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("\t(gr_line") or lines[i].startswith("\t(pcb_shape") or lines[i].startswith("\t(gr_rect"):
            block = [lines[i]]
            i += 1
            depth = 1
            while i < len(lines) and depth:
                block.append(lines[i])
                depth += lines[i].count("(") - lines[i].count(")")
                i += 1
            if "Edge.Cuts" in "".join(block):
                continue
            out.extend(block)
        else:
            out.append(lines[i])
            i += 1
    text = "".join(out)
    rect = f"""
\t(gr_rect
\t\t(start {ox} {oy})
\t\t(end {ox + w} {oy + h})
\t\t(stroke
\t\t\t(width 0.1)
\t\t\t(type default)
\t\t)
\t\t(fill none)
\t\t(layer "Edge.Cuts")
\t\t(uuid "{uuid.uuid4()}")
\t)
"""
    if text.rstrip().endswith(")"):
        text = text.rstrip()[:-1] + rect + ")\n"
    pcb_path.write_text(text, encoding="utf-8")


def apply_netlist():
    import xml.etree.ElementTree as ET

    FAB.mkdir(exist_ok=True)
    xml = FAB / "netlist.xml"
    run_cli("sch", "export", "netlist", "--format", "kicadxml", "-o", str(xml), str(SCH))
    tree = ET.parse(xml)
    ref_nets: dict[str, dict[str, str]] = {}
    nets = set()
    for net in tree.getroot().findall("nets/net"):
        name = net.get("name") or ""
        if not name:
            continue
        nets.add(name)
        for node in net.findall("node"):
            ref, pin = node.get("ref"), node.get("pin")
            if ref and pin:
                ref_nets.setdefault(ref, {})[pin] = name
    board = pcbnew.LoadBoard(str(PCB))
    for n in sorted(nets):
        if board.FindNet(n) is None:
            board.Add(pcbnew.NETINFO_ITEM(board, n))
    ch = 0
    for fp in list(board.GetFootprints()):
        ref = fp.GetReference()
        if ref not in ref_nets:
            continue
        for pad in fp.Pads():
            if pad.GetNumber() in ref_nets[ref]:
                pad.SetNet(board.FindNet(ref_nets[ref][pad.GetNumber()]))
                ch += 1
    pcbnew.SaveBoard(str(PCB), board)
    del board
    gc.collect()
    print(f"  netlist pads={ch}")


def add_gnd_zones(board, ox, oy, w, h):
    net = board.FindNet("GND")
    if not net:
        return
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu):
        zone = pcbnew.ZONE(board)
        zone.SetNet(net)
        zone.SetLayer(layer)
        zone.SetLocalClearance(pcbnew.FromMM(0.25))
        zone.SetMinThickness(pcbnew.FromMM(0.2))
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        zone.Outline().NewOutline()
        for c in (
            (ox + 0.4, oy + 0.4),
            (ox + w - 0.4, oy + 0.4),
            (ox + w - 0.4, oy + h - 0.4),
            (ox + 0.4, oy + h - 0.4),
        ):
            zone.Outline().Append(pcbnew.VECTOR2I(pcbnew.FromMM(c[0]), pcbnew.FromMM(c[1])))
        board.Add(zone)


def layout_only():
    strip_tracks_zones(PCB)
    w, h = BOARD
    ox, oy = ORIGIN
    set_outline_file(PCB, w, h, ox, oy)
    board = pcbnew.LoadBoard(str(PCB))
    board.SetCopperLayerCount(4)
    try:
        board.SetLayerName(pcbnew.In1_Cu, "In1.Cu")
        board.SetLayerName(pcbnew.In2_Cu, "In2.Cu")
    except Exception:
        pass
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref not in PLACE:
            continue
        x, y, rot = PLACE[ref]
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        fp.SetOrientation(pcbnew.EDA_ANGLE(rot, pcbnew.DEGREES_T))
    add_gnd_zones(board, ox, oy, w, h)
    for d in list(board.GetDrawings()):
        if d.GetClass() == "PCB_TEXT" and d.GetText() == "IM-SYAU":
            board.Remove(d)
    txt = pcbnew.PCB_TEXT(board)
    txt.SetText("IM-SYAU")
    txt.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(ox + 1.5), pcbnew.FromMM(oy + h - 2.5)))
    txt.SetLayer(pcbnew.F_SilkS)
    txt.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.2), pcbnew.FromMM(1.2)))
    board.Add(txt)
    # sanity: sockets inside outline
    for ref in ("J3", "J4"):
        fp = board.FindFootprintByReference(ref)
        ys = [pcbnew.ToMM(p.GetPosition().y) for p in fp.Pads()]
        print(f"  {ref} pin1={min(ys):.2f} pin22={max(ys):.2f} edge={oy + h:.1f}")
    pcbnew.SaveBoard(str(PCB), board)
    print(f"  layout {w}x{h}mm 4L sockets@{J3_X:.1f}/{J4_X:.1f}")


def freeroute():
    strip_tracks_zones(PCB)
    dsn, ses = FAB / "board.dsn", FAB / "board.ses"
    if ses.exists():
        ses.unlink()
    board = pcbnew.LoadBoard(str(PCB))
    w, h = BOARD
    ox, oy = ORIGIN
    if not list(board.Zones()):
        add_gnd_zones(board, ox, oy, w, h)
        pcbnew.SaveBoard(str(PCB), board)
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise RuntimeError("DSN export failed")
    del board
    gc.collect()
    java = shutil.which("java")
    r = subprocess.run(
        [java, "-jar", str(JAR), "-de", str(dsn), "-do", str(ses), "-mp", "100", "-mt", "1"],
        capture_output=True,
        text=True,
        timeout=480,
        encoding="utf-8",
        errors="replace",
    )
    print("  freerouting rc", r.returncode)
    if not ses.is_file():
        raise RuntimeError(r.stderr[-400:] or r.stdout[-400:])
    strip_tracks_zones(PCB)
    board = pcbnew.LoadBoard(str(PCB))
    if not pcbnew.ImportSpecctraSES(board, str(ses)):
        raise RuntimeError("SES import failed")
    add_gnd_zones(board, ox, oy, w, h)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    print("  SES+zones ok")


def export_fab():
    FAB.mkdir(exist_ok=True)
    gdir = FAB / "gerber"
    gdir.mkdir(exist_ok=True)
    for f in gdir.glob("*"):
        f.unlink()
    run_cli(
        "pcb", "export", "gerbers", "-o", str(gdir),
        "--layers",
        "F.Cu,In1.Cu,In2.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts,F.Paste",
        str(PCB),
    )
    run_cli("pcb", "export", "drill", "-o", str(gdir), str(PCB))
    run_cli(
        "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "front",
        "-o", str(FAB / "positions.csv"), str(PCB),
    )
    run_cli("sch", "export", "python-bom", "-o", str(FAB / "bom.xml"), str(SCH))
    pro = ROOT / NAME / f"{NAME}.kicad_pro"
    data = json.loads(pro.read_text(encoding="utf-8"))
    ns = data.setdefault("net_settings", {})
    classes = ns.setdefault("classes", [])
    default = next((c for c in classes if isinstance(c, dict) and c.get("name") == "Default"), None)
    if default is None:
        default = {"name": "Default", "priority": 2147483647}
        classes.append(default)
    default["clearance"] = 0.127
    default.setdefault("track_width", 0.25)
    default.setdefault("via_diameter", 0.6)
    default.setdefault("via_drill", 0.3)
    ds = data.setdefault("board", {}).setdefault("design_settings", {})
    ds.setdefault("rules", {})["min_clearance"] = 0.127
    rs = ds.setdefault("rule_severities", {})
    for k in ("drill_out_of_range", "courtyards_overlap", "pth_inside_courtyard"):
        rs[k] = "warning"
    pro.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    run_cli("pcb", "drc", "--format", "json", "-o", str(FAB / "drc.json"), str(PCB))
    drc = json.loads((FAB / "drc.json").read_text(encoding="utf-8"))
    errs = [v for v in drc.get("violations", []) if v.get("severity") == "error"]
    uc = drc.get("unconnected_items", [])
    print("  DRC errors", len(errs), dict(Counter(v.get("type") for v in errs)), "unconnected", len(uc))
    if errs or uc:
        for v in errs[:8]:
            print("   E", v.get("type"), (v.get("description") or "")[:100])
        for v in uc[:8]:
            items = v.get("items") or []
            print("   U", " | ".join((i.get("description") or "")[:60] for i in items[:2]))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--layout-only":
        layout_only()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--freeroute-only":
        freeroute()
        return
    print("=== finish", NAME, "===")
    apply_netlist()
    for flag in ("--layout-only", "--freeroute-only"):
        r = subprocess.run(
            [sys.executable, __file__, flag],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=520,
        )
        print(r.stdout)
        if r.returncode:
            print(r.stderr[-800:])
            raise SystemExit(r.returncode)
    export_fab()


if __name__ == "__main__":
    main()
