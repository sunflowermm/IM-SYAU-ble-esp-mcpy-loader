"""IM-SYAU carrier: charge + power cuts + socket for ESP32-S3-DevKitC (N16R8)."""
from __future__ import annotations

import copy
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(r"C:\Users\sunflowerss\.agents\tools\kicad-claude-mcp\src")
sys.path.insert(0, str(SRC))

os.environ.setdefault(
    "KICAD10_SYMBOL_DIR",
    r"C:\Users\sunflowerss\AppData\Local\Programs\KiCad\10.0\share\kicad\symbols",
)
os.environ.setdefault(
    "KICAD10_FOOTPRINT_DIR",
    r"C:\Users\sunflowerss\AppData\Local\Programs\KiCad\10.0\share\kicad\footprints",
)

from kicad_claude import state  # noqa: E402
from kicad_claude.adapters import pcb_editor as ped  # noqa: E402
from kicad_claude.adapters import sch_editor as ed  # noqa: E402
from kicad_claude.adapters import sch_io  # noqa: E402
from kicad_claude.adapters.sch_io import find_child, is_call, sym  # noqa: E402
from kicad_claude.templates.blank import write_blank_project  # noqa: E402
from kicad_claude.tools import library as lib_tools  # noqa: E402
from kicad_claude.tools import pcb as pcb_tools  # noqa: E402
from kicad_claude.tools import schematic as sch_tools  # noqa: E402
from kicad_claude.utils.geometry import mcp_to_kicad_xy, round_mm  # noqa: E402

NAME = "im-syau"
# DevKitC-1 style: 1x22 each side, 22.86 mm row pitch (verify on your board)
SOCK = "Connector_PinSocket_2.54mm:PinSocket_1x22_P2.54mm_Vertical"


def ensure_index():
    lib_tools._ensure_index()


def new_project():
    d = ROOT / NAME
    d.mkdir(parents=True, exist_ok=True)
    for p in d.glob(f"{NAME}.kicad_*"):
        p.unlink()
    write_blank_project(d, NAME)
    state.set_active(d, NAME)
    return d


def resolve(lib_id: str):
    return sch_tools._resolve_lib_symbol(lib_id)


def fetch_symbol_def_resolved(lib_path: Path, sym_name: str) -> list:
    node = ed.fetch_symbol_def(lib_path, sym_name)
    ext = find_child(node, "extends")
    if not ext or len(ext) < 2:
        return node
    parent_name = ext[1]
    parent = fetch_symbol_def_resolved(lib_path, parent_name)
    merged = copy.deepcopy(parent)
    merged[1] = sym_name
    for c in merged[2:]:
        if is_call(c, "symbol") and isinstance(c[1], str) and c[1].startswith(parent_name):
            c[1] = sym_name + c[1][len(parent_name) :]
    child_props = {
        c[1]: c
        for c in node[2:]
        if is_call(c, "property") and len(c) >= 3 and isinstance(c[1], str)
    }
    for i, c in enumerate(list(merged[2:]), start=2):
        if is_call(c, "property") and len(c) >= 3 and c[1] in child_props:
            merged[i] = copy.deepcopy(child_props[c[1]])
            del child_props[c[1]]
    for prop in child_props.values():
        merged.append(copy.deepcopy(prop))
    return merged


def add_sym(lib_id, ref, value, x, y, rot=0, footprint=""):
    tree, path = sch_tools._load_active_schematic()
    lib_path, sym_name, meta = resolve(lib_id)
    sym_def = fetch_symbol_def_resolved(lib_path, sym_name)
    fp = footprint or meta.get("default_footprint", "")
    proj = state.get_active()
    ed.add_symbol(
        tree,
        qualified_lib_id=lib_id,
        reference=ref,
        value=value,
        x_mm=x,
        y_mm=y,
        rotation=rot,
        sym_def_node=sym_def,
        project_name=proj.name,
        instance_path=sch_tools._instance_path(),
        footprint=fp,
        datasheet=meta.get("datasheet", "~"),
        description=meta.get("description", ""),
    )
    sch_io.write_file(path, tree)


def set_fp(ref: str, footprint: str):
    tree, path = sch_tools._load_active_schematic()
    for node in ed.iter_instance_symbols(tree):
        if ed.get_symbol_property(node, "Reference") == ref:
            ed.set_symbol_property(node, "Footprint", footprint)
            sch_io.write_file(path, tree)
            return
    raise KeyError(ref)


def label(net, x, y, orientation="right"):
    tree, path = sch_tools._load_active_schematic()
    page_h = ed.page_height_mm(tree)
    xk, yk = mcp_to_kicad_xy(x, y, page_h)
    angle = {"right": 0, "up": 90, "left": 180, "down": 270}[orientation]
    tree.append(
        [
            sym("global_label"),
            net,
            [sym("shape"), sym("input")],
            [sym("at"), round_mm(xk), round_mm(yk), angle],
            [
                sym("effects"),
                [sym("font"), [sym("size"), 1.27, 1.27]],
                [sym("justify"), sym("left"), sym("bottom")],
            ],
            [sym("uuid"), str(uuid.uuid4())],
        ]
    )
    sch_io.write_file(path, tree)


def pinpos(ref, pin):
    tree, _ = sch_tools._load_active_schematic()
    return ed.get_pin_position(tree, ref, str(pin))


def connect_label(ref, pin, net, orientation="right"):
    x, y = pinpos(ref, pin)
    label(net, x, y, orientation)


def nc(ref, pin):
    tree, path = sch_tools._load_active_schematic()
    x, y = ed.get_pin_position(tree, ref, str(pin))
    ed.add_no_connect(tree, x, y)
    sch_io.write_file(path, tree)


def add_pwr_flag(net: str, x: float, y: float):
    tree, path = sch_tools._load_active_schematic()
    n = sum(
        1
        for node in ed.iter_instance_symbols(tree)
        if (ed.get_symbol_property(node, "Value") or "") == "PWR_FLAG"
    )
    ref = f"#FLG{n + 1:02d}"
    sch_io.write_file(path, tree)
    add_sym("power:PWR_FLAG", ref, "PWR_FLAG", x, y)
    connect_label(ref, "1", net)


def board_outline(w, h, ox=2, oy=2):
    tree, path = pcb_tools._load_active_pcb()
    ped.set_board_outline(tree, w, h, shape="rect", origin_x_mcp=ox, origin_y_mcp=oy)
    sch_io.write_file(path, tree)


def place_pcb(spacing=10):
    proj = state.get_active()
    sch_tree = sch_io.parse_file(proj.sch_path)
    refs = []
    for node in ed.iter_instance_symbols(sch_tree):
        ref = ed.get_symbol_property(node, "Reference")
        fp = ed.get_symbol_property(node, "Footprint") or ""
        val = ed.get_symbol_property(node, "Value") or ""
        if not ref or ref.startswith("#") or not fp:
            continue
        refs.append((ref, fp, val))
    pcb_tree, pcb_path = pcb_tools._load_active_pcb()
    x0, y0, col, row = 8.0, 30.0, 0, 0
    for ref, fp, val in refs:
        try:
            mod_path = pcb_tools._resolve_footprint(fp)
            fp_def = ped.fetch_footprint_def(mod_path)
            ped.add_footprint(
                pcb_tree,
                qualified_lib_id=fp,
                reference=ref,
                value=val,
                x_mm=x0 + (col % 4) * spacing,
                y_mm=y0 - row * spacing,
                rotation=0,
                layer="F.Cu",
                fp_def_node=fp_def,
            )
        except Exception as e:
            print(f"  skip {ref}: {e}")
        col += 1
        if col % 4 == 0:
            row += 1
    sch_io.write_file(pcb_path, pcb_tree)


def build():
    print("=== carrier", NAME, "(compact DevKit socket, 4L) ===")
    new_project()
    R = "Resistor_SMD:R_0805_2012Metric"
    C = "Capacitor_SMD:C_0805_2012Metric"
    LED = "LED_SMD:LED_0805_2012Metric"
    SW_SLIDE = "Button_Switch_SMD:SW_DIP_SPSTx01_Slide_6.7x4.1mm_W8.61mm_P2.54mm_LowProfile"

    # Charge USB-C → TP4056 → BAT; Schottky OR → SW1 → VSYS → SW2 → DEV_5V
    # DevKit has its own 3V3 LDO — no AMS1117 on carrier.
    add_sym(
        "Connector:USB_C_Receptacle_USB2.0_16P",
        "J1",
        "USB_C_CHG",
        30,
        150,
        footprint="Connector_USB:USB_C_Receptacle_GCT_USB4085",
    )
    add_sym("Device:R", "R1", "5.1k", 50, 160, 0, R)
    add_sym("Device:R", "R2", "5.1k", 50, 140, 0, R)
    add_sym("Battery_Management:TP4056-42-ESOP8", "U1", "TP4056", 85, 150)
    set_fp("U1", "Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.3mm_ThermalVias")
    add_sym("Device:R", "R3", "2k", 85, 125, 0, R)
    add_sym("Device:R", "R4", "10k", 85, 175, 0, R)
    add_sym("Device:C", "C1", "10uF", 70, 170, 0, C)
    add_sym("Device:C", "C2", "10uF", 100, 170, 0, C)
    add_sym("Device:LED", "D1", "CHG", 110, 160, 0, LED)
    add_sym("Device:R", "R5", "1k", 125, 160, 90, R)
    add_sym("Device:Polyfuse", "F1", "1A", 85, 100, 90, "Fuse:Fuse_1206_3216Metric")
    add_sym(
        "Connector_Generic:Conn_01x02",
        "J2",
        "BAT",
        55,
        100,
        footprint="Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
    )
    add_sym("Device:D_Schottky", "D2", "SS34", 130, 150, 0, "Diode_SMD:D_SMA")
    add_sym("Device:D_Schottky", "D3", "SS34", 130, 120, 0, "Diode_SMD:D_SMA")
    add_sym("Switch:SW_SPST", "SW1", "PWR_CUT", 155, 140, 0, SW_SLIDE)
    add_sym("Device:LED", "D4", "PWR", 175, 125, 0, LED)
    add_sym("Device:R", "R6", "1k", 190, 125, 90, R)
    add_sym("Switch:SW_SPST", "SW2", "ESP_CUT", 200, 140, 0, SW_SLIDE)

    add_sym(
        "Connector_Generic:Conn_01x22",
        "J3",
        "DK_LEFT",
        100,
        60,
        footprint=SOCK,
    )
    add_sym(
        "Connector_Generic:Conn_01x22",
        "J4",
        "DK_RIGHT",
        160,
        60,
        footprint=SOCK,
    )

    connect_label("J1", "A5", "CC1")
    connect_label("R1", "1", "CC1")
    connect_label("R1", "2", "GND")
    connect_label("J1", "B5", "CC2")
    connect_label("R2", "1", "CC2")
    connect_label("R2", "2", "GND")
    for p in ("A1", "A12", "B1", "B12", "S1", "SH"):
        try:
            connect_label("J1", p, "GND")
        except Exception:
            pass
    for p in ("A4", "A9", "B4", "B9"):
        try:
            connect_label("J1", p, "VUSB")
        except Exception:
            pass
    for p in ("A6", "A7", "A8", "B6", "B7", "B8", "A2", "A3", "B2", "B3"):
        try:
            nc("J1", p)
        except Exception:
            pass
    try:
        nc("U1", "6")  # STDBY unused
    except Exception:
        pass

    connect_label("U1", "4", "VUSB")
    connect_label("U1", "3", "GND")
    connect_label("U1", "5", "VBAT")
    connect_label("U1", "2", "PROG")
    connect_label("R3", "1", "PROG")
    connect_label("R3", "2", "GND")
    connect_label("U1", "1", "TEMP")
    connect_label("R4", "1", "TEMP")
    connect_label("R4", "2", "GND")
    connect_label("U1", "8", "VUSB")
    connect_label("U1", "7", "CHRG")
    connect_label("U1", "6", "STDBY")
    try:
        connect_label("U1", "9", "GND")
    except Exception:
        pass
    # TP4056 CHRG is open-drain active-low: LED A→R→VUSB, K→CHRG
    # KiCad Device:LED pin1=K pin2=A
    connect_label("D1", "1", "CHRG")
    connect_label("D1", "2", "NetD1K")
    connect_label("R5", "1", "NetD1K")
    connect_label("R5", "2", "VUSB")
    connect_label("C1", "1", "VUSB")
    connect_label("C1", "2", "GND")
    connect_label("C2", "1", "VBAT")
    connect_label("C2", "2", "GND")
    connect_label("J2", "1", "VBAT_RAW")
    connect_label("J2", "2", "GND")
    connect_label("F1", "1", "VBAT_RAW")
    connect_label("F1", "2", "VBAT")
    connect_label("D2", "2", "VUSB")
    connect_label("D2", "1", "VSYS_PRE")
    connect_label("D3", "2", "VBAT")
    connect_label("D3", "1", "VSYS_PRE")
    connect_label("SW1", "1", "VSYS_PRE")
    connect_label("SW1", "2", "VSYS")
    connect_label("D4", "2", "VSYS")
    connect_label("D4", "1", "NetD4K")
    connect_label("R6", "1", "NetD4K")
    connect_label("R6", "2", "GND")
    connect_label("SW2", "1", "VSYS")
    connect_label("SW2", "2", "DEV_5V")

    # DevKitC-1: USB 端=pin21/22；正面 USB 朝下时左侧 J1 为 5V（本板 J3）
    connect_label("J3", "21", "DEV_5V")
    connect_label("J3", "22", "GND")
    connect_label("J4", "21", "GND")
    connect_label("J4", "22", "GND")
    for i in range(1, 21):
        nc("J3", str(i))
        nc("J4", str(i))

    add_pwr_flag("VUSB", 40, 180)
    add_pwr_flag("VSYS", 160, 175)
    add_pwr_flag("DEV_5V", 220, 160)
    add_pwr_flag("GND", 40, 40)

    # Placeholder; finish_one.py sets final ~50×64 mm + 4L layout
    board_outline(50, 64)
    place_pcb(10)
    print("done — compact carrier for DevKit N16R8")


if __name__ == "__main__":
    ensure_index()
    build()
