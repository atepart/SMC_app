"""Domain models for S21 calculations and grouped UI metadata."""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dataclass_fields
from typing import ClassVar


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


@dataclass(frozen=True)
class S21Config:
    """Configuration for the S21 calculation example.

    All lengths are in meters unless the field name ends with ``_um``.
    Frequencies are in GHz and temperatures are in Kelvin.

    The class also stores presentation metadata so the desktop UI can render
    the parameters in grouped sections with tooltips instead of a flat list.
    """

    GROUP_ORDER: ClassVar[tuple[str, ...]] = (
        "EL1 Material",
        "EL2 Material",
        "Dielectrics",
        "Block 1 / Block 2",
        "DC Break",
        "Radial Stub",
        "Block SIS",
        "Sweep / Source",
        "Backend Grid",
    )

    temperature_k: float = field(
        default=4.2,
        metadata={
            "label": "T env",
            "group": "EL1 Material",
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
            "label": "alpha EL1",
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
            "label": "alpha EL2",
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
            "label": "Delta0 EL1",
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
            "label": "Delta0 EL2",
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
            "label": "sigma EL1",
            "group": "EL1 Material",
            "description": "Normal-state conductivity sigma_1 of electrode EL1.",
            "suffix": " 1/(Ohm*m)",
            "minimum": 1.0,
            "maximum": 1.0e9,
            "step": 1.0e5,
            "decimals": 0,
        },
    )
    sigma0_bot: float = field(
        default=18.0e6,
        metadata={
            "label": "sigma EL2",
            "group": "EL2 Material",
            "description": "Normal-state conductivity sigma_2 of electrode EL2.",
            "suffix": " 1/(Ohm*m)",
            "minimum": 1.0,
            "maximum": 1.0e9,
            "step": 1.0e5,
            "decimals": 0,
        },
    )

    d_top_m: float = field(
        default=0.35e-6,
        metadata={
            "label": "d EL1",
            "group": "EL1 Material",
            "description": "Thickness of the top superconducting electrode film.",
            "suffix": " um",
            "minimum": 0.001,
            "maximum": 100.0,
            "step": 0.01,
            "decimals": 4,
            "scale": 1e6,
        },
    )
    d_bot_m: float = field(
        default=0.20e-6,
        metadata={
            "label": "d EL2",
            "group": "EL2 Material",
            "description": "Thickness of the bottom superconducting electrode film.",
            "suffix": " um",
            "minimum": 0.001,
            "maximum": 100.0,
            "step": 0.01,
            "decimals": 4,
            "scale": 1e6,
        },
    )

    h12_m: float = field(
        default=0.465729e-6,
        metadata={
            "label": "h12",
            "group": "Dielectrics",
            "description": "Thickness of the inter-electrode dielectric between EL1 and EL2.",
            "suffix": " um",
            "minimum": 0.001,
            "maximum": 100.0,
            "step": 0.01,
            "decimals": 4,
            "scale": 1e6,
        },
    )
    e12: float = field(
        default=4.28265,
        metadata={
            "label": "eps12",
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
            "suffix": " um",
            "minimum": 0.001,
            "maximum": 100.0,
            "step": 0.01,
            "decimals": 4,
            "scale": 1e6,
        },
    )
    e1: float = field(
        default=4.44084,
        metadata={
            "label": "eps1",
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
            "label": "eps sub",
            "group": "Dielectrics",
            "description": "Relative permittivity of the substrate used for the slot/DC-break model.",
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
            "group": "Dielectrics",
            "description": "Substrate thickness for the slot/DC-break model.",
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
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 2000.0,
            "step": 0.5,
            "decimals": 2,
        },
    )

    f0_ghz: float = field(
        default=650.0,
        metadata={
            "label": "f0",
            "group": "Sweep / Source",
            "description": "Reference frequency used by the legacy chain at the radial-stub-side line segment.",
            "suffix": " GHz",
            "minimum": 1.0,
            "maximum": 5000.0,
            "step": 1.0,
            "decimals": 2,
        },
    )
    dw_m: float = field(
        default=0.5e-6,
        metadata={
            "label": "DW",
            "group": "DC Break",
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
            "group": "DC Break",
            "description": "Slot width in the DC-break/slot antenna element.",
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
            "group": "DC Break",
            "description": "Slot length in the DC-break/slot antenna element.",
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
            "group": "DC Break",
            "description": "Offset between the slot center and the slot antenna feed section.",
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
            "group": "DC Break",
            "description": "Microstrip width inside the DC-break section before the bridge/slot coupling.",
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
            "group": "DC Break",
            "description": "Microstrip length inside the DC-break section before the slot element.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 10000.0,
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
            "label": "Lw1",
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
            "label": "Ww1",
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
            "label": "Lw3",
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
            "label": "Ww3",
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
            "label": "Lw4",
            "group": "Radial Stub",
            "description": "Short wide line after the narrow radial-stub output section.",
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
            "label": "Ww4",
            "group": "Radial Stub",
            "description": "Width of the short wide line after the narrow radial-stub output section.",
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
            "label": "Mex4 L",
            "group": "Radial Stub",
            "description": "Length of the microstrip segment immediately after the radial stub shunt branch.",
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
            "label": "Mex4 W",
            "group": "Radial Stub",
            "description": "Width of the microstrip segment immediately after the radial stub shunt branch.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
            "scale": 1e6,
        },
    )

    transf_1_w_start_m: float = field(default=6.0e-6, metadata={"label": "T1 Wstart", "group": "Block SIS", "description": "Transformer 1 start width.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_1_w_end_m: float = field(default=18.0e-6, metadata={"label": "T1 Wend", "group": "Block SIS", "description": "Transformer 1 end width.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_1_dwdl_um: float = field(default=6.0, metadata={"label": "T1 dW/dL", "group": "Block SIS", "description": "Width slope of transformer 1, used to infer its transition length.", "suffix": " um/um", "minimum": 0.01, "maximum": 100.0, "step": 0.1, "decimals": 3})
    transf_1_dl_m: float = field(default=0.9e-6, metadata={"label": "T1 dL", "group": "Block SIS", "description": "Internal discretization step for transformer 1 in the calculator.", "suffix": " um", "minimum": 0.001, "maximum": 100.0, "step": 0.01, "decimals": 4, "scale": 1e6})
    msl_4_len_m: float = field(default=27.0e-6, metadata={"label": "MSL4 L", "group": "Block SIS", "description": "Length of microstrip line section 4.", "suffix": " um", "minimum": 0.1, "maximum": 10000.0, "step": 0.5, "decimals": 3, "scale": 1e6})
    msl_4_width_m: float = field(default=18.0e-6, metadata={"label": "MSL4 W", "group": "Block SIS", "description": "Width of microstrip line section 4.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_2_w_start_m: float = field(default=18.0e-6, metadata={"label": "T2 Wstart", "group": "Block SIS", "description": "Transformer 2 start width.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_2_w_end_m: float = field(default=4.0e-6, metadata={"label": "T2 Wend", "group": "Block SIS", "description": "Transformer 2 end width.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_2_dwdl_um: float = field(default=2.0, metadata={"label": "T2 dW/dL", "group": "Block SIS", "description": "Width slope of transformer 2, used to infer its transition length.", "suffix": " um/um", "minimum": 0.01, "maximum": 100.0, "step": 0.1, "decimals": 3})
    transf_2_dl_m: float = field(default=0.9e-6, metadata={"label": "T2 dL", "group": "Block SIS", "description": "Internal discretization step for transformer 2 in the calculator.", "suffix": " um", "minimum": 0.001, "maximum": 100.0, "step": 0.01, "decimals": 4, "scale": 1e6})
    msl_5_len_m: float = field(default=10.0e-6, metadata={"label": "MSL5 L", "group": "Block SIS", "description": "Length of microstrip line section 5.", "suffix": " um", "minimum": 0.1, "maximum": 10000.0, "step": 0.5, "decimals": 3, "scale": 1e6})
    msl_5_width_m: float = field(default=4.0e-6, metadata={"label": "MSL5 W", "group": "Block SIS", "description": "Width of microstrip line section 5.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_3_w_start_m: float = field(default=6.0e-6, metadata={"label": "T3 Wstart", "group": "Block SIS", "description": "Transformer 3 start width.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_3_w_end_m: float = field(default=10.0e-6, metadata={"label": "T3 Wend", "group": "Block SIS", "description": "Transformer 3 end width.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_3_dwdl_um: float = field(default=1.0, metadata={"label": "T3 dW/dL", "group": "Block SIS", "description": "Width slope of transformer 3, used to infer its transition length.", "suffix": " um/um", "minimum": 0.01, "maximum": 100.0, "step": 0.1, "decimals": 3})
    transf_3_dl_m: float = field(default=1.2e-6, metadata={"label": "T3 dL", "group": "Block SIS", "description": "Internal discretization step for transformer 3 in the calculator.", "suffix": " um", "minimum": 0.001, "maximum": 100.0, "step": 0.01, "decimals": 4, "scale": 1e6})

    transf_4_w_start_m: float = field(default=10.0e-6, metadata={"label": "T4 Wstart", "group": "Block SIS", "description": "Transformer 4 start width.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_4_w_end_m: float = field(default=6.0e-6, metadata={"label": "T4 Wend", "group": "Block SIS", "description": "Transformer 4 end width.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_4_dwdl_um: float = field(default=1.0, metadata={"label": "T4 dW/dL", "group": "Block SIS", "description": "Width slope of transformer 4, used to infer its transition length.", "suffix": " um/um", "minimum": 0.01, "maximum": 100.0, "step": 0.1, "decimals": 3})
    transf_4_dl_m: float = field(default=1.2e-6, metadata={"label": "T4 dL", "group": "Block SIS", "description": "Internal discretization step for transformer 4 in the calculator.", "suffix": " um", "minimum": 0.001, "maximum": 100.0, "step": 0.01, "decimals": 4, "scale": 1e6})
    msl_6_len_m: float = field(default=25.0e-6, metadata={"label": "MSL6 L", "group": "Block SIS", "description": "Length of microstrip line section 6.", "suffix": " um", "minimum": 0.1, "maximum": 10000.0, "step": 0.5, "decimals": 3, "scale": 1e6})
    msl_6_width_m: float = field(default=4.0e-6, metadata={"label": "MSL6 W", "group": "Block SIS", "description": "Width of microstrip line section 6.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_5_w_start_m: float = field(default=6.0e-6, metadata={"label": "T5 Wstart", "group": "Block SIS", "description": "Transformer 5 start width.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_5_w_end_m: float = field(default=18.0e-6, metadata={"label": "T5 Wend", "group": "Block SIS", "description": "Transformer 5 end width.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_5_dwdl_um: float = field(default=3.0, metadata={"label": "T5 dW/dL", "group": "Block SIS", "description": "Width slope of transformer 5, used to infer its transition length.", "suffix": " um/um", "minimum": 0.01, "maximum": 100.0, "step": 0.1, "decimals": 3})
    transf_5_dl_m: float = field(default=1.2e-6, metadata={"label": "T5 dL", "group": "Block SIS", "description": "Internal discretization step for transformer 5 in the calculator.", "suffix": " um", "minimum": 0.001, "maximum": 100.0, "step": 0.01, "decimals": 4, "scale": 1e6})
    msl_7_len_m: float = field(default=24.0e-6, metadata={"label": "MSL7 L", "group": "Block SIS", "description": "Length of microstrip line section 7.", "suffix": " um", "minimum": 0.1, "maximum": 10000.0, "step": 0.5, "decimals": 3, "scale": 1e6})
    msl_7_width_m: float = field(default=18.0e-6, metadata={"label": "MSL7 W", "group": "Block SIS", "description": "Width of microstrip line section 7.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_6_w_start_m: float = field(default=18.0e-6, metadata={"label": "T6 Wstart", "group": "Block SIS", "description": "Transformer 6 start width, leading into the 50 Ohm wide section.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_6_w_end_m: float = field(default=48.0e-6, metadata={"label": "T6 Wend", "group": "Block SIS", "description": "Transformer 6 end width, leading into the 50 Ohm wide section.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_6_dwdl_um: float = field(default=3.0, metadata={"label": "T6 dW/dL", "group": "Block SIS", "description": "Width slope of transformer 6, used to infer its transition length.", "suffix": " um/um", "minimum": 0.01, "maximum": 100.0, "step": 0.1, "decimals": 3})
    transf_6_dl_m: float = field(default=1.2e-6, metadata={"label": "T6 dL", "group": "Block SIS", "description": "Internal discretization step for transformer 6 in the calculator.", "suffix": " um", "minimum": 0.001, "maximum": 100.0, "step": 0.01, "decimals": 4, "scale": 1e6})
    msl_8_len_m: float = field(default=13.0e-6, metadata={"label": "MSL8 L", "group": "Block SIS", "description": "Length of the wide 50 Ohm line near the SIS block.", "suffix": " um", "minimum": 0.1, "maximum": 10000.0, "step": 0.5, "decimals": 3, "scale": 1e6})
    msl_8_width_m: float = field(default=50.0e-6, metadata={"label": "MSL8 W", "group": "Block SIS", "description": "Width of the wide 50 Ohm line near the SIS block.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_7_w_start_m: float = field(default=49.0e-6, metadata={"label": "T7 Wstart", "group": "Block SIS", "description": "Transformer 7 start width from the 50 Ohm line toward the SIS connection.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_7_w_end_m: float = field(default=14.0e-6, metadata={"label": "T7 Wend", "group": "Block SIS", "description": "Transformer 7 end width from the 50 Ohm line toward the SIS connection.", "suffix": " um", "minimum": 0.1, "maximum": 1000.0, "step": 0.1, "decimals": 3, "scale": 1e6})
    transf_7_dwdl_um: float = field(default=5.0, metadata={"label": "T7 dW/dL", "group": "Block SIS", "description": "Width slope of transformer 7, used to infer its transition length.", "suffix": " um/um", "minimum": 0.01, "maximum": 100.0, "step": 0.1, "decimals": 3})
    transf_7_dl_m: float = field(default=1.2e-6, metadata={"label": "T7 dL", "group": "Block SIS", "description": "Internal discretization step for transformer 7 in the calculator.", "suffix": " um", "minimum": 0.001, "maximum": 100.0, "step": 0.01, "decimals": 4, "scale": 1e6})

    s21_freq_start_ghz: float = field(default=100.0, metadata={"label": "Sweep start", "group": "Sweep / Source", "description": "Start frequency for the S21 sweep.", "suffix": " GHz", "minimum": 0.01, "maximum": 10000.0, "step": 1.0, "decimals": 2})
    s21_freq_stop_ghz: float = field(default=900.0, metadata={"label": "Sweep stop", "group": "Sweep / Source", "description": "Stop frequency for the S21 sweep.", "suffix": " GHz", "minimum": 0.01, "maximum": 10000.0, "step": 1.0, "decimals": 2})
    s21_freq_step_ghz: float = field(default=5.0, metadata={"label": "Sweep step", "group": "Sweep / Source", "description": "Frequency step for the S21 sweep.", "suffix": " GHz", "minimum": 0.01, "maximum": 10000.0, "step": 1.0, "decimals": 2})
    z_ffo_ohm: float = field(default=0.15, metadata={"label": "Z FFO", "group": "Sweep / Source", "description": "Source impedance used on the FFO side in the S21 computation.", "suffix": " Ohm", "minimum": 0.001, "maximum": 1000.0, "step": 0.01, "decimals": 3})

    sis_area_um2: float = field(
        default=0.8,
        metadata={
            "label": "SIS area",
            "group": "Block SIS",
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
            "group": "Block SIS",
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
            "group": "Block SIS",
            "description": "Specific capacitance of the SIS junction.",
            "suffix": " F/um^2",
            "minimum": 1e-18,
            "maximum": 1e-9,
            "step": 1e-14,
            "decimals": 14,
        },
    )
    sis_width_um: float = field(
        default=4.0,
        metadata={
            "label": "W SIS",
            "group": "Block SIS",
            "description": "Effective width used in the inductive correction near the SIS junction.",
            "suffix": " um",
            "minimum": 0.1,
            "maximum": 1000.0,
            "step": 0.1,
            "decimals": 3,
        },
    )

    film_freq_start_ghz: float = field(default=20.0, metadata={"label": "Film grid start", "group": "Backend Grid", "description": "Start frequency for the precomputed conductivity table.", "suffix": " GHz", "minimum": 0.01, "maximum": 10000.0, "step": 1.0, "decimals": 2})
    film_freq_stop_ghz: float = field(default=1110.0, metadata={"label": "Film grid stop", "group": "Backend Grid", "description": "Stop frequency for the precomputed conductivity table.", "suffix": " GHz", "minimum": 0.01, "maximum": 10000.0, "step": 1.0, "decimals": 2})
    film_freq_step_ghz: float = field(default=20.0, metadata={"label": "Film grid step", "group": "Backend Grid", "description": "Frequency step for the precomputed conductivity table.", "suffix": " GHz", "minimum": 0.01, "maximum": 10000.0, "step": 1.0, "decimals": 2})

    def validate(self) -> None:
        """Validate core configuration values."""
        errors = []
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
        if errors:
            raise ValueError("; ".join(errors))

    @classmethod
    def ui_fields(cls) -> list[ConfigFieldInfo]:
        """Return visible field definitions for the grouped desktop UI."""
        result: list[ConfigFieldInfo] = []
        for config_field in dataclass_fields(cls):
            meta = dict(config_field.metadata)
            if not meta:
                continue
            result.append(
                ConfigFieldInfo(
                    name=config_field.name,
                    label=meta["label"],
                    group=meta["group"],
                    description=meta["description"],
                    suffix=meta.get("suffix", ""),
                    minimum=meta.get("minimum", 0.0),
                    maximum=meta.get("maximum", 10000.0),
                    step=meta.get("step", 0.1),
                    decimals=meta.get("decimals", 3),
                    visible=meta.get("visible", True),
                )
            )
        return [field_info for field_info in result if field_info.visible]

    @classmethod
    def field_scale(cls, name: str) -> float:
        """Return the UI scale factor for a field.

        A value of ``1e6`` means the UI displays micrometers while the dataclass
        stores the corresponding value in meters.
        """
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
