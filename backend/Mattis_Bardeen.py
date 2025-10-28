#This program calculates complex conductivity (sigma1 - i*sigma2) of superconductor using the expressions from Mattis-Bardeen theory

import complex_integration as ci

from numpy import real, imag, arange, concatenate, sqrt, tanh

#fundamental constants
#Energy units are presented in eV
e = 1.6022e-19                     #electron charge
h = 6.62607e-34/e                  #Plank constant
kb = 1.38065e-23/e                 #Boltzmann constant

def sigma1(sigma0, f, T, Delta):
    """The function calculates the real part of conductivity -- sigma1. 
       In order to achieve better accurcay and avoid multiple singularities 
       within one integration interval it was divided into parts"""
    
    Fermi = lambda E, f, T: tanh((E+h*f*1e9)/(2.0*kb*T))-tanh(E/(2.0*kb*T))    #Ferm(E)-Ferm(E+hf)
    GG = lambda E, f, T, Delta: (E*(E+h*f*1e9)+Delta*Delta)/sqrt(E*E - Delta*Delta)/sqrt((E+h*f*1e9)*(E+h*f*1e9) - Delta*Delta)    #Densities of states
    func1 = lambda E, f, T, Delta: Fermi(E, f, T)*GG(E, f, T, Delta)    #Product of Fermi and GG
    
    #Contribution to sigma1 of thermally-excited quasiparticles
    res1 = ci.c_integr(func1, Delta, 2.0*Delta, args=(f, T, Delta))
    res2 = ci.c_integr(func1, 2.0*Delta, 5.0*Delta, args=(f, T, Delta))
    res3 = ci.c_integr(func1, 5.0*Delta, 25.0*Delta, args=(f, T, Delta))
    res4 = ci.c_integr(func1, 25.0*Delta, 1000.0*Delta, args=(f, T, Delta))
    
    func2 = lambda E, f, T, Delta: tanh((E+h*f*1e9)/(2.0*kb*T))*GG(E, f, T, Delta)
    
    #Contribution from pair-breaking by high-frequency photons
    if (Delta - h*f*1e9) >= -Delta:
        res5 = res6 = 0.0
    else:
        res5 = ci.c_integr(func2, (Delta-h*f*1e9), -h*f*1e9/2.0, args=(f, T, Delta))
        res6 = ci.c_integr(func2, -h*f*1e9/2.0, -Delta, args=(f, T, Delta))
        
    return sigma0*((res1+res2+res3+res4) - (res5+res6))/(h*f*1e9)

def sigma2(sigma0, f, T, Delta):
    """This function calculates the imaginary part of conductivity 
       (inductive component due to Cooper pairs)"""
    
    GG = lambda E, f, T, Delta: (E*(E + h*f*1e9)+Delta*Delta)/sqrt(Delta*Delta - E*E)/sqrt((E+h*f*1e9)*(E+h*f*1e9) - Delta*Delta)
    func2 = lambda E, f, T, Delta: tanh((E+h*f*1e9)/(2.0*kb*T))*GG(E, f, T, Delta)
    
    if (Delta - h*f*1e9) < -Delta:
        res1 = ci.c_integr(func2, -Delta, 0.0, args=(f, T, Delta))
        res2 = ci.c_integr(func2, 0.0, Delta, args=(f, T, Delta))
    else:
        res1 = ci.c_integr(func2, (Delta-h*f*1e9), (Delta-h*f*1e9/2.0), args=(f, T, Delta))
        res2 = ci.c_integr(func2, (Delta-h*f*1e9/2.0), Delta, args=(f, T, Delta))
        
    return (res1 + res2)*sigma0/(h*f*1e9)

def sigma(sigma0, f, T, Delta):
    return sigma0*(sigma1(f, T, Delta) - 1j*sigma2(f, T, Delta))