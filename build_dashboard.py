"""Rebuild the BIO-INTEL-MOB KPI dashboard.

Usage (from the KPI_dashboard folder):  python3 build_dashboard.py
Optional: python3 build_dashboard.py <data_root> [<fallback_data_root>]
Default data roots: ../duomenys and ../Vilnius_KPI_duomenys/duomenys
"""
import os, subprocess, sys, json
here = os.path.dirname(os.path.abspath(__file__))
root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, '..', 'duomenys')
alt = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, '..', 'Vilnius_KPI_duomenys', 'duomenys')
js = os.path.join(here, 'kpi_data.json')
subprocess.run([sys.executable, os.path.join(here, 'build_data.py'), root, js, alt], check=True)
tpl = open(os.path.join(here, 'template.html'), encoding='utf-8').read()
data = open(js, encoding='utf-8').read().replace('</', '<\\/')
out = os.path.join(here, 'BIO_INTEL_MOB_KPI_Dashboard.html')
open(out, 'w', encoding='utf-8').write(tpl.replace('/*__DATA__*/null', data))
print('written', out)
