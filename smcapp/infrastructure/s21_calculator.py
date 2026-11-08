"""Infrastructure implementation for the S21 calculation example."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass

from numpy import arange, array
from scipy.integrate import IntegrationWarning

from smcapp.api import (
    ComplexIntegrator,
    DCBlockCalculator,
    FilmConductivity,
    ImpedanceCalculator,
    ImpedanceTransformerCalculator,
    IOService,
    MattisBardeenCalculator,
    MicrostripLineCalculator,
    RadialStubCalculator,
    ResultsCalculator,
    SISJunctionCalculator,
    SuperconductingGapCalculator,
)
from smcapp.domain.circuit import TransformerSection
from smcapp.domain.ports import S21Calculator, S21ResultWriter
from smcapp.domain.s21_models import S21Config, S21Result


@dataclass
class S21CalculatorImpl(S21Calculator):
    """Assemble the legacy superconducting circuit as an ABCD network.

    The matrix is multiplied detector-to-FFO as
    ``Mex4 · Mex3 · M_DCB · Mex2 · Mex1``.  ``Mex1``/``Mex2`` match the
    low-impedance FFO to the slot-antenna DC break, ``Mex3`` continues the
    transformation after the galvanic break, and ``Mex4`` contains the radial
    shunt and SIS-side tuning line.  The terminal impedances are the FFO source
    ``Zffo`` and the frequency-dependent SIS load ``Zsis``.

    Values stay in the units used by ``backend/main.py``: GHz, metres, eV,
    Ω·µm², F/µm² and dimensionless relative permittivity.  Presentation-only
    conversions such as pF/µm² are reversed before this class is called.
    """

    gap_calc: SuperconductingGapCalculator
    mb_calc: MattisBardeenCalculator
    impedance: ImpedanceCalculator
    microstrip: MicrostripLineCalculator
    radial_stub: RadialStubCalculator
    transformer: ImpedanceTransformerCalculator
    dcb: DCBlockCalculator
    sis: SISJunctionCalculator
    results: ResultsCalculator

    def calculate(self, config: S21Config, progress_callback: Callable[[str], None] | None = None) -> S21Result:
        """Calculate transducer ``S21`` for every requested LO frequency.

        ``alpha_top`` and ``alpha_bot`` supply the correction from the
        2026-07-07 Mathcad correspondence through
        ``2*Delta0 = alpha*kB*Tc``.  The resulting gaps feed Mattis–Bardeen
        conductivity tables, which in turn provide the complex surface
        impedances used by every microstrip, transformer, DC-block and SIS
        element.

        The proposed ``t_prox`` anodization capacitance is intentionally not
        present: it is a separate future parallel branch and no authoritative
        Mathcad expression/value was supplied with issue #4.
        """
        config.validate()
        log_messages: list[str] = []

        def log(message: str) -> None:
            log_messages.append(message)
            if progress_callback is not None:
                progress_callback(message)

        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always", IntegrationWarning)

            # Zero-temperature film gaps.  This is the specific alpha factor
            # missing from the earlier worksheet version mentioned by Fedor.
            delta0_top = self._delta0_from_alpha_tc(config.alpha_top, config.tc_top_k)
            delta0_bot = self._delta0_from_alpha_tc(config.alpha_bot, config.tc_bot_k)

            log("Mirroring backend/main.py configuration.")
            log("Using strong-coupling approximation for superconducting gaps.")
            log(f"EL1 gap inferred from alpha={config.alpha_top:.3f} and Tc={config.tc_top_k:.3f} K.")
            log(f"EL2 gap inferred from alpha={config.alpha_bot:.3f} and Tc={config.tc_bot_k:.3f} K.")

            delta_top = self.gap_calc.delta_strong_coupling(config.temperature_k, config.tc_top_k, delta0_top)
            delta_bot = self.gap_calc.delta_strong_coupling(config.temperature_k, config.tc_bot_k, delta0_bot)
            log(f"Delta_top = {delta_top:.9e} eV")
            log(f"Delta_bot = {delta_bot:.9e} eV")

            freq_arr = arange(config.film_freq_start_ghz, config.film_freq_stop_ghz, config.film_freq_step_ghz)
            log(
                f"Building film conductivity tables on {len(freq_arr)} points "
                f"from {config.film_freq_start_ghz:g} to {config.film_freq_stop_ghz - config.film_freq_step_ghz:g} GHz."
            )

            top_film = self._build_film(freq_arr, config.sigma0_top, config.temperature_k, delta_top, log, "EL1")
            bot_film = self._build_film(freq_arr, config.sigma0_bot, config.temperature_k, delta_bot, log, "EL2")

            h12 = config.h12_m
            e12 = config.e12
            h1 = config.h1_m
            e1 = config.e1
            dw = config.dw_m

            # Fabrication correction applies with opposite sign to the etched
            # slot and deposited microstrip, exactly as in the legacy model.
            w_slot = config.w_slot_m - dw
            w_ms = config.w_ms_m + dw

            # Mdcb: symmetric seven-factor slot-antenna two-port.  It transfers
            # RF while keeping the FFO and detector galvanically isolated.
            m_dcb = lambda f: self.dcb.matrix(
                f,
                w_slot,
                config.l_slot_m,
                config.lso_m,
                w_ms,
                config.l_ms_m,
                config.e_sub,
                config.h_sub_m,
                e12,
                h12,
                top_film,
                bot_film,
                config.d_top_m,
                config.d_bot_m,
                config.dc_gap_m,
            )

            # Mrad/MLsis: transform the nominal Zrad0, add two identical radial
            # shunt admittances, then tune the result with two MSL sections.
            zrad1 = lambda f: self.microstrip.transform_impedance(
                f,
                config.zrad0_ohm,
                config.zrad1_len_m,
                config.zrad1_width_m + dw,
                e12,
                h12,
                top_film,
                bot_film,
                config.d_top_m,
                config.d_bot_m,
            )
            y_rad = lambda f: self.radial_stub.admittance(
                f,
                config.radial_r_min_m,
                config.radial_r_max_m,
                config.radial_angle_deg,
                e12,
                h12,
                top_film,
                bot_film,
                config.d_top_m,
                config.d_bot_m,
            )
            zrad2 = lambda f: 1.0 / (2.0 * y_rad(f) + 1.0 / zrad1(f))
            zrad3 = lambda f: self.microstrip.transform_impedance(
                f,
                zrad2(f),
                config.zrad3_len_m,
                config.zrad3_width_m + dw,
                e12,
                h12,
                top_film,
                bot_film,
                config.d_top_m,
                config.d_bot_m,
            )
            zrad4 = lambda f: self.microstrip.transform_impedance(
                f,
                zrad3(f),
                config.zrad4_len_m,
                config.zrad4_width_m + dw,
                e12,
                h12,
                top_film,
                bot_film,
                config.d_top_m,
                config.d_bot_m,
            )

            m_rad = lambda f: array([[1.0, 0.0], [1.0 / zrad4(f), 1.0]])
            # Mex04 = M_RAD(f)·M_MSL(f): like every other element, the short
            # SIS-side line is evaluated at the sweep frequency (Mathcad HD35
            # worksheets; legacy backend/main.py fixed it at f0 = 650 GHz).
            mex4 = lambda f: m_rad(f).dot(
                self.microstrip.matrix(
                    f,
                    config.mex4_len_m,
                    config.mex4_width_m + dw,
                    e12,
                    h12,
                    top_film,
                    bot_film,
                    config.d_top_m,
                    config.d_bot_m,
                )
            )

            # Mex1/Mex2/Mex3 are lists in drawing order (FFO -> SIS); the
            # network is multiplied detector-to-FFO, so each list is reversed:
            # Mex3 = Mex03[last] ... Mex03[first] · corner 9, Mex2 = corner 7 ·
            # Mex02[last] ... Mex02[first], Mex1 = Mex01[last] ... Mex01[first].
            # Mex1 uses the E1/H1 dielectric stack, the others E12/H12.
            def section_matrix(element, dielectric, thickness):
                if isinstance(element, TransformerSection):
                    # Backend widths run from the SIS side (start) to the FFO side (end).
                    return lambda f: self._transformer_matrix(
                        top_film,
                        bot_film,
                        config,
                        f,
                        element.w2_m,
                        element.w1_m,
                        element.n_um,
                        dielectric,
                        thickness,
                        element.dl_m,
                    )
                return lambda f: self.microstrip.matrix(
                    f,
                    element.length_m,
                    element.width_m + dw,
                    dielectric,
                    thickness,
                    top_film,
                    bot_film,
                    config.d_top_m,
                    config.d_bot_m,
                )

            def cascade(elements, dielectric, thickness):
                matrices = tuple(section_matrix(element, dielectric, thickness) for element in reversed(elements))
                return lambda f: self.results.group(f, matrices)

            mex3 = cascade((config.corner_right, *config.mex03), e12, h12)
            mex2 = cascade((*config.mex02, config.corner_left), e12, h12)
            mex1 = cascade(config.mex01, e1, h1)

            log("Assembling network: Mex4 -> Mex3 -> M_DCB -> Mex2 -> Mex1.")
            m_total = lambda f: self.results.group(f, (mex4, mex3, m_dcb, mex2, mex1))

            # Terminal load: Rn and C0 in parallel, divided by junction area,
            # plus the kinetic/geometric inductive correction of the leads.
            z_sis = lambda f: self.sis.impedance_sis(
                f,
                config.sis_area_um2,
                config.sis_rn_area_ohm_um2,
                config.sis_cap_f_per_um2,
                top_film,
                bot_film,
                config.d_top_m,
                config.d_bot_m,
                h12,
                width_um=config.sis_width_um,
            )
            z_ffo = lambda f: config.z_ffo_ohm
            s21_db = lambda f: self.results.s21_db(f, z_ffo, z_sis, m_total)

            freq_arr2 = arange(config.s21_freq_start_ghz, config.s21_freq_stop_ghz, config.s21_freq_step_ghz)
            log(
                f"Sweeping {len(freq_arr2)} S21 points from "
                f"{config.s21_freq_start_ghz:g} to {config.s21_freq_stop_ghz - config.s21_freq_step_ghz:g} GHz."
            )

            res = []
            for index, freq in enumerate(freq_arr2, start=1):
                res.append(s21_db(freq))
                if index % 5 == 0 or index == len(freq_arr2):
                    log(f"{index} of {len(freq_arr2)} frequency points completed")

        warning_messages = []
        for warning_item in caught_warnings:
            if issubclass(warning_item.category, IntegrationWarning):
                message = f"IntegrationWarning: {warning_item.message}"
                if message not in warning_messages:
                    warning_messages.append(message)

        if warning_messages:
            log("scipy.integrate emitted warnings during quadrature.")
            log_messages.extend(warning_messages)
        else:
            log("No scipy.integrate warnings were emitted.")

        return S21Result(frequencies_ghz=list(freq_arr2), s21_db=res, log_messages=log_messages)

    @staticmethod
    def _delta0_from_alpha_tc(alpha: float, critical_temperature_k: float) -> float:
        """Return ``Delta0`` in eV from ``2*Delta0 = alpha*kB*Tc``.

        ``1.38065/1.6022*1e-4`` is Boltzmann's constant in eV/K written with
        the same rounded constants as the legacy backend.  For alpha=3.54 and
        Tc=9.5 K this gives about 1.45 meV, preserving the old default while
        making the documented alpha dependence effective.
        """
        return alpha / 2.0 * 1.38065 / 1.6022 * critical_temperature_k * 1e-4

    def _build_film(
        self,
        frequencies_ghz,
        sigma0,
        temperature_k,
        gap_ev,
        log: Callable[[str], None],
        label: str,
    ) -> FilmConductivity:
        sigma1 = []
        sigma2 = []
        total = len(frequencies_ghz)
        for index, freq in enumerate(frequencies_ghz, start=1):
            sigma1.append(self.mb_calc.sigma1(sigma0, freq, temperature_k, gap_ev))
            sigma2.append(self.mb_calc.sigma2(sigma0, freq, temperature_k, gap_ev))
            if index % 5 == 0 or index == total:
                log(f"{label} conductivity table: {index} of {total} frequency points completed")
        return FilmConductivity(frequencies_ghz, sigma1, sigma2)

    def _transformer_matrix(
        self,
        top_film: FilmConductivity,
        bot_film: FilmConductivity,
        config: S21Config,
        frequency_ghz: float,
        w_start_m: float,
        w_end_m: float,
        dwdl_um: float,
        dielectric: float,
        thickness_m: float,
        dl_m: float,
    ):
        """Build one stepped MSL transformer with the common width correction.

        ``w_start_m``/``w_end_m`` identify the physical element endpoints,
        ``dwdl_um`` controls the discrete width slices, and ``dl_m`` is the
        longitudinal length of every slice.  The film and dielectric arguments
        select the stack belonging to that portion of the circuit.
        """
        return self.transformer.transformer_matrix(
            frequency_ghz,
            w_start_m + config.dw_m,
            w_end_m + config.dw_m,
            dwdl_um,
            dielectric,
            thickness_m,
            top_film,
            bot_film,
            config.d_top_m,
            config.d_bot_m,
            length_step_m=dl_m,
        )


@dataclass
class S21FileWriter(S21ResultWriter):
    """Writes S21 results to a tab-separated file."""

    io_service: IOService

    def write(self, path: str, result: S21Result) -> None:
        self.io_service.write(path, (result.frequencies_ghz, result.s21_db))


def build_default_s21_calculator() -> S21CalculatorImpl:
    """Convenience factory for wiring the default S21 calculator."""

    gap_calc = SuperconductingGapCalculator()
    mb_calc = MattisBardeenCalculator()
    impedance = ImpedanceCalculator()
    microstrip = MicrostripLineCalculator(impedance=impedance)
    radial_stub = RadialStubCalculator(microstrip=microstrip)
    transformer = ImpedanceTransformerCalculator(microstrip=microstrip)
    dcb = DCBlockCalculator(integrator=ComplexIntegrator(), microstrip=microstrip)
    sis = SISJunctionCalculator(impedance=impedance)
    results = ResultsCalculator()

    return S21CalculatorImpl(
        gap_calc=gap_calc,
        mb_calc=mb_calc,
        impedance=impedance,
        microstrip=microstrip,
        radial_stub=radial_stub,
        transformer=transformer,
        dcb=dcb,
        sis=sis,
        results=results,
    )
