"""This module calculates the ABCD-matrix of the superconducting microstrip line (MSL)
   using the expressions from (Yassin, G., & Withington, S. (1995). Electromagnetic models 
   for superconducting millimetre-wave and sub-millimetre-wave microstrip transmission lines. 
   Journal of Physics D: Applied Physics, 28(9), 1983.)
   The impedance of the superconducting films which form the elctrodes are calculated numerically using 'Mattis_Bardeen.py' module"""

import Impedance as Imp
import Mattis_Bardeen as MB
from numpy import abs, arctanh, array, cosh, exp, imag, log, pi, real, sinh, sqrt, tanh

mu0 = 4.0 * pi * 1e-7  # permeability of vacuum
eps0 = 8.8542 * 1e-12  # permittivity of vacuum


def chi_Kf1(W, H, d_top):
    """This function calculates the factors to take into account
    the penetration of the magnetic field into the electrodes (chi) and
    friging field effects (Kf1). W[m] is the width of the microstrip line,
    H[m] is the thickness of the insulator, d_top[m] is the thickness of the top electrode"""

    b = 1.0 + d_top / H
    p = 2.0 * b * b - 1.0 + 2.0 * b * sqrt(b * b - 1.0)

    ra = exp(-(1.0 + pi * W / 2.0 / H + (p + 1.0) / sqrt(p) * arctanh(1.0 / sqrt(p)) + log((p - 1.0) / 4.0 / p)))
    ln_ra = 1.0 + pi * W / 2.0 / H + (p + 1.0) / sqrt(p) * arctanh(1.0 / sqrt(p)) + log((p - 1.0) / 4.0 / p)
    eta = sqrt(p) * (
        pi * W / 2.0 / H + (p + 1.0) / 2.0 / sqrt(p) * (1.0 + log(4.0 / (p - 1.0))) - 2.0 * arctanh(1.0 / sqrt(p))
    )

    rbo = eta + (p + 1.0) / 2.0 * log(eta)
    rb1 = (
        rbo
        - sqrt((rbo - 1.0) * (rbo - p))
        + (p + 1.0) * arctanh(sqrt((rbo - p) / (rbo - 1.0)))
        - 2.0 * sqrt(p) * arctanh(sqrt((rbo - p) / p / (rbo - 1.0)))
        + pi * W * sqrt(p) / 2.0 / H
    )

    if W / H > 5:
        rb = rbo
    else:
        rb = rb1

    Kfo = 2.0 * H / pi / W * (log(2.0 * rbo / ra))
    Kf1 = 2.0 * H / pi / W * (log(2.0 * rb) + ln_ra)

    Ra = (1.0 - ra) * (p - ra)
    Is1 = log((2.0 * p - ra * (p + 1.0) + 2.0 * sqrt(p * Ra)) / ra / (p - 1.0))

    Rb = (rb - 1.0) * (rb - p)
    Is2 = -log((-2.0 * p + rb * (p + 1.0) - 2.0 * sqrt(p * Rb)) / rb / (p - 1.0))

    Rbb = (rb + 1.0) * (rb + p)
    Ig1 = -log((2.0 * p + rb * (p + 1.0) + 2.0 * sqrt(p * Rbb)) / rb / (p - 1.0))

    Raa = (ra + 1.0) * (ra + p)
    Ig2 = log((2.0 * p + ra * (p + 1.0) + 2.0 * sqrt(p * Raa)) / ra / (p - 1.0))

    chi = (Is1 + Is2 + Ig1 + Ig2 + pi) / 2.0 / log(2.0 * rb / ra)

    return (chi, Kf1)


def Zo_s(f, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot):
    """This function calculates the characteristic impedance of the microstrip line
    Here f[GHz] is the frequency, W[m] is the width, E and H[m] are the dielectric constant
    and thickness of the inter-electrode insulator, top(bot)_s12_args[(freq[GHz], sigma1_arr[1/Ohm/m],
    sigma2_arr[1/Ohm/m])] denotes the conductivities of the top and bottom electrodes materials,
    d[m] is the thicknes of the corresponding electrode"""

    (chi, Kf1) = chi_Kf1(W, H, d_top)
    g1 = H / W / Kf1

    Z_top = Imp.Z_film(f, top_s12_args, d_top)
    Z_bot = Imp.Z_film(f, bot_s12_args, d_bot)

    res = (
        120.0
        * pi
        * g1
        / sqrt(E)
        * sqrt(1.0 - 1j * chi * (Z_top + Z_bot) / 2.0 / pi / f / 1e9 / 120.0 / pi / H / sqrt(eps0 * mu0) + 0 * 1j)
    )

    return res


def gamma(f, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot):
    """This function calculates the propagation constant of the microstrip line.
    Arguments are the same as above"""

    (chi, Kf1) = chi_Kf1(W, H, d_top)

    Z_top = Imp.Z_film(f, top_s12_args, d_top)
    Z_bot = Imp.Z_film(f, bot_s12_args, d_bot)

    res = (
        1j
        * 2.0
        * pi
        * f
        * 1e9
        * sqrt(E * eps0 * mu0)
        * sqrt(1.0 - 1j * chi * (Z_top + Z_bot) / 2.0 / pi / f / 1e9 / 120.0 / pi / H / sqrt(eps0 * mu0))
    )

    return res


def M_MSL(f, L, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot):
    """This function calculates the ABCD-matrix of the microstrip line.
    L is the length of the MSL."""

    Zo1 = Zo_s(f, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot)
    gamma1 = gamma(f, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot)

    A = cosh(gamma1 * L)
    B = Zo1 * sinh(gamma1 * L)
    C = 1.0 / Zo1 * sinh(gamma1 * L)
    D = cosh(gamma1 * L)

    res = array([[A, B], [C, D]], dtype=complex)
    return res


def Z_T(f, Z_load, L, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot):
    """Impedance transforming function. Z_load[Ohm] is the load impedance"""

    Zo1 = Zo_s(f, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot)
    gamma1 = gamma(f, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot)

    res = Zo1 * (Z_load + Zo1 * tanh(gamma1 * L)) / (Zo1 + Z_load * tanh(gamma1 * L))

    return res


def Y_T(f, Y_load, L, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot):
    """Conductance transforming function. Y_load[1/Ohm] is the load admittance"""

    Yo1 = 1.0 / Zo_s(f, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot)
    gamma1 = gamma(f, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot)

    res = Yo1 * (Y_load + Yo1 * tanh(gamma1 * L)) / (Yo1 + Y_load * tanh(gamma1 * L))

    return res
