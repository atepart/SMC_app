"""This module calculates the load impedance of the detector based on SIS-junction
   For rather strong signals (which is the case for the FFO-pumped SIS-junction as at some frequency points
   the quasiparticle step on the IVC is close to saturation) 
   the impedance is close to conducted in parallel Rn and C.
   Additional inductance due to perturbation of the current flow in the lines is calculated."""

import Impedance as Imp

from numpy import real, imag, pi, log, sqrt

mu0 = 4.0*pi*1e-7 #permeability of vacuum

def Z_SIS(f, S, RnA, C0, top_s12_args, bot_s12_args, d_top, d_bot, H_ins, Wb=4.0):
    """function to calculate the impedance of the SIS-junction. 'f' [GHz] is the frequency, 
       S[um^2] is the area of the junction, RnA [Ohm*um^2], C0[F/um^2] is the capacitance per unit square, 
       next 4 args refer to the top and bottom electrodes parameters, 
       H_ins[m] is the thickness of the insulator"""
    
    Z0 = 1.0/(1.0/RnA + 1j*2*pi*f*1e9*C0)/S
    
    lambda_f_top = imag(Imp.Z_film(f, top_s12_args, d_top))
    lambda_f_bot = imag(Imp.Z_film(f, bot_s12_args, d_bot))
    L_SIS = (lambda_f_top + lambda_f_bot + 2.0*pi*f*1e9*mu0*H_ins/2.0)*0.5*log(Wb*Wb/S)
    
    Z_SIS = 1j*L_SIS + Z0
    
    return Z_SIS

