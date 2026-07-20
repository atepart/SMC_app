"""Complex integration helpers for API calculations."""

from __future__ import annotations

from typing import Callable, Tuple

from numpy import imag, real
from scipy.integrate import quad

QUAD_ABS_TOL = 1.49e-25
QUAD_LIMIT = 400


class ComplexIntegrator:
    """Numerical integration helpers for complex-valued functions."""

    def real_integral(
        self,
        func: Callable,
        start: float,
        end: float,
        args: Tuple = (),
        **kwargs,
    ) -> float:
        """Integrate the real part of a complex function on [start, end]."""

        def real_f(x: float, args: Tuple = ()) -> float:
            return real(func(x, *args))

        return quad(
            real_f,
            start,
            end,
            (args,),
            epsabs=QUAD_ABS_TOL,
            limit=QUAD_LIMIT,
            maxp1=100,
            limlst=100,
            **kwargs,
        )[0]

    def imag_integral(
        self,
        func: Callable,
        start: float,
        end: float,
        args: Tuple = (),
        **kwargs,
    ) -> float:
        """Integrate the imaginary part of a complex function on [start, end]."""

        def imag_f(x: float, args: Tuple = ()) -> float:
            return imag(func(x, *args))

        return quad(
            imag_f,
            start,
            end,
            (args,),
            full_output=0,
            epsabs=QUAD_ABS_TOL,
            limit=QUAD_LIMIT,
            maxp1=100,
            limlst=100,
            **kwargs,
        )[0]

    def complex_integral(
        self,
        func: Callable,
        start: float,
        end: float,
        args: Tuple = (),
        **kwargs,
    ) -> complex:
        """Integrate a complex function on [start, end] by splitting into parts."""
        real_part = self.real_integral(func, start, end, args=args, **kwargs)
        imag_part = self.imag_integral(func, start, end, args=args, **kwargs)
        return real_part + 1j * imag_part
