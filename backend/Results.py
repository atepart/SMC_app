# The module to calculate the power and group the elements together.

from numpy import abs, array, imag, log10, real, sqrt


def group(f, M_arr):
    """This function multiplies the matrices of the elements groupping them together
    in order to simplify calculations. M_arr is the tuple of matrix functions"""

    res = array([[1.0, 0.0], [0.0, 1.0]])
    for M in M_arr:
        res = res.dot(M(f))

    return res


def S21_dB(f, Z_gen, Z_load, M):
    """Function to calculate the ratio of generated power to detected power in dB"""

    R_load = real(Z_load(f))
    R_gen = real(Z_gen(f))

    A = M(f)[0][0] * Z_gen(f) / sqrt(R_load * R_gen)
    B = M(f)[0][1] * 1.0 / sqrt(R_load * R_gen)
    C = M(f)[1][0] * Z_load(f) * Z_gen(f) / sqrt(R_load * R_gen)
    D = M(f)[1][1] * Z_load(f) / sqrt(R_load * R_gen)

    S21 = 4.0 / abs(A + B + C + D) ** 2

    S21_dB = 10.0 * log10(S21)

    return S21_dB
