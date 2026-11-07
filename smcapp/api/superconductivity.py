"""Superconductivity-related calculations."""

from __future__ import annotations

from dataclasses import dataclass

from numpy import abs, real, sqrt, tanh
from scipy.integrate import quad

from .complex_integration import ComplexIntegrator

# Fundamental constants (energy in eV)
E_CHARGE = 1.6022e-19
PLANCK_H = 6.62607e-34 / E_CHARGE
BOLTZMANN_KB = 1.38065e-23 / E_CHARGE


@dataclass
class SuperconductingGapCalculator:
    """Calculates superconducting gaps for different models."""

    def n0_v1(self, critical_temperature_k: float, energy_cutoff: float = 20 * BOLTZMANN_KB * 15.0) -> float:
        """Compute the N(0)V parameter for a given critical temperature.

        Args:
            critical_temperature_k: Critical temperature in Kelvin.
            energy_cutoff: Energy cutoff in eV for integration limits.
        """
        func_n0_v1 = lambda x: tanh(x) / x

        res1 = quad(
            func_n0_v1,
            0,
            energy_cutoff / (20 * BOLTZMANN_KB * critical_temperature_k),
            epsabs=1e-12,
            epsrel=1e-12,
            limit=100,
        )
        res2 = quad(
            func_n0_v1,
            energy_cutoff / (20 * BOLTZMANN_KB * critical_temperature_k),
            energy_cutoff / (2 * BOLTZMANN_KB * critical_temperature_k),
            epsabs=1e-12,
            epsrel=1e-12,
            limit=100,
        )
        return res1[0] + res2[0]

    def delta_bcs(
        self, temperature_k: float, critical_temperature_k: float, energy_cutoff: float = 20 * BOLTZMANN_KB * 15.0
    ) -> float:
        """Solve the BCS gap equation iteratively.

        Args:
            temperature_k: Temperature in Kelvin.
            critical_temperature_k: Critical temperature in Kelvin.
            energy_cutoff: Energy cutoff in eV.
        """
        results = [1.76 * BOLTZMANN_KB * critical_temperature_k]
        func1 = lambda energy, temp, gap: tanh(energy / (2.0 * BOLTZMANN_KB * temp)) * real(
            1.0 / sqrt(energy**2 - gap**2 + 0j)
        )

        for _ in range(1, 2000):
            gap = results[-1]
            res1 = (
                gap
                / self.n0_v1(critical_temperature_k, energy_cutoff)
                * quad(func1, 0, gap, args=(temperature_k, gap), limit=50)[0]
            )
            res2 = (
                gap
                / self.n0_v1(critical_temperature_k, energy_cutoff)
                * quad(func1, gap, energy_cutoff, args=(temperature_k, gap), limit=50)[0]
            )
            results.append(res1 + res2)
            if abs(results[-1] - results[-2]) < 0.0001 * results[-1]:
                break

        return results[-1]

    def delta_bcs_approx(self, temperature_k: float, critical_temperature_k: float, delta0: float = -1.0) -> float:
        """BCS tanh approximation for the superconducting gap.

        Args:
            temperature_k: Temperature in Kelvin.
            critical_temperature_k: Critical temperature in Kelvin.
            delta0: Gap at 0 K in eV. If -1, uses 1.76 * kB * Tc.
        """
        if delta0 == -1.0:
            delta0 = 1.76 * BOLTZMANN_KB * critical_temperature_k
        return delta0 * tanh(1.74 * real(sqrt(critical_temperature_k / temperature_k - 1.0 + 0j)))

    def delta_strong_coupling(self, temperature_k: float, critical_temperature_k: float, delta0: float = -1.0) -> float:
        """Strong-coupling approximation for the superconducting gap.

        Args:
            temperature_k: Temperature in Kelvin.
            critical_temperature_k: Critical temperature in Kelvin.
            delta0: Gap at 0 K in eV. If -1, uses 1.76 * kB * Tc.
        """
        if delta0 == -1.0:
            delta0 = 1.76 * BOLTZMANN_KB * critical_temperature_k
        results = [delta0]

        for _ in range(1, 5000):
            results.append(delta0 * tanh((critical_temperature_k / temperature_k) * (results[-1] / delta0)))
            if abs(results[-1] - results[-2]) < 0.000001 * results[-1]:
                break

        return results[-1]


@dataclass
class MattisBardeenCalculator:
    """Calculates complex conductivity using Mattis-Bardeen expressions."""

    integrator: ComplexIntegrator = ComplexIntegrator()

    def sigma1(self, sigma0: float, frequency_ghz: float, temperature_k: float, gap_ev: float) -> complex:
        """Real part of conductivity (sigma1).

        Args:
            sigma0: Normal-state conductivity, 1/(Ohm*m).
            frequency_ghz: Frequency in GHz.
            temperature_k: Temperature in Kelvin.
            gap_ev: Superconducting gap in eV.
        """
        fermi = lambda energy, freq, temp: tanh((energy + PLANCK_H * freq * 1e9) / (2.0 * BOLTZMANN_KB * temp)) - tanh(
            energy / (2.0 * BOLTZMANN_KB * temp)
        )
        gg = (
            lambda energy, freq, temp, gap: (energy * (energy + PLANCK_H * freq * 1e9) + gap * gap)
            / sqrt(energy * energy - gap * gap)
            / sqrt((energy + PLANCK_H * freq * 1e9) * (energy + PLANCK_H * freq * 1e9) - gap * gap)
        )
        func1 = lambda energy, freq, temp, gap: fermi(energy, freq, temp) * gg(energy, freq, temp, gap)

        res1 = self.integrator.complex_integral(
            func1, gap_ev, 2.0 * gap_ev, args=(frequency_ghz, temperature_k, gap_ev)
        )
        res2 = self.integrator.complex_integral(
            func1, 2.0 * gap_ev, 5.0 * gap_ev, args=(frequency_ghz, temperature_k, gap_ev)
        )
        res3 = self.integrator.complex_integral(
            func1, 5.0 * gap_ev, 25.0 * gap_ev, args=(frequency_ghz, temperature_k, gap_ev)
        )
        res4 = self.integrator.complex_integral(
            func1, 25.0 * gap_ev, 1000.0 * gap_ev, args=(frequency_ghz, temperature_k, gap_ev)
        )

        func2 = lambda energy, freq, temp, gap: tanh(
            (energy + PLANCK_H * freq * 1e9) / (2.0 * BOLTZMANN_KB * temp)
        ) * gg(energy, freq, temp, gap)

        if (gap_ev - PLANCK_H * frequency_ghz * 1e9) >= -gap_ev:
            res5 = res6 = 0.0
        else:
            res5 = self.integrator.complex_integral(
                func2,
                (gap_ev - PLANCK_H * frequency_ghz * 1e9),
                -PLANCK_H * frequency_ghz * 1e9 / 2.0,
                args=(frequency_ghz, temperature_k, gap_ev),
            )
            res6 = self.integrator.complex_integral(
                func2,
                -PLANCK_H * frequency_ghz * 1e9 / 2.0,
                -gap_ev,
                args=(frequency_ghz, temperature_k, gap_ev),
            )

        return sigma0 * ((res1 + res2 + res3 + res4) - (res5 + res6)) / (PLANCK_H * frequency_ghz * 1e9)

    def sigma2(self, sigma0: float, frequency_ghz: float, temperature_k: float, gap_ev: float) -> complex:
        """Imaginary part of conductivity (sigma2).

        Args:
            sigma0: Normal-state conductivity, 1/(Ohm*m).
            frequency_ghz: Frequency in GHz.
            temperature_k: Temperature in Kelvin.
            gap_ev: Superconducting gap in eV.
        """
        gg = (
            lambda energy, freq, temp, gap: (energy * (energy + PLANCK_H * freq * 1e9) + gap * gap)
            / sqrt(gap * gap - energy * energy)
            / sqrt((energy + PLANCK_H * freq * 1e9) * (energy + PLANCK_H * freq * 1e9) - gap * gap)
        )
        func2 = lambda energy, freq, temp, gap: tanh(
            (energy + PLANCK_H * freq * 1e9) / (2.0 * BOLTZMANN_KB * temp)
        ) * gg(energy, freq, temp, gap)

        if (gap_ev - PLANCK_H * frequency_ghz * 1e9) < -gap_ev:
            res1 = self.integrator.complex_integral(func2, -gap_ev, 0.0, args=(frequency_ghz, temperature_k, gap_ev))
            res2 = self.integrator.complex_integral(func2, 0.0, gap_ev, args=(frequency_ghz, temperature_k, gap_ev))
        else:
            res1 = self.integrator.complex_integral(
                func2,
                (gap_ev - PLANCK_H * frequency_ghz * 1e9),
                (gap_ev - PLANCK_H * frequency_ghz * 1e9 / 2.0),
                args=(frequency_ghz, temperature_k, gap_ev),
            )
            res2 = self.integrator.complex_integral(
                func2,
                (gap_ev - PLANCK_H * frequency_ghz * 1e9 / 2.0),
                gap_ev,
                args=(frequency_ghz, temperature_k, gap_ev),
            )

        return (res1 + res2) * sigma0 / (PLANCK_H * frequency_ghz * 1e9)

    def sigma(self, sigma0: float, frequency_ghz: float, temperature_k: float, gap_ev: float) -> complex:
        """Complex conductivity sigma1 - i*sigma2."""
        return self.sigma1(sigma0, frequency_ghz, temperature_k, gap_ev) - 1j * self.sigma2(
            sigma0, frequency_ghz, temperature_k, gap_ev
        )
