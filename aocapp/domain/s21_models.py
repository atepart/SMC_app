"""Domain models for S21 calculations."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class S21Config:
    """Configuration for the S21 calculation example.

    All lengths are in meters, frequencies in GHz, temperatures in Kelvin.
    """

    temperature_k: float = 4.2
    tc_top_k: float = 9.5
    tc_bot_k: float = 9.5
    delta0_top_ev: float | None = 1.45e-3
    delta0_bot_ev: float | None = 1.45e-3
    sigma0_top: float = 18.0e6
    sigma0_bot: float = 18.0e6

    film_freq_start_ghz: float = 20.0
    film_freq_stop_ghz: float = 1110.0
    film_freq_step_ghz: float = 20.0

    d_top_m: float = 0.35e-6
    d_bot_m: float = 0.20e-6

    h12_m: float = 0.465729e-6
    e12: float = 4.28265
    h1_m: float = 1.65729e-7
    e1: float = 4.44084

    f0_ghz: float = 650.0
    dw_m: float = 0.5e-6

    w_slot_m: float = 4.0e-6
    l_slot_m: float = 36.0e-6
    lso_m: float = 8.0e-6
    e_sub: float = 11.7
    h_sub_m: float = 0.35e-3
    w_ms_m: float = 9.0e-6
    l_ms_m: float = 14.0e-6

    zrad0_ohm: float = 50.0
    zrad1_len_m: float = 57.0e-6
    zrad1_width_m: float = 4.0e-6
    radial_r_min_m: float = 4.0e-6
    radial_r_max_m: float = 38.0e-6
    radial_angle_deg: float = 113.0
    zrad3_len_m: float = 4.0e-6
    zrad3_width_m: float = 4.0e-6
    zrad4_len_m: float = 3.0e-6
    zrad4_width_m: float = 6.0e-6

    mex4_len_m: float = 3.0e-6
    mex4_width_m: float = 6.0e-6

    transf_1_w_start_m: float = 6.0e-6
    transf_1_w_end_m: float = 18.0e-6
    transf_1_dwdl_um: float = 6.0
    transf_1_dl_m: float = 0.9e-6
    msl_4_len_m: float = 27.0e-6
    msl_4_width_m: float = 18.0e-6
    transf_2_w_start_m: float = 18.0e-6
    transf_2_w_end_m: float = 4.0e-6
    transf_2_dwdl_um: float = 2.0
    transf_2_dl_m: float = 0.9e-6
    msl_5_len_m: float = 10.0e-6
    msl_5_width_m: float = 4.0e-6
    transf_3_w_start_m: float = 6.0e-6
    transf_3_w_end_m: float = 10.0e-6
    transf_3_dwdl_um: float = 1.0
    transf_3_dl_m: float = 1.2e-6

    transf_4_w_start_m: float = 10.0e-6
    transf_4_w_end_m: float = 6.0e-6
    transf_4_dwdl_um: float = 1.0
    transf_4_dl_m: float = 1.2e-6
    msl_6_len_m: float = 25.0e-6
    msl_6_width_m: float = 4.0e-6
    transf_5_w_start_m: float = 6.0e-6
    transf_5_w_end_m: float = 18.0e-6
    transf_5_dwdl_um: float = 3.0
    transf_5_dl_m: float = 1.2e-6
    msl_7_len_m: float = 24.0e-6
    msl_7_width_m: float = 18.0e-6
    transf_6_w_start_m: float = 18.0e-6
    transf_6_w_end_m: float = 48.0e-6
    transf_6_dwdl_um: float = 3.0
    transf_6_dl_m: float = 1.2e-6
    msl_8_len_m: float = 13.0e-6
    msl_8_width_m: float = 50.0e-6
    transf_7_w_start_m: float = 49.0e-6
    transf_7_w_end_m: float = 14.0e-6
    transf_7_dwdl_um: float = 5.0
    transf_7_dl_m: float = 1.2e-6

    s21_freq_start_ghz: float = 100.0
    s21_freq_stop_ghz: float = 900.0
    s21_freq_step_ghz: float = 5.0

    sis_area_um2: float = 0.8
    sis_rn_area_ohm_um2: float = 32.0
    sis_cap_f_per_um2: float = 8.3e-14
    sis_width_um: float = 4.0
    z_ffo_ohm: float = 0.15

    def validate(self) -> None:
        """Validate core configuration values."""
        errors = []
        if self.temperature_k <= 0:
            errors.append("temperature_k must be > 0")
        if self.film_freq_step_ghz <= 0:
            errors.append("film_freq_step_ghz must be > 0")
        if self.s21_freq_step_ghz <= 0:
            errors.append("s21_freq_step_ghz must be > 0")
        if self.film_freq_start_ghz >= self.film_freq_stop_ghz:
            errors.append("film_freq_start_ghz must be < film_freq_stop_ghz")
        if self.s21_freq_start_ghz >= self.s21_freq_stop_ghz:
            errors.append("s21_freq_start_ghz must be < s21_freq_stop_ghz")
        if self.s21_freq_start_ghz < self.film_freq_start_ghz:
            errors.append("s21_freq_start_ghz must be >= film_freq_start_ghz")
        if self.s21_freq_stop_ghz > self.film_freq_stop_ghz:
            errors.append("s21_freq_stop_ghz must be <= film_freq_stop_ghz")
        if errors:
            raise ValueError("; ".join(errors))


@dataclass(frozen=True)
class S21Result:
    """Results of the S21 calculation."""

    frequencies_ghz: list[float]
    s21_db: list[float]
    log_messages: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.frequencies_ghz)
