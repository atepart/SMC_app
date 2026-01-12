"""Infrastructure implementation for the S21 calculation example."""

from __future__ import annotations

from dataclasses import dataclass

from numpy import arange, array

from aocapp.api import (
    ComplexIntegrator,
    DCBlockCalculator,
    FilmConductivity,
    IOService,
    ImpedanceCalculator,
    ImpedanceTransformerCalculator,
    MattisBardeenCalculator,
    MicrostripLineCalculator,
    RadialStubCalculator,
    ResultsCalculator,
    SISJunctionCalculator,
    SuperconductingGapCalculator,
)
from aocapp.domain.ports import S21Calculator, S21ResultWriter
from aocapp.domain.s21_models import S21Config, S21Result


@dataclass
class S21CalculatorImpl(S21Calculator):
    """S21 calculator that mirrors backend/Test_ABCD_calc.ipynb."""

    gap_calc: SuperconductingGapCalculator
    mb_calc: MattisBardeenCalculator
    impedance: ImpedanceCalculator
    microstrip: MicrostripLineCalculator
    radial_stub: RadialStubCalculator
    transformer: ImpedanceTransformerCalculator
    dcb: DCBlockCalculator
    sis: SISJunctionCalculator
    results: ResultsCalculator

    def calculate(self, config: S21Config) -> S21Result:
        config.validate()

        delta0_top = config.delta0_top_ev if config.delta0_top_ev is not None else self._delta0_from_tc(config.tc_top_k)
        delta0_bot = config.delta0_bot_ev if config.delta0_bot_ev is not None else self._delta0_from_tc(config.tc_bot_k)

        delta_top = self.gap_calc.delta_bcs_approx(config.temperature_k, config.tc_top_k, delta0_top)
        delta_bot = self.gap_calc.delta_bcs_approx(config.temperature_k, config.tc_bot_k, delta0_bot)

        freq_arr = arange(config.film_freq_start_ghz, config.film_freq_stop_ghz, config.film_freq_step_ghz)

        top_film = self._build_film(freq_arr, config.sigma0_top, config.temperature_k, delta_top)
        bot_film = self._build_film(freq_arr, config.sigma0_bot, config.temperature_k, delta_bot)

        h12 = config.h12_m
        e12 = config.e12
        h1 = config.h1_m
        e1 = config.e1
        dw = config.dw_m

        w_slot = config.w_slot_m - dw
        w_ms = config.w_ms_m + dw

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
        )

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
        mex4 = lambda f: m_rad(f).dot(
            self.microstrip.matrix(
                config.f0_ghz,
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

        m_transf_1 = lambda f: self._transformer_matrix(top_film, bot_film, config, f, config.transf_1_w_start_m, config.transf_1_w_end_m, config.transf_1_dwdl_um, e12, h12, config.transf_1_dl_m)
        m_msl_4 = lambda f: self.microstrip.matrix(
            f,
            config.msl_4_len_m,
            config.msl_4_width_m + dw,
            e12,
            h12,
            top_film,
            bot_film,
            config.d_top_m,
            config.d_bot_m,
        )
        m_transf_2 = lambda f: self._transformer_matrix(top_film, bot_film, config, f, config.transf_2_w_start_m, config.transf_2_w_end_m, config.transf_2_dwdl_um, e12, h12, config.transf_2_dl_m)
        m_msl_5 = lambda f: self.microstrip.matrix(
            f,
            config.msl_5_len_m,
            config.msl_5_width_m + dw,
            e12,
            h12,
            top_film,
            bot_film,
            config.d_top_m,
            config.d_bot_m,
        )
        m_transf_3 = lambda f: self._transformer_matrix(top_film, bot_film, config, f, config.transf_3_w_start_m, config.transf_3_w_end_m, config.transf_3_dwdl_um, e12, h12, config.transf_3_dl_m)

        mex3 = lambda f: self.results.group(f, (m_transf_1, m_msl_4, m_transf_2, m_msl_5, m_transf_3))

        m_transf_5 = lambda f: self._transformer_matrix(top_film, bot_film, config, f, config.transf_5_w_start_m, config.transf_5_w_end_m, config.transf_5_dwdl_um, e1, h1, config.transf_5_dl_m)
        m_msl_6 = lambda f: self.microstrip.matrix(
            f,
            config.msl_6_len_m,
            config.msl_6_width_m + dw,
            e1,
            h1,
            top_film,
            bot_film,
            config.d_top_m,
            config.d_bot_m,
        )
        m_transf_6 = lambda f: self._transformer_matrix(top_film, bot_film, config, f, config.transf_6_w_start_m, config.transf_6_w_end_m, config.transf_6_dwdl_um, e1, h1, config.transf_6_dl_m)
        m_msl_7 = lambda f: self.microstrip.matrix(
            f,
            config.msl_7_len_m,
            config.msl_7_width_m + dw,
            e1,
            h1,
            top_film,
            bot_film,
            config.d_top_m,
            config.d_bot_m,
        )
        m_transf_7 = lambda f: self._transformer_matrix(top_film, bot_film, config, f, config.transf_7_w_start_m, config.transf_7_w_end_m, config.transf_7_dwdl_um, e1, h1, config.transf_7_dl_m)
        m_msl_8 = lambda f: self.microstrip.matrix(
            f,
            config.msl_8_len_m,
            config.msl_8_width_m + dw,
            e1,
            h1,
            top_film,
            bot_film,
            config.d_top_m,
            config.d_bot_m,
        )
        m_transf_8 = lambda f: self._transformer_matrix(top_film, bot_film, config, f, config.transf_8_w_start_m, config.transf_8_w_end_m, config.transf_8_dwdl_um, e1, h1, config.transf_8_dl_m)

        mex1 = lambda f: self.results.group(f, (m_transf_5, m_msl_6, m_transf_6, m_msl_7, m_transf_7, m_msl_8, m_transf_8))

        m_total = lambda f: self.results.group(f, (mex4, mex3, m_dcb, mex1))

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
        res = [s21_db(freq) for freq in freq_arr2]

        return S21Result(frequencies_ghz=list(freq_arr2), s21_db=res)

    def _delta0_from_tc(self, critical_temperature_k: float) -> float:
        return 3.67 / 2.0 * 1.38065 / 1.6022 * critical_temperature_k * 1e-4

    def _build_film(self, frequencies_ghz, sigma0, temperature_k, gap_ev) -> FilmConductivity:
        sigma1 = []
        sigma2 = []
        for freq in frequencies_ghz:
            sigma1.append(self.mb_calc.sigma1(sigma0, freq, temperature_k, gap_ev))
            sigma2.append(self.mb_calc.sigma2(sigma0, freq, temperature_k, gap_ev))
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
