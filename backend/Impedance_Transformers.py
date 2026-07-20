"""This module calculates the ABCD-matrix of the step impedance transformers"""

import Microstrip_line as MSL
from numpy import arange, array


def Transf(f, W_start, W_end, dWdL, E, H, top_s12_args, bot_s12_args, d_top, d_bot, dL=1.0 * 1e-6):
    """Function to calculate the matrix of the step impedance transformer.
    'f'[GHz] is frequnecy, W_start[m] and W_end[m] are the start and end widths of the transformer section
    NOTE: (W_start-W_end) % (dWdL*1e-6) should be equal to zero; dWdL is the ratio of the width change per unit length
    E and H[m] are the realltive permittivity and the thickness of the insulator"""

    eps = 0.01 * 1e-6
    if W_start < W_end:
        W_arr = arange(W_start, W_end + eps, dWdL * 1e-6)
    else:
        W_arr = arange(W_end, W_start + eps, dWdL * 1e-6)[::-1]

    res = array([[1.0, 0.0], [0.0, 1.0]], dtype=complex)

    for W in W_arr:
        res = res.dot(MSL.M_MSL(f, dL, W, E, H, top_s12_args, bot_s12_args, d_top, d_bot))

    return res
