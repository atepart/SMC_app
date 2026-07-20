"""Baseline tests for geometry domain primitives."""

from __future__ import annotations

from aocapp.domain.models import Point, Rect, bounds_from_points


def test_bounds_from_points_wraps_all_coordinates() -> None:
    bounds = bounds_from_points([Point(3.0, -1.0), Point(-2.0, 5.0), Point(1.0, 2.0)])

    assert bounds == Rect(x=-2.0, y=-1.0, width=5.0, height=6.0)


def test_bounds_from_points_returns_zero_rect_for_empty_input() -> None:
    assert bounds_from_points([]) == Rect(x=0.0, y=0.0, width=0.0, height=0.0)
