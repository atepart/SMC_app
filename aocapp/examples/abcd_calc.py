"""Example usage of the API calculators based on backend/Test_ABCD_calc.ipynb."""

from __future__ import annotations

from typing import Callable

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


def build_film(
    frequencies_ghz,
    sigma0,
    temperature_k,
    gap_ev,
    mb_calc: MattisBardeenCalculator,
) -> FilmConductivity:
    sigma1 = []
    sigma2 = []
    for freq in frequencies_ghz:
        sigma1.append(mb_calc.sigma1(sigma0, freq, temperature_k, gap_ev))
        sigma2.append(mb_calc.sigma2(sigma0, freq, temperature_k, gap_ev))
    return FilmConductivity(frequencies_ghz, sigma1, sigma2)


def main() -> None:
    gap_calc = SuperconductingGapCalculator()
    mb_calc = MattisBardeenCalculator()
    impedance = ImpedanceCalculator()
    microstrip = MicrostripLineCalculator(impedance=impedance)
    radial_stub = RadialStubCalculator(microstrip=microstrip)
    transformer = ImpedanceTransformerCalculator(microstrip=microstrip)
    dcb = DCBlockCalculator(integrator=ComplexIntegrator(), microstrip=microstrip)
    sis = SISJunctionCalculator(impedance=impedance)
    results = ResultsCalculator()
    io_service = IOService()

    temperature_k = 4.2
    tc_top = 9.5
    tc_bot = 9.5
    delta0_top = 3.67 / 2.0 * 1.38065 / 1.6022 * tc_top * 1e-4
    delta0_bot = 3.67 / 2.0 * 1.38065 / 1.6022 * tc_bot * 1e-4

    delta_top = gap_calc.delta_bcs_approx(temperature_k, tc_top, delta0_top)
    delta_bot = gap_calc.delta_bcs_approx(temperature_k, tc_bot, delta0_bot)

    freq_arr = arange(100.0, 1110.0, 20.0)
    sigma0_top = 18.0e6
    sigma0_bot = 18.0e6

    top_film = build_film(freq_arr, sigma0_top, temperature_k, delta_top, mb_calc)
    bot_film = build_film(freq_arr, sigma0_bot, temperature_k, delta_bot, mb_calc)

    d_top = 0.35e-6
    d_bot = 0.20e-6

    h12 = 0.265729e-6
    e12 = 4.34703
    h1 = 0.265729e-6
    e1 = 4.34703
    f0 = 600.0

    dw = 0.5e-6

    w_slot = 4.0e-6 - dw
    l_slot = 50.0e-6
    lso = 4.0e-6
    e_sub = 11.7
    h_sub = 0.35e-3

    w_ms = 9.0e-6 + dw
    l_ms = 45.0e-6

    m_dcb = lambda f: dcb.matrix(
        f,
        w_slot,
        l_slot,
        lso,
        w_ms,
        l_ms,
        e_sub,
        h_sub,
        e12,
        h12,
        top_film,
        bot_film,
        d_top,
        d_bot,
    )

    zrad0 = 50.0
    zrad1 = lambda f: microstrip.transform_impedance(f, zrad0, 65.0e-6, 4.0e-6 + dw, e12, h12, top_film, bot_film, d_top, d_bot)
    y_rad = lambda f: radial_stub.admittance(f, 4.0e-6, 32.0e-6, 120.0, e12, h12, top_film, bot_film, d_top, d_bot)
    zrad2 = lambda f: 1.0 / (2.0 * y_rad(f) + 1.0 / zrad1(f))
    zrad3 = lambda f: microstrip.transform_impedance(f, zrad2(f), 14.0e-6, 4.5e-6 + dw, e12, h12, top_film, bot_film, d_top, d_bot)
    zrad4 = lambda f: microstrip.transform_impedance(f, zrad3(f), 3.0e-6, 6.0e-6 + dw, e12, h12, top_film, bot_film, d_top, d_bot)

    m_rad = lambda f: array([[1.0, 0.0], [1.0 / zrad4(f), 1.0]])

    mex4 = lambda f: m_rad(f).dot(microstrip.matrix(f0, 3.0e-6, 6.0e-6 + dw, e12, h12, top_film, bot_film, d_top, d_bot))

    m_transf_1 = lambda f: transformer.transformer_matrix(f, 8.0e-6 + dw, 20.0e-6 + dw, 4.0, e12, h12, top_film, bot_film, d_top, d_bot, length_step_m=0.0e-6)
    m_msl_4 = lambda f: microstrip.matrix(f, 60.0e-6, 18.0e-6 + dw, e12, h12, top_film, bot_film, d_top, d_bot)
    m_transf_2 = lambda f: transformer.transformer_matrix(f, 18.0e-6 + dw, 6.0e-6 + dw, 4.0, e12, h12, top_film, bot_film, d_top, d_bot, length_step_m=0.0e-6)
    m_msl_5 = lambda f: microstrip.matrix(f, 55.0e-6, 5.0e-6 + dw, e12, h12, top_film, bot_film, d_top, d_bot)
    m_transf_3 = lambda f: transformer.transformer_matrix(f, 4.0e-6 + dw, 10.0e-6 + dw, 1.0, e12, h12, top_film, bot_film, d_top, d_bot, length_step_m=1.5e-6)

    mex3 = lambda f: results.group(f, (m_transf_1, m_msl_4, m_transf_2, m_msl_5, m_transf_3))

    m_transf_5 = lambda f: transformer.transformer_matrix(f, 10.0e-6 + dw, 6.0e-6 + dw, 1.0, e1, h1, top_film, bot_film, d_top, d_bot, length_step_m=2.5e-6)
    m_msl_6 = lambda f: microstrip.matrix(f, 50.0e-6, 11.5e-6 + dw, e1, h1, top_film, bot_film, d_top, d_bot)
    m_transf_6 = lambda f: transformer.transformer_matrix(f, 6.0e-6 + dw, 12.0e-6 + dw, 3.0, e1, h1, top_film, bot_film, d_top, d_bot, length_step_m=0.0e-6)
    m_msl_7 = lambda f: microstrip.matrix(f, 5.0e-6, 18.0e-6 + dw, e1, h1, top_film, bot_film, d_top, d_bot)
    m_transf_7 = lambda f: transformer.transformer_matrix(f, 12.0e-6 + dw, 48.0e-6 + dw, 4.0, e1, h1, top_film, bot_film, d_top, d_bot, length_step_m=0.0e-6)
    m_msl_8 = lambda f: microstrip.matrix(f, 35.0e-6, 44.5e-6 + dw, e1, h1, top_film, bot_film, d_top, d_bot)
    m_transf_8 = lambda f: transformer.transformer_matrix(f, 44.0e-6 + dw, 14.0e-6 + dw, 4.0, e1, h1, top_film, bot_film, d_top, d_bot, length_step_m=1.0e-6)

    mex1 = lambda f: results.group(f, (m_transf_5, m_msl_6, m_transf_6, m_msl_7, m_transf_7, m_msl_8, m_transf_8))

    m_total = lambda f: results.group(f, (mex4, mex3, m_dcb, mex1))

    z_sis: Callable[[float], complex] = lambda f: sis.impedance_sis(
        f, 1.25, 40.0, 8.2e-14, top_film, bot_film, d_top, d_bot, h12, width_um=4.0
    )
    z_ffo: Callable[[float], complex] = lambda f: 0.3
    s21_db: Callable[[float], float] = lambda f: results.s21_db(f, z_ffo, z_sis, m_total)

    res = []
    freq_arr2 = arange(150.0, 751.0, 20.0)
    for freq in freq_arr2:
        res.append(s21_db(freq))

    io_service.write("S21_dB.tab", (freq_arr2, res))


if __name__ == "__main__":
    main()
