"""DC block calculations for slot antenna structures."""

from __future__ import annotations

from dataclasses import dataclass

from numpy import abs as np_abs
from numpy import array, cos, cosh, exp, log, pi, sin, sinh, sqrt, tanh
from scipy.integrate import quad

from .complex_integration import ComplexIntegrator
from .microstrip import MicrostripLineCalculator
from .models import FilmConductivity

ETA0 = 120.0 * pi
EPS0 = 8.8542e-12
MU0 = 4.0 * pi * 1e-7


@dataclass
class DCBlockCalculator:
    """DC block calculator for slot antenna structures."""
    integrator: ComplexIntegrator
    microstrip: MicrostripLineCalculator

    def slot_line(self, frequency_ghz: float, a0: float, b0: float, dielectric_constant: float, thickness_m: float):
        """Calculate slot line characteristic impedance and propagation constant.

        Args:
            frequency_ghz: Frequency in GHz.
            a0: Slot width in meters.
            b0: Slot span in meters.
            dielectric_constant: Relative permittivity.
            thickness_m: Substrate thickness in meters.
        """
        k0 = a0 / b0
        k1 = sinh(pi * a0 / 4.0 / thickness_m) / sinh(pi * b0 / 4.0 / thickness_m)
        k2 = sqrt(1.0 - k0 * k0)
        k3 = sqrt(1.0 - k1 * k1)

        k_arr = (k0, k1, k2, k3)

        ki = []
        func = lambda phi, k: 1.0 / sqrt(1.0 - k * sin(phi) * sin(phi))

        for k in k_arr:
            res = quad(func, 0.0, pi / 2.0, args=(k), epsabs=1.49e-25, limit=100, maxp1=100, limlst=100)
            ki.append(res[0])

        es_eff = 1.0 + (dielectric_constant - 1.0) / 2.0 * ki[2] * ki[1] / ki[0] / ki[3]
        zc = 120.0 * pi / sqrt(es_eff) * ki[0] / ki[2]
        gamma = 2.0 * pi * frequency_ghz * 1e9 * 1j * sqrt(es_eff * EPS0 * MU0)

        return zc, gamma

    def bridge_line(self, frequency_ghz: float, a0: float, b0: float, dielectric_constant: float, thickness_m: float):
        """Calculate bridge line characteristic impedance and propagation constant.

        Args:
            frequency_ghz: Frequency in GHz.
            a0: Slot width in meters.
            b0: Bridge span in meters.
            dielectric_constant: Relative permittivity.
            thickness_m: Substrate thickness in meters.
        """
        k0 = a0 / b0
        k1 = sinh(pi * a0 / 4.0 / thickness_m) / sinh(pi * b0 / 4.0 / thickness_m)
        k2 = sqrt(1.0 - k0 * k0)
        k3 = sqrt(1.0 - k1 * k1)

        k_arr = (k0, k1, k2, k3)

        ki = []
        func = lambda phi, k: 1.0 / sqrt(1.0 - k * sin(phi) * sin(phi))

        for k in k_arr:
            res = quad(func, 0.0, pi / 2.0, args=(k), epsabs=1.49e-25, limit=100, maxp1=100, limlst=100)
            ki.append(res[0])

        es_eff = 1.0 + (dielectric_constant - 1.0) / 2.0 * ki[2] * ki[1] / ki[0] / ki[3]
        zc = 120.0 * pi / sqrt(es_eff) * ki[0] / ki[2]
        gamma = 2.0 * pi * frequency_ghz * 1e9 * 1j * sqrt(es_eff * EPS0 * MU0)

        return zc, gamma

    def dipole_impedance(
        self,
        frequency_ghz: float,
        width_m: float,
        length_m: float,
        length_offset_m: float,
        dielectric_constant: float,
        base_distance_m: float,
        phase: float = -1,
    ) -> complex:
        """Calculate dipole impedance for the DC block structure.

        Args:
            frequency_ghz: Frequency in GHz.
            width_m: Dipole width in meters.
            length_m: Dipole length in meters.
            length_offset_m: Offset between dipoles in meters.
            dielectric_constant: Relative permittivity.
            base_distance_m: Distance between dipoles in meters.
            phase: Mutual coupling phase (+/- 1).
        """
        rd = width_m / 4.0
        e_eff = 0.5 + dielectric_constant / 2.0
        k_eff = sqrt(e_eff * EPS0 * MU0)
        gamma_dcb = 2.0 * pi * frequency_ghz * 1e9 * k_eff

        func = lambda theta: (cos(gamma_dcb * length_m * cos(theta)) - cos(gamma_dcb * length_m)) ** 2 / sin(theta)
        rd_val = 60.0 / sqrt(e_eff) * quad(func, 0.0, pi, epsabs=1.49e-25, limit=100, maxp1=100, limlst=100)[0]

        c_rd = 2.0
        r_d = 120.0 / sqrt(e_eff) * (log(c_rd * length_m / rd) - 1.0)

        rda = rd_val * 0.5 / (sin(gamma_dcb * length_m) ** 2 + (rd_val / r_d * cos(gamma_dcb * length_m)) ** 2)
        xda = (
            r_d
            / 4.0
            * ((rd_val / r_d) ** 2 - 1.0)
            * sin(2.0 * gamma_dcb * length_m)
            / (sin(gamma_dcb * length_m) ** 2 + (rd_val / r_d * cos(gamma_dcb * length_m)) ** 2)
        )
        zda = rda + 1j * xda

        f1 = lambda z: exp(-1j * gamma_dcb * sqrt(base_distance_m**2 + (length_m - z) ** 2)) / sqrt(
            base_distance_m**2 + (length_m - z) ** 2
        )
        f2 = lambda z: exp(-1j * gamma_dcb * sqrt(base_distance_m**2 + (length_m + z) ** 2)) / sqrt(
            base_distance_m**2 + (length_m + z) ** 2
        )
        f3 = lambda z: 2.0 * cos(gamma_dcb * length_m) * exp(-1j * gamma_dcb * sqrt(base_distance_m**2 + z * z)) / sqrt(
            base_distance_m**2 + z * z
        )

        zdm = 1j * 30.0 / sqrt(e_eff)
        func1 = lambda z: sin(gamma_dcb * (length_m - np_abs(z))) * (f1(z) + f2(z) - f3(z))
        zdm = zdm * self.integrator.complex_integral(func1, length_offset_m, length_m)

        return zda + phase * zdm

    def slot_impedance(
        self,
        frequency_ghz: float,
        width_m: float,
        length_m: float,
        length_offset_m: float,
        dielectric_constant: float,
        base_distance_m: float,
        phase: float = -1,
    ) -> complex:
        """Calculate slot impedance using the Babinet principle.

        Args:
            frequency_ghz: Frequency in GHz.
            width_m: Slot width in meters.
            length_m: Slot length in meters.
            length_offset_m: Offset between slots in meters.
            dielectric_constant: Relative permittivity.
            base_distance_m: Distance between slots in meters.
            phase: Mutual coupling phase (+/- 1).
        """
        e_eff = 0.5 + dielectric_constant / 2.0
        return (120.0 * pi) ** 2 / e_eff / 4.0 / self.dipole_impedance(
            frequency_ghz,
            width_m,
            length_m,
            length_offset_m,
            dielectric_constant,
            base_distance_m,
            phase=phase,
        )

    def matrix(
        self,
        frequency_ghz: float,
        slot_width_m: float,
        slot_length_m: float,
        slot_offset_m: float,
        microstrip_width_m: float,
        microstrip_length_m: float,
        substrate_dielectric: float,
        substrate_thickness_m: float,
        insulator_dielectric: float,
        insulator_thickness_m: float,
        top_film: FilmConductivity,
        bot_film: FilmConductivity,
        top_thickness_m: float,
        bot_thickness_m: float,
    ):
        """Calculate the ABCD matrix for the DC block structure.

        Args:
            frequency_ghz: Frequency in GHz.
            slot_width_m: Slot width in meters.
            slot_length_m: Slot length in meters.
            slot_offset_m: Slot offset in meters.
            microstrip_width_m: Microstrip width in meters.
            microstrip_length_m: Microstrip length in meters.
            substrate_dielectric: Substrate relative permittivity.
            substrate_thickness_m: Substrate thickness in meters.
            insulator_dielectric: Insulator relative permittivity.
            insulator_thickness_m: Insulator thickness in meters.
            top_film: Top film conductivity dataset.
            bot_film: Bottom film conductivity dataset.
            top_thickness_m: Top film thickness in meters.
            bot_thickness_m: Bottom film thickness in meters.
        """
        matrices = []

        bridge_width = slot_width_m + 2.0 * microstrip_width_m
        z_bridge, gamma_bridge = self.bridge_line(
            frequency_ghz, slot_width_m, bridge_width, substrate_dielectric, substrate_thickness_m
        )
        z_bridge_eff = z_bridge * tanh(gamma_bridge * slot_width_m)

        matrices.append(array([[1.0, z_bridge_eff / 2.0], [0.0, 1.0]]))

        z_ms = self.microstrip.transform_impedance(
            frequency_ghz,
            1.0e10,
            microstrip_length_m,
            microstrip_width_m,
            insulator_dielectric,
            insulator_thickness_m,
            top_film,
            bot_film,
            top_thickness_m,
            bot_thickness_m,
        )
        matrices.append(array([[1.0, z_ms], [0.0, 1.0]]))

        base_distance = 2.0 * microstrip_width_m + 2.0 * slot_offset_m + 4.0e-6
        z_sa = self.slot_impedance(
            frequency_ghz,
            slot_width_m,
            slot_length_m,
            slot_offset_m,
            substrate_dielectric,
            base_distance,
        )
        matrices.append(array([[1.0, 0.0], [1.0 / z_sa, 1.0]]))

        slot_span = slot_width_m + 2.0 * base_distance
        z_sl, g_sl = self.slot_line(frequency_ghz, slot_width_m, slot_span, substrate_dielectric, substrate_thickness_m)
        matrices.append(array([[cosh(g_sl * slot_width_m), z_sl * sinh(g_sl * slot_width_m)], [1.0 / z_sl * sinh(g_sl * slot_width_m), cosh(g_sl * slot_width_m)]]))

        matrices.append(array([[1.0, 0.0], [1.0 / z_sa, 1.0]]))
        matrices.append(array([[1.0, z_ms], [0.0, 1.0]]))
        matrices.append(array([[1.0, z_bridge_eff / 2.0], [0.0, 1.0]]))

        result = array([[1.0, 0.0], [0.0, 1.0]])
        for matrix in matrices:
            result = result.dot(matrix)

        return result
