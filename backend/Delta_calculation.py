# This module allows to calculate the values of the superconducting gap at different temperatures

from numpy import abs, imag, real, sqrt, tanh
from scipy.integrate import quad

e = 1.6022e-19  # electron charge
kB = 1.38065e-23 / e  # Boltzmann constant
h = 6.62607e-34 / e  # Planck's constant

# Function to calculate the N(0)V -- parameter for both BCS-like and non-BCS cases (density of states at Fermi energy multiplied by the coupling potential),


def N0_V_1(Tc, E=20 * kB * 15.0):
    func_N0_V_1 = lambda x: tanh(x) / x

    res1 = quad(func_N0_V_1, 0, E / (20 * kB * Tc), epsabs=10 ** (-12), epsrel=10 ** (-12), limit=100)
    res2 = quad(func_N0_V_1, E / (20 * kB * Tc), E / (2 * kB * Tc), epsabs=10 ** (-12), epsrel=10 ** (-12), limit=100)
    return res1[0] + res2[0]


# Exact value for BCS-gap obtained from solving the integral equation iteratively
def Delta_BCS(T, Tc, E=20 * kB * 15.0):
    res = []
    res.append(1.76 * kB * Tc)
    func1 = lambda E, T, Delta: tanh(E / (2.0 * kB * T)) * real(1.0 / sqrt(E**2 - Delta**2 + 0j))

    for i in range(1, 2000):
        Delta0_1 = res[-1] / N0_V_1(Tc, E) * quad(func1, 0, res[-1], args=(T, res[-1]), limit=50)[0]
        Delta0_2 = res[-1] / N0_V_1(Tc, E) * quad(func1, res[-1], E, args=(T, res[-1]), limit=50)[0]
        res.append(Delta0_1 + Delta0_2)
        if abs(res[-1] - res[-2]) < 0.0001 * res[-1]:
            break
    # returns superconducting gap as a result of calculations in eV
    return res[-1]


# BCS-tanh approximation
def Delta_BCS_approx(T, Tc, Delta0=-1):
    if Delta0 == -1:
        Delta0 = 1.76 * kB * Tc
    # returns superconducting gap as a result of calculations in eV
    return Delta0 * tanh(1.74 * real(sqrt(Tc / T - 1.0 + 0j)))


# Strong-coupling approximate expression
def Delta_str_cpl(T, Tc, Delta0=-1):
    if Delta0 == -1:
        Delta0 = 1.76 * kB * Tc
    res = [
        Delta0,
    ]

    for i in range(1, 5000):
        res.append(Delta0 * tanh((Tc / T) * (res[-1] / Delta0)))
        if abs(res[-1] - res[-2]) < 0.000001 * res[-1]:
            break
        i += 1
    # returns superconducting gap as a result of calculations in eV
    return res[-1]
