"""This is the example of calculation of the superconducting integrated structure.
   It involves superconducting microstrip lines, step impedance transformers, SIS-junction,
   radial stub and DC-Block based on slot antenna.
   In-built method allows to calculate the surface impedance of the superconducting films
   using Mattis-Bardeen expressions.
"""

from numpy import arange, array

import in_output as IO
import Delta_calculation as DC
import Mattis_Bardeen as MB
import Impedance as Imp
import Microstrip_line as MSL
import SIS_junction as SIS
import Radial_stub as RST
import Impedance_Transformers as ITR
import DC_Block as DCB
import Results as RES

#Calculation of the superconducting energy gap
Delta0_top = 1.45e-3 #eV
Delta0_bot = 1.45e-3 #eV
T = 4.2 #K
Tc_top = 9.5 #K
Tc_bot = 9.5 #K

Delta_top = DC.Delta_str_cpl(T, Tc_top, Delta0_top)
Delta_bot = DC.Delta_str_cpl(T, Tc_bot, Delta0_bot)
print("Delta_top = " + str(Delta_top) + " eV")

#Calculations of the top and bottom electrodes conductivities
freq_arr = arange(20.0, 1110.0, 20.0)

sigma0_top = 18.0e6 #1/(Ohm*m)
sigma0_bot = 18.0e6 #1/(Ohm*m)

sigma1_top = []
sigma2_top = []
sigma1_bot = []
sigma2_bot = []

for freq in freq_arr:
    sigma1_top.append(MB.sigma1(sigma0_top, freq, T, Delta_top))
    sigma2_top.append(MB.sigma2(sigma0_top, freq, T, Delta_top))
    sigma1_bot.append(MB.sigma1(sigma0_bot, freq, T, Delta_bot))
    sigma2_bot.append(MB.sigma2(sigma0_bot, freq, T, Delta_bot))

#Transition to the surface impedance from conductivities
d_top = 0.35e-6 #m
d_bot = 0.20e-6 #m

Z_top = []
Z_bot = []

for freq in freq_arr:
    Z_top.append(Imp.Z_film(freq, (freq_arr, sigma1_top, sigma2_top), d_top))
    Z_bot.append(Imp.Z_film(freq, (freq_arr, sigma1_bot, sigma2_bot), d_bot))

top_s12_args = (freq_arr, sigma1_top, sigma2_top)
bot_s12_args = (freq_arr, sigma1_bot, sigma2_bot)

print("Impedance of the top film at 650 GHz is equal to " + str(Imp.Z_film(650, (freq_arr, sigma1_top, sigma2_top), d_top)))

#The parameters of the insulator
H12 = 0.465729e-6
E12 = 4.28265
H1 = 1.65729e-7
E1 = 4.44084
f0 = 650

#DC-block (DCB) matrix calculations
W_slot = 3.5*1e-6
L_slot = 36*1e-6
Lso = 8.0*1e-6
E_sub = 11.7
H_sub = 0.35*1e-3

DW = 0.5*1e-6

W_ms = 9.5*1e-6
L_ms = 14.0*1e-6
M_DCB = lambda f:DCB.M_DCB(f, W_slot, L_slot, Lso, W_ms, L_ms, E_sub, H_sub, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot)

#radial stub Matrix calculation
Zrad0 = 50.0 #
Zrad1 = lambda f: MSL.Z_T(f, Zrad0, 57.0e-6, 4.0e-6 + DW, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot)
Y_RAD = lambda f: RST.Y_RAD(f, 4.0e-6, 38.0e-6, 113.0, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot)
Zrad2 = lambda f: 1.0/(2.0*Y_RAD(f) + 1.0/Zrad1(f))
Zrad3 = lambda f: MSL.Z_T(f, Zrad2(f), 4.0e-6, 4.0e-6 + DW, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot)
Zrad4 = lambda f: MSL.Z_T(f, Zrad3(f), 3.0e-6, 6.0e-6 + DW, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot)
M_RAD = lambda f: array([[1.0, 0.0], [1.0/Zrad4(f), 1.0]])

#Modelling of the whole structure
Mex4 = lambda f: M_RAD(f).dot(MSL.M_MSL(f0, 3.0*1e-6, 6.0*1e-6+DW, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot)) 


M_transf_1 = lambda f: ITR.Transf(f, 6.0*1e-6+DW, 18.0*1e-6+DW, 6.0, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot, dL = 0.9e-6)
M_MSL_4    = lambda f: MSL.M_MSL(f, 27.0e-6, 18.0e-6+DW, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot)
M_transf_2 = lambda f: ITR.Transf(f, 18.0*1e-6+DW, 4.0*1e-6+DW, 2.0, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot, dL=0.9e-6)
M_MSL_5    = lambda f: MSL.M_MSL(f, 10.0e-6, 4.0e-6+DW, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot)
M_transf_3 = lambda f: ITR.Transf(f, 6.0*1e-6+DW, 10.0*1e-6+DW, 1.0, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot, dL=1.2e-6)

Mex3 = lambda f: RES.group(f, (M_transf_1, M_MSL_4, M_transf_2, M_MSL_5, M_transf_3))


M_transf_4 = lambda f: ITR.Transf(f, 10.0*1e-6+DW, 6.0*1e-6+DW, 1.0, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot, dL=1.2e-6)
M_MSL_6    = lambda f: MSL.M_MSL(f, 25.0e-6, 4.0e-6+DW, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot)
M_transf_5 = lambda f: ITR.Transf(f, 6.0*1e-6+DW, 18.0*1e-6+DW, 3.0, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot, dL=1.2e-6)
M_MSL_7    = lambda f: MSL.M_MSL(f, 24.0e-6, 18.0e-6+DW, E12, H12, top_s12_args, bot_s12_args, d_top, d_bot)

Mex2 = lambda f: RES.group(f, (M_transf_4, M_MSL_6, M_transf_5, M_MSL_7))


M_transf_6 = lambda f: ITR.Transf(f, 18.0*1e-6+DW, 48.0*1e-6+DW, 3.0, E1, H1, top_s12_args, bot_s12_args, d_top, d_bot, dL=1.2e-6)
M_MSL_8    = lambda f: MSL.M_MSL(f, 13.0e-6, 50.0e-6+DW, E1, H1, top_s12_args, bot_s12_args, d_top, d_bot)
M_transf_7 = lambda f: ITR.Transf(f, 49.0*1e-6+DW, 14.0*1e-6+DW, 5.0, E1, H1, top_s12_args, bot_s12_args, d_top, d_bot, dL=1.2e-6)

Mex1 = lambda f: RES.group(f, (M_transf_6, M_MSL_8, M_transf_7))

#Matrix of the whole structure
M_total = lambda f: RES.group(f, (Mex4, Mex3, M_DCB, Mex2, Mex1))


#S21-parameter of the structure
Zsis = lambda f: SIS.Z_SIS(f, 0.8, 32.0, 8.3e-14, top_s12_args, bot_s12_args, 0.35e-6, 0.2e-6, H12)
Zffo = lambda f: 0.15
S21_dB = lambda f: RES.S21_dB(f, Zffo, Zsis, M_total)

print("Calculation of the test superconducting structure")

res = []
freq_arr2 = arange(100.0, 900.0, 5.0)
k=0
for freq in freq_arr2:
    res.append(S21_dB(freq))
    k+=1
    if k%5 == 0:
        print(str(k) + " of " + str(len(freq_arr2)) + " frequency points completed")
        
IO.writer("S21_dB.tab", (freq_arr2, res))

