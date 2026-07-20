# This module calculates the Surface Impedance of the superconducting films
# which form the electrodes of the superconducting transmission lines

from numpy import imag, pi, real, sqrt, tanh
from scipy.interpolate import interp1d

mu0 = 4.0 * pi * 1e-7


def Z_film(f, film_args, d):
    """This function calculates the surface impedance (per unit square)
    of the superconducting film with conductivity (sigma1 - i*sigma2) and
    thickness 'd'[m] at frequency 'f' [GHz]. Z = sqrt(...)*coth(...)
    sigma1 and sigma2 are the tuples (frequency_array, sigma1(2)_array)
    Z == -1 means bulk case"""

    (freq_arr, sigma1, sigma2) = film_args
    s1 = interp1d(freq_arr, sigma1)  # interpolation of 'sigma1' data points
    s2 = interp1d(freq_arr, sigma2)  # interpolation of 'sigma2' data points

    sigma = lambda f: (s1(f) - 1j * s2(f))

    res = sqrt(1j * 2.0 * pi * f * 1e9 * mu0 / sigma(f) + 0 * 1j) / tanh(
        sqrt(1j * 2.0 * pi * f * 1e9 * mu0 * sigma(f) + 0 * 1j) * d
    )
    return res


def Z_normal(f, sigma0, d, tau=0):
    """Function to calculate the surface impedance per square of the normal metal films"""

    sigma = sigma0 / (1.0 + 1j * 2.0 * pi * f * 1e9 * tau)
    res = sqrt(1j * 2.0 * pi * f * 1e9 * mu0 / sigma + 0 * 1j) / tanh(
        sqrt(1j * 2.0 * pi * f * 1e9 * mu0 * sigma + 0 * 1j) * d
    )
    return res


def Z_datasets(film_args, d, name):
    """Function to generate the datasets for 3D simulators (Ansys HFSS)
    Writes the real (R) and imaginary (X) parts of the impedance
    to two Re(Im)__name__.tab files.
    Formulae take into account mutual impedance of the two sheets of the bottom and top surface of the films"""

    R_dataset = []
    X_dataset = []

    (freq_arr, sigma1_arr, sigma2_arr) = film_args
    k = 0
    for freq in freq_arr:
        sigma = sigma1_arr[k] - 1j * sigma2_arr[k]
        Z1 = sqrt(1j * 2.0 * pi * freq * 1e9 * mu0 / sigma + 0 * 1j) / tanh(
            sqrt(1j * 2.0 * pi * freq * 1e9 * mu0 * sigma + 0 * 1j) * d
        )
        res = Z1 * (
            1.0
            - 1j * pi * freq * 1e9 * mu0 * d / Z1
            + sqrt(1.0 + (1j * pi * freq * 1e9 * mu0 * d / Z1) * (1j * pi * freq * 1e9 * mu0 * d / Z1))
        )
        R_dataset.append(real(res))
        X_dataset.append(imag(res))
        k += 1
    # Writing resistance per unit square
    filename = "Re_" + name + ".tab"
    file1 = open(filename, "w")
    k = 0
    for freq in freq_arr:
        file1.write(str(freq) + "\t" + str(R_dataset[k]) + "\n")
        k += 1
    file1.close()

    # Writing reactance per unit square
    filename = "Im_" + name + ".tab"
    file1 = open(filename, "w")
    k = 0
    for freq in freq_arr:
        file1.write(str(freq) + "\t" + str(X_dataset[k]) + "\n")
        k += 1
    file1.close()
