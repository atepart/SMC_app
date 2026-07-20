# module to evaluate numerically the integrals from complex-valued functions of real-valued variables

from numpy import imag, real
from scipy.integrate import quad


def real_func(x, func, args=()):
    return real(func(x, *args))


def imag_func(x, func, args=()):
    return imag(func(x, *args))


def real_integral(func, a, b, args=(), **kwargs):
    def real_f(x, args=()):
        return real_func(x, func, args)

    return quad(real_f, a, b, (args,), epsabs=1.49 * 10 ** (-25), limit=100, maxp1=100, limlst=100, **kwargs)


def imag_integral(func, a, b, args=(), **kwargs):
    def imag_f(x, args=()):
        return imag_func(x, func, args)

    return quad(
        imag_f, a, b, (args,), full_output=0, epsabs=1.49 * 10 ** (-25), limit=100, maxp1=100, limlst=100, **kwargs
    )


def c_integr(func, a, b, args=(), **kwargs):
    """Calculates the definite integral from function 'func' along the interval [a, b] of the real axis"""
    result_r = real_integral(func, a, b, args, **kwargs)
    result_im = imag_integral(func, a, b, args, **kwargs)
    return result_r[0] + 1j * result_im[0]
