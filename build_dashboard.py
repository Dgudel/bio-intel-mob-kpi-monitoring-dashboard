"""Rebuild the BIO-INTEL-MOB KPI dashboard (index.html + kpi_data.json).

Usage:  python3 build_dashboard.py [<data_root> [<fallback_data_root>]]
Default data roots: ./data/duomenys and ./data/Vilnius_KPI_duomenys/duomenys when run in the
GitHub repo, otherwise ../duomenys and ../Vilnius_KPI_duomenys/duomenys (Dropbox layout).
"""
import os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
base = os.path.join(here, 'data') if os.path.isdir(os.path.join(here, 'data', 'duomenys')) else os.path.join(here, '..')
root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, 'duomenys')
alt = sys.argv[2] if len(sys.argv) > 2 else os.path.join(base, 'Vilnius_KPI_duomenys', 'duomenys')
js = os.path.join(here, 'kpi_data.json')
subprocess.run([sys.executable, os.path.join(here, 'build_data.py'), root, js, alt], check=True)
tpl = open(os.path.join(here, 'template.html'), encoding='utf-8').read()
data = open(js, encoding='utf-8').read().replace('</', '<\\/')
html = tpl.replace('/*__DATA__*/null', data)
open(os.path.join(here, 'index.html'), 'w', encoding='utf-8').write(html)  # GitHub Pages entry point
if base != os.path.join(here, 'data'):  # Dropbox copy keeps its descriptive file name too
    open(os.path.join(here, 'BIO_INTEL_MOB_KPI_Dashboard.html'), 'w', encoding='utf-8').write(html)
print('written index.html')
