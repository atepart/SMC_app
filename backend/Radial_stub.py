"""This module calculates the radial stub input impedance"""

import Microstrip_line as MSL
from numpy import arange, pi


def Y_RAD(f, R_min, R_max, angle, E, H, top_s12_args, bot_s12_args, d_top, d_bot):
    """Function to calculate the conductance of the radial stub.
    'f'[GHz] is frequnecy, R_min[m] and R_max[m] are the outer and inner radii of the stub
    NOTE: (R_max-R_min) %2 should be equal to zero; angle[degrees] denotes the angle of the stub. E and H[m] are
    the realltive permittivity and the thickness of the insulator"""

    dR = 2.0 * 1e-6  # radius step
    ANG = 2.0 * pi / 360.0 * angle

    N_step = R_max / dR

    Z0 = 1.0e10
    Z = Z0

    for r in arange(0.0, R_max - 1e-6, dR)[::-1]:
        W = R_min + ANG * r
        Z = MSL.Z_T(f, Z, dR, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot)

    return 1.0 / Z
