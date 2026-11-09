"""Domain models for S21 calculations and grouped UI metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields as dataclass_fields, replace

from smcapp.domain.circuit import (
    CORNERS,
    DEFAULT_CORNER_LEFT,
    DEFAULT_CORNER_RIGHT,
    DEFAULT_MEX01,
    DEFAULT_MEX02,
    DEFAULT_MEX03,
    ElementSlot,
    LineSection,
    Section,
    TransformerSection,
    element_by_prefix,
    element_slots,
    validate_sections,
    with_element,
)
from smcapp.domain.transformers import transformer_dl_max_um


@dataclass(frozen=True)
class ConfigFieldInfo:
    """Rich metadata for a numeric configuration field."""

    name: str
    label: str
    group: str
    description: str
    suffix: str = ""
    minimum: float = 0.0
    maximum: float = 10000.0
    step: float = 0.1
    decimals: int = 3
    visible: bool = True
    element_id: str | None = None
    number: int | None = None


def _transformer_width_description(slot: ElementSlot, label: str) -> str:
    side = "слева (от ФФО)" if label == "W1" else "справа (к SIS)"
    contact = {"corner_left": "W2", "corner_right": "W1"}.get(slot.prefix)
    if contact is None:
        return f"Элемент {slot.number}: ширина {side}, до поправки dW."
    face = (
        "ширина ступни на шлейфе DC block (по центру шлейфа); при W ≠ Wms виден выступ с обеих сторон"
        if label == contact
        else "торец к соседней линии, высота горизонтальной части"
    )
    return f"Элемент {slot.number} (угловой): ширина {side} — {face}, до поправки dW."


# UI field names of the list elements: ``<prefix>_<attribute>``.
TRANSFORMER_UI_FIELDS = ("w1_m", "w2_m", "length_m")
LINE_UI_FIELDS = ("width_m", "length_m")
ELEMENT_FIELD_SCALE = 1e6
FIXED_GROUPS = ("General", "Backend Grid", "EL1 Material", "EL2 Material", "Dielectrics", "Block 1 / Block 2")


def split_element_field(
    name: str, attributes: tuple[str, ...] = ("w1_m", "w2_m", "width_m", "length_m")
) -> tuple[str, str] | None:
    """``("mex03_2", "width_m")`` for an element field name, else ``None``."""
    for attribute in attributes:
        suffix = "_" + attribute
        if name.endswith(suffix):
            prefix = name[: -len(suffix)]
            if prefix in CORNERS or re.fullmatch(r"mex0[123]_[1-9][0-9]*", prefix):
                return prefix, attribute
    return None


# GitHub #10: decimals shown in each editor. Stored SI values are not rounded;
# an untouched editor keeps the exact loaded value (see the main window).
_DISPLAY_DECIMALS = {
    "dw_m": 2,
    "z_ffo_ohm": 2,
    "temperature_k": 1,
    "tc_top_k": 1,
    "tc_bot_k": 1,
    "alpha_top": 2,
    "alpha_bot": 2,
    "sigma0_top": 3,
    "sigma0_bot": 3,
    "h_sub_m": 0,
    "sis_area_um2": 2,
    "sis_rn_area_ohm_um2": 1,
    "sis_cap_f_per_um2": 3,
    "zrad0_ohm": 0,
    "radial_angle_deg": 0,
}


def _display_decimals(info: ConfigFieldInfo) -> int:
    if info.name in _DISPLAY_DECIMALS:
        return _DISPLAY_DECIMALS[info.name]
    if info.suffix == " GHz":
        return 0  # every frequency: 1 GHz
    if info.suffix == " um":
        return 1  # every lateral size: 0.1 µm
    return info.decimals


@dataclass(frozen=True)
class S21Config:
    """Configuration for the S21 calculation example.

    All lengths are in meters unless the field name ends with ``_um``.
    Frequencies are in GHz and temperatures are in Kelvin.

    The class also stores presentation metadata so the desktop UI can render
    the parameters in grouped sections with tooltips instead of a flat list.
    """

    temperature_k: float = field(
        default=4.2,
        metadata={
            "label": "T env",
            "group": "General",
            "description": "Ambient or operating temperature used for both electrodes in the Mattis-Bardeen conductivity model.",
            "suffix": " K",
            "minimum": 0.1,
            "maximum": 300.0,
            "step": 0.1,
            "decimals": 2,
        },
    )
    tc_top_k: float = field(
        default=9.5,
        metadata={
            "label": "Tc EL1",
            "group": "EL1 Material",
            "description": "Critical temperature Tc of electrode EL1.",
            "suffix": " K",
            "minimum": 0.1,
            "maximum": 30.0,
            "step": 0.1,
            "decimals": 3,
        },
    )
    tc_bot_k: float = field(
        default=9.5,
        metadata={
            "label": "Tc EL2",
            "group": "EL2 Material",
            "description": "Critical temperature Tc of electrode EL2.",
            "suffix": " K",
            "minimum": 0.1,
            "maximum": 30.0,
            "step": 0.1,
            "decimals": 3,
        },
    )
    alpha_top: float = field(
        default=3.54,
        metadata={
            "label": "α EL1",
            "group": "EL1 Material",
            "description": "Strong-coupling coefficient alpha_1 from the relation 2*Delta = alpha*kB*Tc for electrode EL1.",
            "suffix": "",
            "minimum": 0.1,
            "maximum": 10.0,
            "step": 0.01,
            "decimals": 3,
        },
    )
    alpha_bot: float = field(
        default=3.54,
        metadata={
            "label": "α EL2",
            "group": "EL2 Material",
            "description": "Strong-coupling coefficient alpha_2 from the relation 2*Delta = alpha*kB*Tc for electrode EL2.",
            "suffix": "",
            "minimum": 0.1,
            "maximum": 10.0,
            "step": 0.01,
            "decimals": 3,
        },
    )
    delta0_top_ev: float | None = field(
        default=1.45e-3,
        metadata={
            "label": "Δ₀ EL1",
            "group": "EL1 Material",
            "description": "Explicit superconducting gap at 0 K for EL1. Kept for compatibility with the legacy backend; hidden in the UI.",
            "suffix": " eV",
            "minimum": 0.0,
            "maximum": 0.01,
            "step": 0.0001,
            "decimals": 6,
            "visible": False,
        },
    )
    delta0_bot_ev: float | None = field(
        default=1.45e-3,
        metadata={
            "label": "Δ₀ EL2",
            "group": "EL2 Material",
            "description": "Explicit superconducting gap at 0 K for EL2. Kept for compatibility with the legacy backend; hidden in the UI.",
            "suffix": " eV",
            "minimum": 0.0,
            "maximum": 0.01,
            "step": 0.0001,
            "decimals": 6,
            "visible": False,
        },
    )
    sigma0_top: float = field(
        default=18.0e6,
        metadata={
            "label": "σ EL1",
            "group": "EL1 Material",
            "description": "Normal-state conductivity sigma_1 of electrode EL1.",
            "suffix": " 1/(Ohm*m)",
            "minimum": 0.000001,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 6,
            "scale": 1e-6,
        },
    )
    sigma0_bot: float = field(
        default=18.0e6,
        metadata={
            "label": "σ EL2",
            "group": "EL2 Material",
            "description": "Normal-state conductivity sigma_2 of electrode EL2.",
            "suffix": " 1/(Ohm*m)",
            "minimum": 0.000001,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 6,
            "scale": 1e-6,
        },
    )

    d_top_m: float = field(
        default=0.35e-6,
        metadata={
            "label": "d EL1",
            "group": "EL1 Material",
            "description": "Thickness of the top superconducting electrode film.",
            "suffix": " nm",
            "minimum": 1.0,
            "maximum": 100000.0,
            "step": 10.0,
            "decimals": 0,
            "scale": 1e9,
        },
    )
    d_bot_m: float = field(
        default=0.20e-6,
        metadata={
            "label": "d EL2",
            "group": "EL2 Material",
            "description": "Thickness of the bottom superconducting electrode film.",
            "suffix": " nm",
            "minimum": 1.0,
            "maximum": 100000.0,
            "step": 10.0,
            "decimals": 0,
            "scale": 1e9,
        },
    )

    h12_m: float = field(
        default=0.465729e-6,
        metadata={
            "label": "h12",
            "group": "Dielectrics",
            "description": "Thickness of the inter-electrode dielectric between EL1 and EL2.",
            "suffix": " nm",
            "minimum": 1.0,
            "maximum": 100000.0,
            "step": 10.0,
            "decimals": 0,
            "scale": 1e9,
        },
    )
    e12: float = field(
        default=4.28265,
        metadata={
            "label": "ε₁₂",
            "group": "Dielectrics",
            "description": "Relative permittivity of the inter-electrode dielectric.",
            "suffix": "",
            "minimum": 1.0,
            "maximum": 50.0,
            "step": 0.01,
            "decimals": 5,
        },
    )
    h1_m: float = field(
        default=1.65729e-7,
        metadata={
            "label": "h1",
            "group": "Dielectrics",
            "description": "Thickness of the dielectric used in the wide 50 Ohm SIS-side section.",
            "suffix": " nm",
            "minimum": 1.0,
            "maximum": 100000.0,
            "step": 10.0,
            "decimals": 0,
            "scale": 1e9,
        },
    )
    e1: float = field(
        default=4.44084,
        metadata={
            "label": "ε₁",
            "group": "Dielectrics",
            "description": "Relative permittivity of the dielectric in the SIS-side matching section.",
            "suffix": "",
            "minimum": 1.0,
            "maximum": 50.0,
            "step": 0.01,
            "decimals": 5,
        },
    )
    e_sub: float = field(
        default=11.7,
        metadata={
            "label": "ε sub",
            "group": "General",
            "description": "Relative permittivity of the substrate used for the slot/DC-block model.",
            "suffix": "",
            "minimum": 1.0,
            "maximum": 50.0,
            "step": 0.1,
            "decimals": 3,
        },
    )
    h_sub_m: float = field(
        default=0.35e-3,
        metadata={
            "label": "h sub",
            "group": "General",
            "description": "Substrate thickness for the slot/DC-block model.",
            "suffix": " um",
            "minimum": 0.01,
            "maximum": 5000.0,
            "step": 1.0,
            "decimals": 1,
            "scale": 1e6,
        },
    )

    block_left_taper_um: float = field(
        default=12.0,
        metadata={
            "label": "Block taper L",
            "group": "Block 1 / Block 2",
            "description": "Left taper length of the octagonal block shape used for Block1 and Block2 preview.",
            "visible": False,
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.5,
            "decimals": 2,
        },
    )
    block_center_length_um: float = field(
        default=30.0,
        metadata={
            "label": "Block body",
            "group": "Block 1 / Block 2",
            "description": "Straight body length of Block1/Block2.",
            "visible": False,
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 2000.0,
            "step": 0.5,
            "decimals": 2,
        },
    )
    block_right_taper_um: float = field(
        default=14.0,
        metadata={
            "label": "Block taper R",
            "group": "Block 1 / Block 2",
            "description": "Right taper length of the octagonal block shape used for Block1 and Block2 preview.",
            "visible": False,
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.5,
            "decimals": 2,
        },
    )
    block_body_height_um: float = field(
        default=60.0,
        metadata={
            "label": "Block height",
            "group": "Block 1 / Block 2",
            "description": "Full block height shown on the sketch for Block1 and Block2.",
            "visible": False,
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 2000.0,
            "step": 0.5,
            "decimals": 2,
        },
    )
    block_neck_height_um: float = field(
        default=20.0,
        metadata={
            "label": "Neck height",
            "group": "Block 1 / Block 2",
            "description": "Narrow neck height at the microstrip connection of the block.",
            "visible": False,
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.5,
            "decimals": 2,
        },
    )
    block_arm_length_um: float = field(
        default=53.0,
        metadata={
            "label": "Arm length",
            "group": "Block 1 / Block 2",
            "description": "Length of the outgoing arm from Block1/Block2 toward the next element.",
            "visible": False,
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 2000.0,
            "step": 0.5,
            "decimals": 2,
        },
    )

    dw_m: float = field(
        default=0.5e-6,
        metadata={
            "label": "dW",
            "group": "General",
            "description": "Common fabrication width correction added to microstrip widths and subtracted from slot width.",
            "suffix": " um",
            "minimum": 0.0,
            "maximum": 100.0,
            "step": 0.05,
            "decimals": 3,
            "scale": 1e6,
        },
    )

    w_slot_m: float = field(
        default=4.0e-6,
        metadata={
            "label": "Wslot",
            "group": "DC block",
            "description": "Толщина чёрной Π-образной щели в нижнем электроде (горизонтальный участок и плечи). На рисунке и в расчёте применяется Wslot − dW. Зазор между шлейфами задаётся отдельно.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    l_slot_m: float = field(
        default=36.0e-6,
        metadata={
            "label": "Lslot",
            "group": "DC block",
            "description": "Длина вертикального плеча Π-образной щели от верхней кромки щели до конца плеча (L_slot в HFSS). Должна быть больше Lso — нижнего предела интеграла в расчёте.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 10000.0,
            "step": 0.5,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    lso_m: float = field(
        default=8.0e-6,
        metadata={
            "label": "Lso",
            "group": "DC block",
            "description": "Расстояние от внутренней кромки плеча щели до внешней кромки шлейфа. Входит в Pibase = 2·Wms + 2·Lso + зазор — расстояние между внутренними кромками плеч.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    w_ms_m: float = field(
        default=9.0e-6,
        metadata={
            "label": "Wms",
            "group": "DC block",
            "description": "Ширина вертикального открытого МПЛ-шлейфа (ноги электрода) до поправки dW.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    l_ms_m: float = field(
        default=14.0e-6,
        metadata={
            "label": "Lms",
            "group": "DC block",
            "description": "Длина вертикального открытого МПЛ-шлейфа от ступни углового трансформатора {corner_left}/{corner_right} до открытого конца.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 10000.0,
            "step": 0.5,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    dc_gap_m: float = field(
        default=4.0e-6,
        metadata={
            "label": "Зазор",
            "group": "DC block",
            "description": "Расстояние между двумя шлейфами DC block (металл к металлу, без поправки dW). Это слагаемое 4 µm в Pibase = 2·Wms + 2·Lso + зазор.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.5,
            "decimals": 3,
            "scale": 1e6,
        },
    )

    zrad0_ohm: float = field(
        default=50.0,
        metadata={
            "label": "Zrad0",
            "group": "Radial Stub",
            "description": "Characteristic impedance of the line feeding the radial stub. The sketch indicates a 50 Ohm line at this side.",
            "suffix": " Ohm",
            "minimum": 1.0,
            "maximum": 500.0,
            "step": 1.0,
            "decimals": 2,
        },
    )
    zrad1_len_m: float = field(
        default=57.0e-6,
        metadata={
            "label": "L1",
            "group": "Radial Stub",
            "description": "Length of the feed line before the radial fan.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 10000.0,
            "step": 0.5,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    zrad1_width_m: float = field(
        default=4.0e-6,
        metadata={
            "label": "W1",
            "group": "Radial Stub",
            "description": "Width of the feed line before the radial fan.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    radial_r_min_m: float = field(
        default=4.0e-6,
        metadata={
            "label": "Rmin",
            "group": "Radial Stub",
            "description": "Inner radius of the radial stub sector.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    radial_r_max_m: float = field(
        default=38.0e-6,
        metadata={
            "label": "Rmax",
            "group": "Radial Stub",
            "description": "Outer radius of the radial stub sector.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 10000.0,
            "step": 0.5,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    radial_angle_deg: float = field(
        default=113.0,
        metadata={
            "label": "Angle",
            "group": "Radial Stub",
            "description": "Opening angle of the radial fan in degrees.",
            "suffix": " deg",
            "minimum": 1.0,
            "maximum": 359.0,
            "step": 1.0,
            "decimals": 1,
        },
    )
    zrad3_len_m: float = field(
        default=4.0e-6,
        metadata={
            "label": "L3",
            "group": "Radial Stub",
            "description": "Post-stub microstrip length of the narrow matching line.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    zrad3_width_m: float = field(
        default=4.0e-6,
        metadata={
            "label": "W3",
            "group": "Radial Stub",
            "description": "Post-stub microstrip width of the narrow matching line.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    zrad4_len_m: float = field(
        default=3.0e-6,
        metadata={
            "label": "L2 · L4/2",
            "group": "Radial Stub",
            "description": "Элемент {sis_line} «Линия SIS», второй участок (бывший Lw4): длина от SIS до Radial Stub line.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    zrad4_width_m: float = field(
        default=6.0e-6,
        metadata={
            "label": "W2 · W4",
            "group": "Radial Stub",
            "description": "Элемент {sis_line} «Линия SIS», второй участок (бывший Ww4): ширина до поправки dW.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )

    mex4_len_m: float = field(
        default=3.0e-6,
        metadata={
            "label": "L1 · L4/2",
            "group": "Radial Stub",
            "description": "Элемент {sis_line} «Линия SIS», первый участок (бывшая линия у SIS): длина от элемента {before_sis} до SIS.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )
    mex4_width_m: float = field(
        default=6.0e-6,
        metadata={
            "label": "W1 · W4",
            "group": "Radial Stub",
            "description": "Элемент {sis_line} «Линия SIS», первый участок (бывшая линия у SIS): ширина до поправки dW; металл на схеме W1 + dW.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )

    # Mex01/Mex02/Mex03 in drawing order (FFO -> SIS) and the two corner
    # transformers at the DC block, which always end Mex02 / start Mex03.
    mex01: tuple[Section, ...] = DEFAULT_MEX01
    mex02: tuple[Section, ...] = DEFAULT_MEX02
    corner_left: TransformerSection = DEFAULT_CORNER_LEFT
    corner_right: TransformerSection = DEFAULT_CORNER_RIGHT
    mex03: tuple[Section, ...] = DEFAULT_MEX03

    s21_freq_start_ghz: float = field(
        default=100.0,
        metadata={
            "label": "Sweep start",
            "group": "General",
            "description": "Start frequency for the S21 sweep.",
            "suffix": " GHz",
            "minimum": 0.01,
            "maximum": 10000.0,
            "step": 1.0,
            "decimals": 2,
        },
    )
    s21_freq_stop_ghz: float = field(
        default=900.0,
        metadata={
            "label": "Sweep stop",
            "group": "General",
            "description": "Stop frequency for the S21 sweep.",
            "suffix": " GHz",
            "minimum": 0.01,
            "maximum": 10000.0,
            "step": 1.0,
            "decimals": 2,
        },
    )
    s21_freq_step_ghz: float = field(
        default=5.0,
        metadata={
            "label": "Sweep step",
            "group": "General",
            "description": "Frequency step for the S21 sweep.",
            "suffix": " GHz",
            "minimum": 0.01,
            "maximum": 10000.0,
            "step": 1.0,
            "decimals": 2,
        },
    )
    z_ffo_ohm: float = field(
        default=0.15,
        metadata={
            "label": "Z FFO",
            "group": "General",
            "description": "Source impedance used on the FFO side in the S21 computation.",
            "suffix": " Ohm",
            "minimum": 0.001,
            "maximum": 1000.0,
            "step": 0.01,
            "decimals": 3,
        },
    )

    sis_area_um2: float = field(
        default=0.8,
        metadata={
            "label": "SIS area",
            "group": "SIS",
            "description": "Junction area of the SIS detector.",
            "suffix": " um^2",
            "minimum": 0.001,
            "maximum": 1000.0,
            "step": 0.01,
            "decimals": 3,
        },
    )
    sis_rn_area_ohm_um2: float = field(
        default=32.0,
        metadata={
            "label": "RnA",
            "group": "SIS",
            "description": "Normal resistance-area product of the SIS junction.",
            "suffix": " Ohm*um^2",
            "minimum": 0.001,
            "maximum": 10000.0,
            "step": 0.1,
            "decimals": 3,
        },
    )
    sis_cap_f_per_um2: float = field(
        default=8.3e-14,
        metadata={
            "label": "C0",
            "group": "SIS",
            "description": "Specific capacitance of the SIS junction.",
            "suffix": " pF/µm²",
            "minimum": 0.000001,
            "maximum": 1000.0,
            "step": 0.001,
            "decimals": 6,
            "scale": 1e12,
        },
    )
    sis_width_um: float = field(
        default=4.0,
        metadata={
            "label": "Wb",
            "group": "SIS",
            "description": "Wb — ширина, задающая индуктивность растекания токов вблизи детектора (индуктивная поправка у SIS).",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
        },
    )

    film_freq_start_ghz: float = field(
        default=20.0,
        metadata={
            "label": "Film grid start",
            "group": "Backend Grid",
            "description": "Start frequency for the precomputed conductivity table.",
            "suffix": " GHz",
            "minimum": 0.01,
            "maximum": 10000.0,
            "step": 1.0,
            "decimals": 2,
        },
    )
    film_freq_stop_ghz: float = field(
        default=1110.0,
        metadata={
            "label": "Film grid stop",
            "group": "Backend Grid",
            "description": "Stop frequency for the precomputed conductivity table.",
            "suffix": " GHz",
            "minimum": 0.01,
            "maximum": 10000.0,
            "step": 1.0,
            "decimals": 2,
        },
    )
    film_freq_step_ghz: float = field(
        default=20.0,
        metadata={
            "label": "Film grid step",
            "group": "Backend Grid",
            "description": "Frequency step for the precomputed conductivity table.",
            "suffix": " GHz",
            "minimum": 0.01,
            "maximum": 10000.0,
            "step": 1.0,
            "decimals": 2,
        },
    )

    def validate(self) -> None:
        """Validate core configuration values."""
        errors = validate_sections(self)
        if self.temperature_k <= 0:
            errors.append("temperature_k must be > 0")
        if self.film_freq_step_ghz <= 0:
            errors.append("film_freq_step_ghz must be > 0")
        if self.s21_freq_step_ghz <= 0:
            errors.append("s21_freq_step_ghz must be > 0")
        if self.film_freq_start_ghz >= self.film_freq_stop_ghz:
            errors.append("film_freq_start_ghz must be < film_freq_stop_ghz")
        if self.s21_freq_start_ghz >= self.s21_freq_stop_ghz:
            errors.append("s21_freq_start_ghz must be < s21_freq_stop_ghz")
        if self.s21_freq_start_ghz < self.film_freq_start_ghz:
            errors.append("s21_freq_start_ghz must be >= film_freq_start_ghz")
        if self.s21_freq_stop_ghz > self.film_freq_stop_ghz:
            errors.append("s21_freq_stop_ghz must be <= film_freq_stop_ghz")
        if self.block_neck_height_um > self.block_body_height_um:
            errors.append("block_neck_height_um must be <= block_body_height_um")
        if self.w_slot_m <= self.dw_m:
            errors.append("w_slot_m must be > dw_m so the corrected DC-block slot stays positive")
        if self.dc_gap_m <= 0:
            errors.append("dc_gap_m must be > 0: the two DC-block stubs are isolated")
        if errors:
            raise ValueError("; ".join(errors))

    def element_slots(self) -> tuple[ElementSlot, ...]:
        """Numbered elements of this configuration in drawing order."""
        return element_slots(self)

    def group_order(self) -> tuple[str, ...]:
        """Parameter groups top to bottom; element groups follow the drawing."""
        return (*FIXED_GROUPS, *(slot.group for slot in self.element_slots()))

    def ui_fields(self) -> list[ConfigFieldInfo]:
        """Return visible field definitions for the grouped desktop UI.

        Element groups and numbers follow the current composition of
        Mex01/Mex02/Mex03, so the result depends on the instance.
        """
        slots = self.element_slots()
        by_id = {slot.element_id: slot for slot in slots}
        numbers = {
            "corner_left": by_id["T2.C"].number,
            "corner_right": by_id["T3.C"].number,
            "sis_line": by_id["SIS-line"].number,
            "before_sis": by_id["SIS-line"].number - 1,
        }
        visible: list[ConfigFieldInfo] = []
        for config_field in dataclass_fields(self):
            meta = dict(config_field.metadata)
            if not meta or not meta.get("visible", True):
                continue
            info = ConfigFieldInfo(
                name=config_field.name,
                label=meta["label"],
                group=meta["group"],
                description=meta["description"].format(**numbers),
                suffix=meta.get("suffix", ""),
                minimum=meta.get("minimum", 0.0),
                maximum=meta.get("maximum", 10000.0),
                step=meta.get("step", 0.1),
                decimals=meta.get("decimals", 3),
            )
            if info.suffix == " GHz":
                info = replace(info, step=1.0 if "step" in info.name else 10.0)
            if info.suffix == " um" and info.group in {"DC block", "Radial Stub", "SIS"}:
                info = replace(info, step=0.5)
            if info.name == "sis_rn_area_ohm_um2":
                info = replace(info, step=0.5, label="RnS")
            element = None
            if info.group == "DC block":
                element = "DC"
            elif info.group == "SIS":
                element = "SIS"
            elif info.name.startswith(("mex4_", "zrad4_")):
                element = "SIS-line"
            elif info.name.startswith("zrad") and info.name[4] in "13":
                element = f"Ww{info.name[4]}"
            elif info.group == "Radial Stub":
                element = "Radial"
            if element is not None:
                slot = by_id[element]
                info = replace(info, element_id=element, group=slot.group, number=slot.number)
            visible.append(info)
        for slot in slots:
            if slot.prefix is None:
                continue
            visible.extend(self._element_fields(slot))
        general = (
            "s21_freq_start_ghz",
            "s21_freq_stop_ghz",
            "s21_freq_step_ghz",
            "z_ffo_ohm",
            "dw_m",
            "temperature_k",
            "e_sub",
            "h_sub_m",
        )
        # «Линия SIS»: the first (former SIS line) and second (former Lw4) parts.
        sis_line = ("mex4_len_m", "mex4_width_m", "zrad4_len_m", "zrad4_width_m")
        order = {name: index for index, name in enumerate(general + sis_line)}
        # Grouping is per group name, so only the order inside these groups changes.
        visible.sort(key=lambda info: order.get(info.name, -1))
        return [replace(info, decimals=_display_decimals(info)) for info in visible]

    @staticmethod
    def _element_fields(slot: ElementSlot) -> list[ConfigFieldInfo]:
        common = dict(
            group=slot.group,
            suffix=" um",
            minimum=0.1,
            step=0.5,
            element_id=slot.element_id,
            number=slot.number,
        )
        if slot.kind == "line":
            return [
                ConfigFieldInfo(
                    f"{slot.prefix}_width_m",
                    "W",
                    description=f"Элемент {slot.number}: ширина линии до поправки dW.",
                    maximum=1000.0,
                    **common,
                ),
                ConfigFieldInfo(
                    f"{slot.prefix}_length_m",
                    "L",
                    description=f"Элемент {slot.number}: длина линии.",
                    maximum=10000.0,
                    **common,
                ),
            ]
        corner = slot.kind == "corner"
        return [
            *(
                ConfigFieldInfo(
                    f"{slot.prefix}_{attribute}",
                    label,
                    description=_transformer_width_description(slot, label),
                    maximum=1000.0,
                    **common,
                )
                for attribute, label in (("w1_m", "W1"), ("w2_m", "W2"))
            ),
            ConfigFieldInfo(
                f"{slot.prefix}_length_m",
                "L",
                description="Общая длина трансформатора. Автоподбор целого шага ширины dw и числа срезов n = |W1−W2|/dw + 1; "
                + f"dl=0.5…{transformer_dl_max_um(corner):g} µm."
                + (
                    " У угловых трансформаторов это осевая линия L1+L2+L3: по горизонтали от торца,"
                    " по диагонали к оси ступни и вниз по ступне до шлейфа."
                    if corner
                    else ""
                ),
                maximum=10000.0,
                **common,
            ),
        ]

    def element_prefixes(self) -> tuple[str, ...]:
        """UI prefixes of the list elements and corners in drawing order."""
        return tuple(slot.prefix for slot in self.element_slots() if slot.prefix is not None)

    def element(self, prefix: str) -> TransformerSection | LineSection:
        """List element or corner by its UI prefix (``mex01_2``, ``corner_left``)."""
        return element_by_prefix(self, prefix)

    def with_values(self, **values: float) -> S21Config:
        """A copy with plain fields and element fields replaced, in SI units.

        Element fields are ``<prefix>_<attribute>``: ``w1_m``, ``w2_m``,
        ``n_um``, ``dl_m`` of a transformer, ``width_m``, ``length_m`` of a line.
        """
        plain: dict[str, float] = {}
        elements: dict[str, dict[str, float]] = {}
        for name, value in values.items():
            target = split_element_field(name, ("w1_m", "w2_m", "n_um", "dl_m", "width_m", "length_m"))
            if target is None:
                plain[name] = value
            else:
                elements.setdefault(target[0], {})[target[1]] = value
        config = replace(self, **plain)
        for prefix, changes in elements.items():
            config = with_element(config, prefix, replace(config.element(prefix), **changes))
        return config

    def ui_value(self, name: str) -> float:
        """Return a UI value, including the derived transformer length."""
        target = split_element_field(name)
        if target is not None:
            prefix, attribute = target
            return getattr(self.element(prefix), attribute) * ELEMENT_FIELD_SCALE
        return getattr(self, name) * self.field_scale(name)

    @classmethod
    def field_scale(cls, name: str) -> float:
        """Return the UI scale factor for a field.

        A value of ``1e6`` means the UI displays micrometers while the dataclass
        stores the corresponding value in meters.  The SIS capacitance uses
        ``1e12`` so the UI presents pF/µm² while the calculation continues to
        receive the legacy F/µm² value.
        """
        if split_element_field(name) is not None:
            return ELEMENT_FIELD_SCALE
        for config_field in dataclass_fields(cls):
            if config_field.name == name:
                return config_field.metadata.get("scale", 1.0)
        return 1.0


@dataclass(frozen=True)
class S21Result:
    """Results of the S21 calculation."""

    frequencies_ghz: list[float]
    s21_db: list[float]
    log_messages: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.frequencies_ghz)
