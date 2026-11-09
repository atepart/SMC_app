"""Variable element chain of the Mex01/Mex02/Mex03 sections (GitHub #11, WP-044).

The three matching sections are ordered lists of stepped transformers and
microstrip lines in drawing order, from the FFO to the SIS.  The corner
transformers at the DC block (the last element of Mex02 and the first of
Mex03) keep a fixed place and are stored separately, so they can never be
removed.  Element numbers run through the whole chain without gaps and are
derived from the current composition, never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import floor, isfinite
from typing import TYPE_CHECKING, Union

from smcapp.domain.transformers import derive_transformer_steps, transformer_length_m

if TYPE_CHECKING:
    from smcapp.domain.s21_models import S21Config


@dataclass(frozen=True)
class TransformerSection:
    """Stepped transformer; W1 on the FFO (left) side, W2 on the SIS (right) side.

    ``n_um`` is the width increment between slices and ``dl_m`` the length of
    every slice, exactly as the calculator consumes them (``dwdl``/``dl``).
    """

    w1_m: float
    w2_m: float
    n_um: float
    dl_m: float

    @property
    def left_width_m(self) -> float:
        return self.w1_m

    @property
    def right_width_m(self) -> float:
        return self.w2_m

    @property
    def length_m(self) -> float:
        return transformer_length_m(self.w2_m, self.w1_m, self.n_um, self.dl_m)


@dataclass(frozen=True)
class LineSection:
    """Microstrip line of constant width."""

    width_m: float
    length_m: float

    @property
    def left_width_m(self) -> float:
        return self.width_m

    @property
    def right_width_m(self) -> float:
        return self.width_m


Section = Union[TransformerSection, LineSection]

SECTIONS = ("mex01", "mex02", "mex03")
SECTION_TITLES = {"mex01": "Mex01", "mex02": "Mex02", "mex03": "Mex03"}
CORNERS = ("corner_left", "corner_right")
# Corner transformers: left one ends Mex02, right one starts Mex03.
CORNER_IDS = {"corner_left": "T2.C", "corner_right": "T3.C"}

# Defaults in drawing order (the former T7, MSL8, T6 | MSL7, T5, MSL6, T4 |
# T3, MSL5, T2, MSL4, T1 with W1 = former Wend and W2 = former Wstart).
DEFAULT_MEX01: tuple[Section, ...] = (
    TransformerSection(14.0e-6, 49.0e-6, 5.0, 1.2e-6),
    LineSection(50.0e-6, 13.0e-6),
    TransformerSection(48.0e-6, 18.0e-6, 3.0, 1.2e-6),
)
DEFAULT_MEX02: tuple[Section, ...] = (
    LineSection(18.0e-6, 24.0e-6),
    TransformerSection(18.0e-6, 6.0e-6, 3.0, 1.2e-6),
    LineSection(4.0e-6, 25.0e-6),
)
DEFAULT_CORNER_LEFT = TransformerSection(6.0e-6, 10.0e-6, 1.0, 1.2e-6)
DEFAULT_CORNER_RIGHT = TransformerSection(10.0e-6, 6.0e-6, 1.0, 1.2e-6)
DEFAULT_MEX03: tuple[Section, ...] = (
    LineSection(4.0e-6, 10.0e-6),
    TransformerSection(4.0e-6, 18.0e-6, 2.0, 0.9e-6),
    LineSection(18.0e-6, 27.0e-6),
    TransformerSection(18.0e-6, 6.0e-6, 6.0, 0.9e-6),
)

# Sizes of added elements (GitHub #11).
NEW_LINE_LENGTH_M = 20e-6
NEW_TRANSFORMER_LENGTH_M = 4e-6

FIXED_TITLES = {
    "DC": "DC block",
    "SIS-line": "Линия SIS",
    "SIS": "SIS",
    "Ww3": "Radial Stub line",
    "Radial": "Radial Stub",
    "Ww1": "Выходная линия",
}
# Elements after Mex03, in drawing order.
TAIL_IDS = ("SIS-line", "SIS", "Ww3", "Radial", "Ww1")


@dataclass(frozen=True)
class ElementSlot:
    """One numbered element of the drawing in the current composition.

    ``section``/``index`` locate an element of a variable section (only those
    can be removed or followed by new elements); ``prefix`` names its UI
    fields, e.g. ``mex03_2_width_m``.
    """

    element_id: str
    number: int
    kind: str  # "transformer", "line", "corner" or "fixed"
    section: str | None = None
    index: int | None = None
    prefix: str | None = None

    @property
    def title(self) -> str:
        if self.kind in ("transformer", "corner"):
            return "Трансформатор"
        if self.kind == "line":
            return "Линия"
        return FIXED_TITLES[self.element_id]

    @property
    def group(self) -> str:
        """Display name shared by the parameter group, diagnostics and drawing."""
        return f"{self.number} · {self.title}"

    @property
    def editable(self) -> bool:
        """Only elements of Mex01/Mex02/Mex03 except the corners (owner's decision)."""
        return self.section is not None


def section_element_id(section: str, index: int, element: Section) -> str:
    kind = "T" if isinstance(element, TransformerSection) else "MSL"
    return f"{kind}{SECTIONS.index(section) + 1}.{index + 1}"


def section_prefix(section: str, index: int) -> str:
    return f"{section}_{index + 1}"


def element_slots(config: S21Config) -> tuple[ElementSlot, ...]:
    """Every numbered element in drawing order with its through number."""
    slots: list[ElementSlot] = []

    def add(element_id: str, kind: str, **extra) -> None:
        slots.append(ElementSlot(element_id, len(slots) + 1, kind, **extra))

    def add_section(section: str) -> None:
        for index, element in enumerate(getattr(config, section)):
            kind = "transformer" if isinstance(element, TransformerSection) else "line"
            add(
                section_element_id(section, index, element),
                kind,
                section=section,
                index=index,
                prefix=section_prefix(section, index),
            )

    add_section("mex01")
    add_section("mex02")
    add(CORNER_IDS["corner_left"], "corner", prefix="corner_left")
    add("DC", "fixed")
    add(CORNER_IDS["corner_right"], "corner", prefix="corner_right")
    add_section("mex03")
    for element_id in TAIL_IDS:
        add(element_id, "fixed")
    return tuple(slots)


def element_order(config: S21Config) -> tuple[str, ...]:
    return tuple(slot.element_id for slot in element_slots(config))


def element_numbers(config: S21Config) -> dict[str, int]:
    return {slot.element_id: slot.number for slot in element_slots(config)}


def element_by_prefix(config: S21Config, prefix: str) -> TransformerSection | LineSection:
    """The element of a variable section or a corner named by its UI prefix."""
    if prefix in CORNERS:
        return getattr(config, prefix)
    section, _, position = prefix.rpartition("_")
    if section not in SECTIONS or not position.isdigit():
        raise KeyError(prefix)
    elements = getattr(config, section)
    index = int(position) - 1
    if not 0 <= index < len(elements):
        raise KeyError(prefix)
    return elements[index]


def element_prefixes(config: S21Config) -> tuple[str, ...]:
    """UI prefixes of every list element and corner in drawing order."""
    return tuple(slot.prefix for slot in element_slots(config) if slot.prefix is not None)


def composition(config: S21Config) -> tuple[tuple[str, ...], ...]:
    """Kinds of the elements of each section: equal compositions share UI fields."""
    return tuple(
        tuple("T" if isinstance(element, TransformerSection) else "MSL" for element in getattr(config, section))
        for section in SECTIONS
    )


def with_element(config: S21Config, prefix: str, element: Section) -> S21Config:
    """Return *config* with the element at *prefix* replaced by *element*."""
    if prefix in CORNERS:
        if not isinstance(element, TransformerSection):
            raise TypeError("Угловой элемент — всегда трансформатор")
        return replace(config, **{prefix: element})
    element_by_prefix(config, prefix)  # KeyError for an unknown prefix
    section, _, position = prefix.rpartition("_")
    elements = list(getattr(config, section))
    elements[int(position) - 1] = element
    return replace(config, **{section: tuple(elements)})


def _slot(config: S21Config, element_id: str) -> ElementSlot:
    for slot in element_slots(config):
        if slot.element_id == element_id:
            return slot
    raise KeyError(element_id)


def can_remove(config: S21Config, element_id: str) -> bool:
    """A section element can go unless it is the last one of its section.

    An empty section would leave nothing to call «Добавить» on.
    """
    slot = _slot(config, element_id)
    return slot.editable and len(getattr(config, slot.section)) > 1


def can_insert_after(config: S21Config, element_id: str) -> bool:
    return _slot(config, element_id).editable


def remove_element(config: S21Config, element_id: str) -> S21Config:
    """Drop one element of Mex01/Mex02/Mex03; numbers after it move up."""
    slot = _slot(config, element_id)
    if not slot.editable:
        raise ValueError(f"Элемент {slot.number} нельзя удалить")
    elements = list(getattr(config, slot.section))
    if len(elements) == 1:
        raise ValueError(f"Элемент {slot.number} — последний в {SECTION_TITLES[slot.section]}, его нельзя удалить")
    del elements[slot.index]
    return replace(config, **{slot.section: tuple(elements)})


def _next_left_width_m(config: S21Config, slot: ElementSlot) -> float:
    """First (left) width of the element drawn right after *slot*."""
    elements = getattr(config, slot.section)
    if slot.index + 1 < len(elements):
        return elements[slot.index + 1].left_width_m
    if slot.section == "mex01":
        return config.mex02[0].left_width_m
    if slot.section == "mex02":
        return config.corner_left.left_width_m
    return config.mex4_width_m  # Mex03 ends at the first part of «Линия SIS»


def new_transformer(w1_m: float, w2_m: float, length_m: float = NEW_TRANSFORMER_LENGTH_M) -> TransformerSection:
    """A transformer of length *length_m* between two widths.

    n and dl follow the usual automatic choice. When no such choice exists
    (a fractional width difference, or a dl outside the rule) the owner
    accepts an element outside the rule: the slices
    still add up to *length_m*, so drawing and calculation stay consistent.
    """
    try:
        steps = derive_transformer_steps(w1_m, w2_m, length_m)
        return TransformerSection(w1_m, w2_m, float(steps.n_um), steps.dl_m)
    except ValueError:
        delta_um = abs(w1_m - w2_m) * 1e6
        n_um = delta_um if delta_um > 0.01 else 1.0
        count = max(1, -floor(-((delta_um + 0.01) / n_um)))
        return TransformerSection(w1_m, w2_m, n_um, length_m / count)


def insert_after(config: S21Config, element_id: str) -> S21Config:
    """Add two elements after *element_id* (GitHub #11).

    After a line come a transformer and a line, after a transformer a line
    and a transformer.  The first new width is the last width of the element
    added to, the last new width is the first width of the following element;
    a new line is 20 µm long and a new transformer 4 µm.
    """
    slot = _slot(config, element_id)
    if not slot.editable:
        raise ValueError(f"После элемента {slot.number} нельзя добавлять элементы")
    elements = list(getattr(config, slot.section))
    anchor = elements[slot.index]
    first_w = anchor.right_width_m
    last_w = _next_left_width_m(config, slot)
    if isinstance(anchor, LineSection):
        added = (new_transformer(first_w, last_w), LineSection(last_w, NEW_LINE_LENGTH_M))
    else:
        added = (LineSection(first_w, NEW_LINE_LENGTH_M), new_transformer(first_w, last_w))
    elements[slot.index + 1 : slot.index + 1] = added
    return replace(config, **{slot.section: tuple(elements)})


def validate_sections(config: S21Config) -> list[str]:
    """Structural and numeric errors of the variable sections."""
    errors = []
    for section in SECTIONS:
        elements = getattr(config, section)
        if not isinstance(elements, tuple) or not elements:
            errors.append(f"{SECTION_TITLES[section]} must contain at least one element")
            continue
        for element in elements:
            if not isinstance(element, (TransformerSection, LineSection)):
                errors.append(f"{SECTION_TITLES[section]}: unknown element {element!r}")
    for corner in CORNERS:
        if not isinstance(getattr(config, corner), TransformerSection):
            errors.append(f"{corner} must be a transformer")
    if errors:
        return errors
    numbers = element_numbers(config)
    for slot in element_slots(config):
        if slot.prefix is None:
            continue
        element = element_by_prefix(config, slot.prefix)
        values = (
            (element.w1_m, element.w2_m, element.n_um, element.dl_m)
            if isinstance(element, TransformerSection)
            else (element.width_m, element.length_m)
        )
        if not all(isinstance(v, (int, float)) and isfinite(v) and v > 0 for v in values):
            errors.append(f"element {numbers[slot.element_id]}: sizes must be positive finite numbers")
    return errors


__all__ = [
    "CORNERS",
    "ElementSlot",
    "LineSection",
    "SECTIONS",
    "TransformerSection",
    "can_insert_after",
    "can_remove",
    "composition",
    "element_by_prefix",
    "element_numbers",
    "element_order",
    "element_prefixes",
    "element_slots",
    "insert_after",
    "new_transformer",
    "remove_element",
    "validate_sections",
    "with_element",
]
