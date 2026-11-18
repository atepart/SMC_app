"""Readable text export of the structure parameters («Экспорт → Параметры HFSS», WP-058).

The text mirrors the parameter panel: its groups in panel order, then
``Label = value unit`` lines with the labels, units and decimals of the
editors.  Hidden fields (Δ₀) are left out.  Transformers add their slicing
(``dw``, ``n``, ``dl``) and Dielectrics the computed stack, as the panel hints
show them.  The values come from the configuration Run S21 would use.
"""

from __future__ import annotations

from pathlib import Path

from smcapp.domain.circuit import TransformerSection
from smcapp.domain.dielectrics import DielectricStack
from smcapp.domain.s21_models import ConfigFieldInfo, S21Config, split_element_field
from smcapp.domain.transformers import transformer_slice_count

HFSS_EXPORT_SUFFIX = ".txt"


def field_unit(info: ConfigFieldInfo) -> str:
    """Unit as written next to the editor: ``µm``, ``nm``, ``GHz``, ``Ω``, ``1/(Ω·µm)``."""
    if info.name.startswith("sigma0_"):
        return "1/(Ω·µm)"  # entered per µm, stored per metre
    text = info.suffix.strip()
    for old, new in (("Ohm", "Ω"), ("um", "µm"), ("^2", "²"), ("*", "·"), ("deg", "°")):
        text = text.replace(old, new)
    return text


def format_field(config: S21Config, info: ConfigFieldInfo) -> str:
    """``Label = value unit`` with the editor's decimals."""
    value = config.ui_value(info.name)
    text = f"{value:.{info.decimals}f}"
    if text.startswith("-") and float(text) == 0.0:
        text = text[1:]
    unit = field_unit(info)
    separator = "" if unit in ("", "°") else " "
    return f"{info.label} = {text}{separator}{unit}"


def transformer_steps_text(element: TransformerSection) -> str:
    """Slicing of a transformer as the panel hint writes it: ``dw=2 µm; n=15; dl=0.373333 µm``."""
    slices = transformer_slice_count(element.w1_m, element.w2_m, element.n_um)
    return f"dw={element.n_um:g} µm; n={slices}; dl={element.dl_m * 1e6:g} µm"


def dielectric_stack_text(stack: DielectricStack) -> list[str]:
    """Computed insulator stack, as under the Dielectrics fields."""
    return [
        f"H1 = h1 + Ha = {stack.h1_m * 1e9:.4f} nm; ε₁ = {stack.e1:.5f}",
        f"H12 = h1 + h2 + Ha = {stack.h12_m * 1e9:.4f} nm; ε₁₂ = {stack.e12:.5f}",
    ]


def hfss_parameters_text(config: S21Config, same_material: bool | None = None, version: str | None = None) -> str:
    """Every visible parameter of *config*, grouped as in the panel.

    *same_material* adds the state of «Use the same material as EL1» to the
    EL2 group when the caller knows it; *version* goes into the title line.
    """
    fields_by_group: dict[str, list[ConfigFieldInfo]] = {}
    for info in config.ui_fields():
        fields_by_group.setdefault(info.group, []).append(info)

    title = "Параметры структуры SMC_app" + (f" {version}" if version else "")
    lines = [f"# {title}", ""]
    for group in config.group_order():
        group_fields = fields_by_group.get(group, [])
        if not group_fields:
            continue
        lines.append(group)
        lines.extend(format_field(config, info) for info in group_fields)
        if group == "EL2 Material" and same_material is not None:
            lines.append(f"Материал как у EL1 (Tc, α, σ) = {'да' if same_material else 'нет'}")
        if group == "Dielectrics":
            lines.extend(dielectric_stack_text(config.dielectric_stack()))
        element = split_element_field(group_fields[0].name)
        if element is not None:
            section = config.element(element[0])
            if isinstance(section, TransformerSection):
                lines.append(transformer_steps_text(section))
        lines.append("")
    return "\n".join(lines)


def write_hfss_parameters(path: str | Path, text: str) -> Path:
    """Write *text* as UTF-8; a name without extension gets ``.txt``."""
    destination = Path(path).expanduser()
    if not destination.suffix:
        destination = destination.with_suffix(HFSS_EXPORT_SUFFIX)
    destination.write_text(text, encoding="utf-8")
    return destination
