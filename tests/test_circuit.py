"""WP-044: Mex01/Mex02/Mex03 as lists — numbering, removal and insertion."""

from __future__ import annotations

from dataclasses import replace

import pytest

from smcapp.domain.circuit import (
    LineSection,
    TransformerSection,
    can_insert_after,
    can_remove,
    element_numbers,
    element_order,
    insert_after,
    new_transformer,
    remove_element,
)
from smcapp.domain.s21_models import S21Config
from smcapp.infrastructure.geometry import IntegratedStructureCalculator
from smcapp.infrastructure.s21_calculator import build_default_s21_calculator

DEFAULT_ORDER = (
    "T1.1",
    "MSL1.2",
    "T1.3",
    "MSL2.1",
    "T2.2",
    "MSL2.3",
    "T2.C",
    "DC",
    "T3.C",
    "MSL3.1",
    "T3.2",
    "MSL3.3",
    "T3.4",
    "SIS-line",
    "SIS",
    "Ww3",
    "Radial",
    "Ww1",
)


def _id(config: S21Config, number: int) -> str:
    return next(slot.element_id for slot in config.element_slots() if slot.number == number)


def _element(config: S21Config, number: int):
    slot = next(slot for slot in config.element_slots() if slot.number == number)
    return config.element(slot.prefix)


def test_default_composition_keeps_numbers_1_to_18() -> None:
    config = S21Config()
    assert element_order(config) == DEFAULT_ORDER
    assert element_numbers(config) == {element: number for number, element in enumerate(DEFAULT_ORDER, 1)}
    assert [slot.group for slot in config.element_slots()][:3] == [
        "1 · Трансформатор",
        "2 · Линия",
        "3 · Трансформатор",
    ]
    assert [slot.number for slot in config.element_slots() if slot.editable] == [1, 2, 3, 4, 5, 6, 10, 11, 12, 13]


def test_removing_2_moves_every_later_number_up_without_gaps() -> None:
    config = S21Config()
    former_3 = _element(config, 3)
    former_sis_line = element_numbers(config)["SIS-line"]

    changed = remove_element(config, _id(config, 2))

    assert [slot.number for slot in changed.element_slots()] == list(range(1, 18))
    assert _element(changed, 2) == former_3
    assert changed.mex01 == (config.mex01[0], config.mex01[2])
    assert element_numbers(changed)["SIS-line"] == former_sis_line - 1
    assert element_numbers(changed)["DC"] == 7


def test_adding_to_line_4_gives_transformer_5_and_line_6_and_shifts_the_rest_by_2() -> None:
    config = S21Config()
    former_5, former_13 = _element(config, 5), _element(config, 13)

    changed = insert_after(config, _id(config, 4))

    assert [slot.number for slot in changed.element_slots()] == list(range(1, 21))
    kinds = {slot.number: slot.kind for slot in changed.element_slots()}
    assert (kinds[4], kinds[5], kinds[6]) == ("line", "transformer", "line")
    assert _element(changed, 7) == former_5
    assert _element(changed, 15) == former_13
    assert element_numbers(changed)["DC"] == 10
    assert element_numbers(changed)["Ww1"] == 20


def test_added_sizes_follow_the_issue_rules_after_a_transformer() -> None:
    config = S21Config()
    # After 5 (W2 = 6 µm) and before line 6 (W = 4 µm): line, then transformer.
    changed = insert_after(config, _id(config, 5))
    line, transformer = _element(changed, 6), _element(changed, 7)
    assert line == LineSection(6e-6, 20e-6)
    assert isinstance(transformer, TransformerSection)
    assert (transformer.w1_m, transformer.w2_m) == (6e-6, 4e-6)
    assert transformer.length_m == pytest.approx(4e-6)
    # Calculable: integer n, dw=2 preferred, dl within 0.2…5 µm (WP-054).
    assert transformer.n_um == 2 and transformer.dl_m == pytest.approx(2e-6)
    assert _element(changed, 8) == config.mex02[2]


@pytest.mark.parametrize(
    ("number", "next_width"),
    [
        (3, 18e-6),  # end of Mex01: the next element is line 4
        (6, 6e-6),  # end of Mex02: W1 of the corner transformer 7
        (13, 6e-6),  # end of Mex03: W1 of «Линия SIS»
        (10, 4e-6),  # start of Mex03: W1 of transformer 11
    ],
)
def test_last_added_width_is_the_first_width_of_the_next_element(number, next_width) -> None:
    config = S21Config(mex4_width_m=6e-6)
    anchor = _element(config, number)
    changed = insert_after(config, _id(config, number))
    first, second = _element(changed, number + 1), _element(changed, number + 2)
    assert first.left_width_m == anchor.right_width_m
    assert second.right_width_m == next_width
    if isinstance(anchor, LineSection):
        assert isinstance(first, TransformerSection) and second == LineSection(next_width, 20e-6)
        assert first.length_m == pytest.approx(4e-6)
    else:
        assert first == LineSection(anchor.right_width_m, 20e-6)
        assert isinstance(second, TransformerSection) and second.length_m == pytest.approx(4e-6)


def test_rectangular_and_fractional_transformers_are_allowed() -> None:
    rectangular = new_transformer(18e-6, 18e-6)
    assert rectangular.w1_m == rectangular.w2_m == 18e-6
    assert rectangular.length_m == pytest.approx(4e-6)
    fractional = new_transformer(6e-6, 10.5e-6)
    assert fractional.length_m == pytest.approx(4e-6)
    # Adding to line 4 (18 µm) before transformer 5 (W1 = 18 µm): rectangular.
    changed = insert_after(S21Config(), "MSL2.1")
    assert _element(changed, 5).w1_m == _element(changed, 5).w2_m == 18e-6


@pytest.mark.parametrize("element_id", ["T2.C", "DC", "T3.C", "SIS-line", "SIS", "Ww3", "Radial", "Ww1"])
def test_corners_dc_block_and_sis_node_cannot_be_changed(element_id) -> None:
    config = S21Config()
    assert not can_remove(config, element_id)
    assert not can_insert_after(config, element_id)
    with pytest.raises(ValueError, match="нельзя"):
        remove_element(config, element_id)
    with pytest.raises(ValueError, match="нельзя"):
        insert_after(config, element_id)


def test_the_last_element_of_a_section_stays() -> None:
    config = remove_element(remove_element(S21Config(), "T1.1"), "MSL1.1")
    assert len(config.mex01) == 1
    assert not can_remove(config, "T1.1")
    assert can_insert_after(config, "T1.1")
    with pytest.raises(ValueError, match="последний в Mex01"):
        remove_element(config, "T1.1")
    with pytest.raises(ValueError, match="Mex01 must contain"):
        replace(config, mex01=()).validate()


def _edited_configs():
    config = S21Config()
    yield "default", config
    for number in (1, 2, 3, 4, 5, 6, 10, 11, 12, 13):
        yield f"remove {number}", remove_element(config, _id(config, number))
        yield f"add after {number}", insert_after(config, _id(config, number))


@pytest.mark.parametrize(("name", "config"), list(_edited_configs()))
def test_schematic_follows_the_composition(name, config) -> None:
    geometry = IntegratedStructureCalculator().calculate(config)
    numbers = element_numbers(config)
    assert [element.number for element in geometry.elements] == list(range(1, len(numbers) + 1))
    assert {element.element_id: element.number for element in geometry.elements} == numbers
    callouts = {c.element_id: c.label.text for c in geometry.overview.callouts if c.label.text.isdigit()}
    assert callouts == {element: str(number) for element, number in numbers.items()}
    assert {owner for owner, _points in geometry.hit_areas} == set(numbers)
    # Neighbours touch: every section starts where the previous one ends.
    chain = [e for e in geometry.elements if e.element_id[0] in "TM" and not e.element_id.endswith(".C")]
    for left, right in zip(chain, chain[1:]):
        if left.output_port is not None and right.input_port is not None and right.number == left.number + 1:
            assert right.input_port.center == left.output_port.center


def test_cascade_follows_list_order_in_the_calculation() -> None:
    """Splitting line 12 into 10 µm + 17 µm keeps S21: lists are multiplied in order."""
    base = S21Config(s21_freq_start_ghz=300.0, s21_freq_stop_ghz=700.0, s21_freq_step_ghz=100.0)
    line = base.mex03[2]
    split = replace(
        base,
        mex03=(
            base.mex03[0],
            base.mex03[1],
            replace(line, length_m=10e-6),
            replace(line, length_m=17e-6),
            base.mex03[3],
        ),
    )
    calculator = build_default_s21_calculator()
    whole = calculator.calculate(base).s21_db
    parts = calculator.calculate(split).s21_db
    assert parts == pytest.approx(whole, rel=1e-9, abs=1e-9)
    removed = calculator.calculate(remove_element(base, "MSL3.3")).s21_db
    assert removed != pytest.approx(whole, abs=1e-3)
