"""This module allows to calculate the impedance of the Double Dipole and Slot antenna input impedances.
   Slot antenna serves as the DC_block in the superconducting integrated matching circuits"""

from numpy import pi, sinh, cosh, tanh, sin, cos, sqrt, log, exp, abs, array
from scipy.integrate import quad

import complex_integration as ci
import Microstrip_line as MSL

eta0 = 120.0*pi
eps0 = 8.8542*1e-12
mu0 = 4.0*pi*1e-7

def Z_g_Slot_line(f, a0, b0, E_sub, H_sub):
    """Function to calculate the characteristic impedance and propagation constant
       of the slot line"""
    
    k0 = a0/b0
    k1 = sinh(pi*a0/4.0/H_sub)/sinh(pi*b0/4.0/H_sub)
    k2 = sqrt(1.0 - k0*k0)
    k3 = sqrt(1.0 - k1*k1)
    
    k_arr = (k0, k1, k2, k3)
    
    KI = []
    func = lambda phi, k: 1.0/sqrt(1.0 - k*sin(phi)*sin(phi))
    
    for k in k_arr:
        res = quad(func, 0.0, pi/2.0, args=(k), epsabs = 1.49*10**(-25), limit = 100, maxp1 = 100, limlst = 100)
        KI.append(res[0])
    
    Es_eff = 1.0 + (E_sub - 1.0)/2.0*KI[2]*KI[1]/KI[0]/KI[3]
    Zc = 120.0*pi/sqrt(Es_eff)*KI[0]/KI[2]
    gamma = 2.0*pi*f*1e9*1j*sqrt(Es_eff*eps0*mu0)
    
    return (Zc, gamma)

def Z_g_Bridge_line(f, a0, b0, E_sub, H_sub):
    """Function to calculate the characteristic impedance and propagation constant
       of the slot line"""
    
    k0 = a0/b0
    k1 = sinh(pi*a0/4.0/H_sub)/sinh(pi*b0/4.0/H_sub)
    k2 = sqrt(1.0 - k0*k0)
    k3 = sqrt(1.0 - k1*k1)
    
    k_arr = (k0, k1, k2, k3)
    
    KI = []
    func = lambda phi, k: 1.0/sqrt(1.0 - k*sin(phi)*sin(phi))
    
    for k in k_arr:
        res = quad(func, 0.0, pi/2.0, args=(k), epsabs = 1.49*10**(-25), limit = 100, maxp1 = 100, limlst = 100)
        KI.append(res[0])
    
    Es_eff = 1.0 + (E_sub - 1.0)/2.0*KI[2]*KI[1]/KI[0]/KI[3]
    Zc = 120.0*pi/sqrt(Es_eff)*KI[0]/KI[2]
    gamma = 2.0*pi*f*1e9*1j*sqrt(Es_eff*eps0*mu0)
    
    return (Zc, gamma)

def ZDAm(f, Wd, Ld, Ldo, Ed, D_base, PHASE=-1):
    """Function to calculate the impedance of the dipole antenna"""
    
    #Single Dipole antenna
    Rd = Wd/4.0
    Ed_eff = 0.5 + Ed/2.0
    K_eff = sqrt(Ed_eff*eps0*mu0)
    gamma_DCB = 2.0*pi*f*1e9*K_eff
    
    func = lambda theta: (cos(gamma_DCB*Ld*cos(theta)) - cos(gamma_DCB*Ld))**2/sin(theta)
    RD = 60.0/sqrt(Ed_eff)*quad(func, 0.0, pi, epsabs = 1.49*10**(-25), limit = 100, maxp1 = 100, limlst = 100)[0]
    
    C_rd = 2.0
    rD = 120.0/sqrt(Ed_eff)*(log(C_rd*Ld/Rd) - 1.0)
    
    RDA = RD*0.5/(sin(gamma_DCB*Ld)**2 + (RD/rD*cos(gamma_DCB*Ld))**2)
    XDA = rD/4.0*((RD/rD)**2 - 1.0)*sin(2.0*gamma_DCB*Ld)/(sin(gamma_DCB*Ld)**2 + (RD/rD*cos(gamma_DCB*Ld))**2)
    ZDA = RDA + 1j*XDA
    
    #Mutual impact
    F1 = lambda z: exp(-1j*gamma_DCB*sqrt(D_base**2 + (Ld - z)**2))/sqrt(D_base**2 + (Ld - z)**2)
    F2 = lambda z: exp(-1j*gamma_DCB*sqrt(D_base**2 + (Ld + z)**2))/sqrt(D_base**2 + (Ld + z)**2)
    F3 = lambda z: 2.0*cos(gamma_DCB*Ld)*exp(-1j*gamma_DCB*sqrt(D_base**2 + z*z))/sqrt(D_base**2 + z*z)
    
    ZDm = 1j*30.0/sqrt(Ed_eff)
    func1 = lambda z: sin(gamma_DCB*(Ld - abs(z)))*(F1(z) + F2(z) - F3(z))
    ZDm = ZDm*ci.c_integr(func1, Ldo, Ld)
    
    return (ZDA + PHASE*ZDm)

def ZSA(f, Wd, Ld, Ldo, Ed, D_base, PHASE=-1):
    """Slot antenna impedance calculated from ZDA using the Babinet principle"""
    
    Rd = Wd/4.0
    Ed_eff = 0.5 + Ed/2.0
    
    res = (120.0*pi)**2/Ed_eff/4.0/ZDAm(f, Wd, Ld, Ldo, Ed, D_base, PHASE=-1)
    return res

def M_DCB(f, Ws, Ls, Lso, Wms, Lms, E_sub, H_sub, E_ins, H_ins, top_s12_args, bot_s12_args, d_top, d_bot):
    """Function to calculate the DC-Block ABCD-matrix"""
    
    M_arr = []
    
    b1 = Ws+2.0*Wms
    Z_bridge = Z_g_Bridge_line(f, Ws, b1, E_sub, H_sub)[0]*tanh(Z_g_Bridge_line(f, Ws, b1, E_sub, H_sub)[1]*Ws)
    
    M1 = array([[1.0, Z_bridge/2.0], [0.0, 1.0]])
    M_arr.append(M1)

    Zms = MSL.Z_T(f, 1.0*1e10, Lms, Wms, E_ins, H_ins, top_s12_args, bot_s12_args, d_top, d_bot)
    M2 = array([[1.0, Zms], [0.0, 1.0]])
    M_arr.append(M2)
    
    D_base = 2.0*Wms + 2.0*Lso + 4.0*1e-6
    Z_SA = ZSA(f, Ws, Ls, Lso, E_sub, D_base)
    M3 = array([[1.0, 0.0], [1.0/Z_SA, 1.0]])
    M_arr.append(M3)
    
    b0 = Ws + 2.0*D_base
    Z_sl = Z_g_Slot_line(f, Ws, b0, E_sub, H_sub)[0]
    g_sl = Z_g_Slot_line(f, Ws, b0, E_sub, H_sub)[1]
    M4 = array([[cosh(g_sl*Ws), Z_sl*sinh(g_sl*Ws)], [1.0/Z_sl*sinh(g_sl*Ws), cosh(g_sl*Ws)]])
    M_arr.append(M4)
    
    M5 = array([[1.0, 0.0], [1.0/Z_SA, 1.0]])
    M_arr.append(M5)
    
    M6 = array([[1.0, Zms], [0.0, 1.0]])
    M_arr.append(M6)
    
    M7 = array([[1.0, Z_bridge/2.0], [0.0, 1.0]])
    M_arr.append(M7)
    
    res = array([[1.0, 0.0], [0.0, 1.0]])
    for M in M_arr:
        res=res.dot(M)
    
    return res