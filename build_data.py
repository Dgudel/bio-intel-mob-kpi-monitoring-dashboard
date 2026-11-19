"""Build KPI time-series JSON for the BIO-INTEL-MOB dashboard from the downloaded public datasets."""
import json, sys, os
import pandas as pd

D = sys.argv[1]  # data root containing Vilnius/, Ryga/, ES_palyginimas/
OUT = sys.argv[2]
ALT = sys.argv[3] if len(sys.argv) > 3 else None  # optional fallback root for files missing in D

V = os.path.join(D, 'Vilnius'); R = os.path.join(D, 'Ryga'); E = os.path.join(D, 'ES_palyginimas')
_orig_read = pd.read_csv
def _read(path, *a, **k):
    if isinstance(path, str) and not os.path.exists(path) and ALT:
        alt = os.path.join(ALT, os.path.relpath(os.path.normpath(path), os.path.normpath(D)))
        if os.path.exists(alt): path = alt
    return _orig_read(path, *a, **k)
pd.read_csv = _read
def rd(*p): return pd.read_csv(os.path.join(*p))

# Entities: fixed identity -> colour slot (colour follows entity)
ENT = {
    'vrd':  dict(name='Vilnius District Municipality (pilot area)', short='Vilnius district', level='Municipality (LAU)', city='Vilnius'),
    'vcity': dict(name='Vilnius City Municipality', short='Vilnius city', level='Municipality (LAU)', city='Vilnius'),
    'lt01': dict(name='Capital Region of Lithuania (LT01)', short='LT01 Capital region', level='Region (NUTS 2)', city='Vilnius'),
    'lt':   dict(name='Lithuania', short='Lithuania', level='National', city='Vilnius'),
    'riga': dict(name='Riga City', short='Riga city', level='City', city='Riga'),
    'pieriga': dict(name='Pierīga peri-urban municipalities (Riga region)', short='Pierīga (peri-urban)', level='Municipalities (aggregated)', city='Riga'),
    'lv':   dict(name='Latvia', short='Latvia', level='National', city='Riga'),
    'eu':   dict(name='EU-27', short='EU-27', level='EU benchmark', city='EU'),
}

def yr(df, t='time', v='value'):
    s = df[[t, v]].dropna()
    return [[int(a), round(float(b), 4)] for a, b in zip(s[t], s[v])]

def ser(ent, pts, label=None, freq='A', source='', note=''):
    e = ENT.get(ent, {})
    return dict(entity=ent, label=label or e.get('name', ent), level=e.get('level', ''), city=e.get('city', ''),
                freq=freq, source=source, note=note, data=pts)

# -------- helpers for common tables
def osp(path, filt=None, ent_map=None, minyear=None):
    d = pd.read_csv(path)
    if filt is not None: d = d[filt(d)]
    out = {}
    m = ent_map or {'Vilniaus r. sav.': 'vrd', 'Vilniaus m. sav.': 'vcity', 'Lietuvos Respublika': 'lt', 'Sostinės regionas': 'lt01'}
    for name, ent in m.items():
        q = d[d.savivaldybesRegdb_pavadinimas == name].copy()
        q['TIME_PERIOD'] = q.TIME_PERIOD.astype(int)
        if minyear: q = q[q.TIME_PERIOD >= minyear]
        q = q.sort_values('TIME_PERIOD')
        out[ent] = yr(q, 'TIME_PERIOD')
    return out

def es(path, geo_ent, **filt):
    d = pd.read_csv(path)
    for k, v in filt.items(): d = d[d[k] == v]
    out = {}
    for g, ent in geo_ent.items():
        q = d[d.geo == g].sort_values('time')
        out[ent] = yr(q)
    return out

SRC = {
    'osp': 'Statistics Lithuania (osp.stat.gov.lt)',
    'lsp': 'Official Statistics Portal of Latvia (data.stat.gov.lv)',
    'eurostat': 'Eurostat',
    'urb': 'Eurostat Urban Audit (urb_ctran / urb_cenv)',
    'eea': 'EEA Air Quality e-reporting (E1a/E2a)',
    'rs': 'Rīgas satiksme e-ticket validations (data.gov.lv)',
}

charts = {}  # kpi -> list of charts

def chart(kpi, cid, title, unit, series, desc='', direction=None, headline=False, kind='line', index_base=None):
    charts.setdefault(kpi, []).append(dict(id=cid, title=title, unit=unit, series=[s for s in series if s['data']],
                                           desc=desc, direction=direction, headline=headline, kind=kind))

# ================= KPI 1 – private car dependency
f = os.path.join(V, 'KPI01_Priklausomybe_nuo_automobilio', 'osp_S5R086_M7030305_2.csv')
o = osp(f, minyear=2014)
lv = rd(R, 'KPI01_Priklausomybe_nuo_automobilio', 'lsp_TRC010.csv'); lv = lv[lv.Laikotarpis >= 2014]
rc = rd(R, 'KPI01_Priklausomybe_nuo_automobilio', 'eurostat_urb_ctran_miesto_transportas.csv'); rc = rc[(rc.indic_ur == 'TT1057I') & (rc.cities == 'LV001C') & (rc.time >= 2014)].sort_values('time')
eu = rd(E, 'KPI01_Priklausomybe_nuo_automobilio', 'eurostat_road_eqs_carhab_automobiliai_1000_gyv.csv'); eu = eu[eu.time >= 2014]
chart(1, 'k1_motor', 'Passenger cars per 1,000 inhabitants', 'cars / 1,000 inh.', [
    ser('vrd', o['vrd'], source=SRC['osp'] + ' S5R086'),
    ser('vcity', o['vcity'], source=SRC['osp'] + ' S5R086'),
    ser('lt', o['lt'], source=SRC['osp'] + ' S5R086'),
    ser('riga', yr(rc), source=SRC['urb'] + ' TT1057I'),
    ser('lv', yr(lv, 'Laikotarpis'), source=SRC['lsp'] + ' TRC010'),
    ser('eu', yr(eu), source=SRC['eurostat'] + ' road_eqs_carhab'),
], desc='Motorisation rate - the most granular public proxy of car dependency. Lithuanian series start in 2014 (register methodology break 2013/2014).', direction='down', headline=True)

ps = {}
for c, p, g in [('Vilnius', V, {'LT': 'lt'}), ('Ryga', R, {'LV': 'lv'}), ('EU', E, {'EU27_2020': 'eu'})]:
    ps.update(es(os.path.join(p, 'KPI01_Priklausomybe_nuo_automobilio', 'eurostat_tran_hv_psmod_modalinis_pasiskirstymas.csv'), g, vehicle='CAR'))
chart(1, 'k1_modal', 'Passenger cars - share of inland passenger-km', '% of passenger-km', [
    ser('lt', ps['lt'], source=SRC['eurostat'] + ' tran_hv_psmod'),
    ser('lv', ps['lv'], source=SRC['eurostat'] + ' tran_hv_psmod'),
    ser('eu', ps['eu'], source=SRC['eurostat'] + ' tran_hv_psmod'),
], desc='GA baseline for this KPI is the national private-car modal share (Lithuania 91.7 %, Latvia 83.7 %). National level only: excludes walking, cycling and urban PT.', direction='down')

# ================= KPI 2 – mobility CO2 / GHG
gge = {}
for p, g in [(V, {'LT': 'lt'}), (R, {'LV': 'lv'}), (E, {'EU27_2020': 'eu'})]:
    gge.update(es(os.path.join(p, 'KPI02_Mobilumo_CO2_SESD', 'eurostat_env_air_gge_transporto_SESD.csv'), g, src_crf='CRF1A3B'))
def index(pts, base):
    b = dict(pts).get(base)
    return [[t, round(v / b * 100, 2)] for t, v in pts] if b else []
chart(2, 'k2_road_idx', 'GHG emissions from road transport (index 2015 = 100)', 'index, 2015 = 100', [
    ser(k, index([p for p in gge[k] if p[0] >= 2005], 2015), source=SRC['eurostat'] + ' env_air_gge (CRF 1.A.3.b)') for k in ['lt', 'lv', 'eu']
], desc='Indexed so that countries of very different size share one axis. Absolute values (Mt CO2e) shown in the table view.', direction='down', headline=True)
chart(2, 'k2_road_abs', 'GHG emissions from road transport', 'Mt CO2e', [
    ser(k, [p for p in gge[k] if p[0] >= 2005], source=SRC['eurostat'] + ' env_air_gge (CRF 1.A.3.b)') for k in ['lt', 'lv']
], desc='Fuel combustion in road transport, national inventory.', direction='down')
# transport share of total
share = {}
for p, g, ent in [(V, 'LT', 'lt'), (R, 'LV', 'lv')]:
    tr = rd(p, 'KPI02_Mobilumo_CO2_SESD', 'eurostat_env_air_gge_transporto_SESD.csv'); tr = tr[(tr.src_crf == 'CRF1A3')].set_index('time').value
    tot = rd(p, 'KPI02_Mobilumo_CO2_SESD', 'eurostat_sdg_13_10_SESD_bendros.csv'); tot = tot[(tot.src_crf == 'TOTX4_MEMO') & (tot.unit == 'MTCO2E')].set_index('time').value
    s = (tr / tot * 100).dropna(); s = s[s.index >= 2005]
    share[ent] = [[int(a), round(float(b), 2)] for a, b in s.items()]
chart(2, 'k2_share', 'Transport share of total national GHG emissions', '% of total GHG (excl. LULUCF)', [
    ser('lt', share['lt'], source=SRC['eurostat'] + ' env_air_gge + sdg_13_10'),
    ser('lv', share['lv'], source=SRC['eurostat'] + ' env_air_gge + sdg_13_10'),
], desc='Matches the GA baseline wording ("transport share of national GHGs ~25 %").', direction='down')

# ================= KPI 3 – multimodal transport efficiency
pas = osp(os.path.join(V, 'KPI03_Multimodalumo_efektyvumas', 'osp_S5R029_M7030327_2.csv'), filt=lambda d: (d.transtipas4r == 'k3') & (d.reisasM5820213 == 2), minyear=2012)
vkm = osp(os.path.join(V, 'KPI03_Multimodalumo_efektyvumas', 'osp_S5R003_M7030327_3.csv'), filt=lambda d: (d.reisasM5820213 == 2), minyear=2012)
def ratio(a, b):
    bb = dict(b); return [[t, round(v / bb[t], 3)] for t, v in a if bb.get(t)]
chart(3, 'k3_load', 'Bus passengers per bus-km on regular routes', 'passengers / vehicle-km', [
    ser('vrd', ratio(pas['vrd'], vkm['vrd']), source=SRC['osp'] + ' S5R029 / S5R003'),
], desc='Derived productivity proxy: passengers carried divided by vehicle-km run by buses and trolleybuses on regular routes (registered in the municipality). Rising = more efficient use of the PT supply.', direction='up', headline=True)
chart(3, 'k3_load_city', 'Bus & trolleybus passengers per vehicle-km - Vilnius city (comparison)', 'passengers / vehicle-km', [
    ser('vcity', ratio(pas['vcity'], vkm['vcity']), source=SRC['osp'] + ' S5R029 / S5R003'),
], desc='Same indicator for the core city network - a comparison series for difference-in-differences against the pilot district.', direction='up')
chart(3, 'k3_vkm', 'Bus vehicle-km on regular routes - Vilnius district', 'thousand vehicle-km', [
    ser('vrd', vkm['vrd'], label='Vilnius District Municipality (pilot area)', source=SRC['osp'] + ' S5R003'),
], desc='PT supply offered by carriers registered in Vilnius District (suburban regular routes).', direction='up')
rs = rd(R, 'KPI01_Priklausomybe_nuo_automobilio', 'rigas_satiksme_etalonu_validacijos_marsrutas_menuo.csv')
m = rs.groupby('Menuo').validacijos.sum() / 1e6
m = m[m.index >= '2020-09']
chart(3, 'k3_rs', 'Rīgas satiksme public transport boardings (e-ticket validations)', 'million validations / month', [
    ser('riga', [[k, round(float(v), 3)] for k, v in m.items()], label='Riga city (Rīgas satiksme network)', freq='M', source=SRC['rs'],
        note='Earlier months (2018-05/06, 2020-01) published only partly and are excluded; not all passengers validate.'),
], desc='Monthly demand on the Riga municipal PT network - the most frequent public series for the Riga pilot.', direction='up')
tp = rd(R, 'KPI03_Multimodalumo_efektyvumas', 'lsp_TPA010.csv')
tps = (tp.groupby('Laikotarpis').value.sum() / 1000)
chart(3, 'k3_riga_tram', 'Passengers carried by tram and trolleybus - Riga', 'million passengers / year', [
    ser('riga', [[int(a), round(float(b), 2)] for a, b in tps.items() if a >= 2005], source=SRC['lsp'] + ' TPA010'),
], direction='up')

# ================= KPI 4 – VRU accident risk
inj = osp(os.path.join(V, 'KPI04_VRU_avariju_rizika', 'osp_S5R034_M7030322_2.csv'), filt=lambda d: d.nukentejus_tip == 'suzeist', minyear=2010)
kil = osp(os.path.join(V, 'KPI04_VRU_avariju_rizika', 'osp_S5R034_M7030322_2.csv'), filt=lambda d: d.nukentejus_tip == 'zuvusieji', minyear=2010)
acc = osp(os.path.join(V, 'KPI04_VRU_avariju_rizika', 'osp_S5R035_M7030322_1.csv'), minyear=2010)
chart(4, 'k4_vrd', 'Road casualties in Vilnius District Municipality', 'persons / year', [
    ser('vrd', inj['vrd'], label='Injured - Vilnius district', source=SRC['osp'] + ' S5R034'),
    ser('vrd', kil['vrd'], label='Killed - Vilnius district', source=SRC['osp'] + ' S5R034'),
    ser('vrd', acc['vrd'], label='Injury accidents - Vilnius district', source=SRC['osp'] + ' S5R035'),
], desc='Pilot-municipality level, all road users (public data are not split by VRU at municipal level). VRU split requires the S10 accident-level dataset (data.gov.lt/datasets/3164) - to be downloaded locally.', direction='down', headline=True, kind='byorder')
# monthly accidents VRD
mm = rd(V, 'KPI04_VRU_avariju_rizika', 'osp_S5R035_M7030105_1.csv')
mm = mm[(mm.savivaldybesRegdb_pavadinimas == 'Vilniaus r. sav.') & (mm.keliu_ivykis == 'visi_kel_ivyk')].copy()
mm['t'] = mm.TIME_PERIOD.str.replace('M', '-'); mm = mm.sort_values('t')
chart(4, 'k4_vrd_m', 'Injury road accidents per month - Vilnius district', 'accidents / month', [
    ser('vrd', [[t, float(v)] for t, v in zip(mm.t, mm.value) if pd.notna(v)], freq='M', source=SRC['osp'] + ' S5R035 (monthly)'),
], desc='Monthly series: useful for before/after comparison around PUMH opening dates (use 12-month means to remove seasonality).', direction='down')
# VRU national
vr = rd(V, 'KPI04_VRU_avariju_rizika', 'osp_S5R034_M7030332.csv'); vr = vr[vr.nukentejusysis == 'visi_nukent']
def vru(code, tip):
    q = vr[(vr.keliu_naudotojaiM703 == code) & (vr.nukentejus_tip == tip)].sort_values('TIME_PERIOD'); return yr(q, 'TIME_PERIOD')
chart(4, 'k4_lt_vru', 'Vulnerable road users killed - Lithuania', 'persons / year', [
    ser('lt', vru(2, 'zuvusieji'), label='Pedestrians killed - Lithuania', source=SRC['osp'] + ' S5R034 (M7030332)'),
    ser('lt', vru(3, 'zuvusieji'), label='Cyclists killed - Lithuania', source=SRC['osp'] + ' S5R034 (M7030332)'),
], desc='National VRU fatalities by road-user type.', direction='down', kind='byorder')
ped = {}
for p, g in [(V, {'LT': 'lt'}), (R, {'LV': 'lv'})]:
    d = rd(p, 'KPI04_VRU_avariju_rizika', 'eurostat_tran_sf_roadus_zuve_pagal_eismo_dalyvi.csv')
    d = d[(d.sex == 'T') & (d.age == 'TOTAL') & (d.unit == 'P_MHAB') & (d.pers_cat == 'TOTAL')]
    for gg, ent in g.items(): ped[ent] = yr(d[d.geo == gg].sort_values('time'))
d = rd(E, 'KPI04_VRU_avariju_rizika', 'eurostat_tran_sf_roadus_zuve_pagal_eismo_dalyvi.csv'); d = d[(d.sex == 'T') & (d.age == 'TOTAL') & (d.unit == 'P_MHAB') & (d.pers_cat == 'TOTAL')]
ped['eu'] = yr(d[d.geo == 'EU27_2020'].sort_values('time'))
chart(4, 'k4_permil', 'Road deaths per million inhabitants', 'deaths / million inh.', [
    ser('lt', [p for p in ped['lt'] if p[0] >= 2010], source=SRC['eurostat'] + ' tran_sf_roadus'),
    ser('lv', [p for p in ped['lv'] if p[0] >= 2010], source=SRC['eurostat'] + ' tran_sf_roadus'),
    ser('eu', [p for p in ped['eu'] if p[0] >= 2010], source=SRC['eurostat'] + ' tran_sf_roadus'),
], desc='GA baseline reference ("deaths per million": Lithuania 45-65, Latvia 59).', direction='down')
pd_ = {}
for p, g in [(V, {'LT': 'lt'}), (R, {'LV': 'lv'})]:
    d = rd(p, 'KPI04_VRU_avariju_rizika', 'eurostat_tran_sf_roadus_zuve_pagal_eismo_dalyvi.csv')
    d = d[(d.sex == 'T') & (d.age == 'TOTAL') & (d.unit == 'NR') & (d.pers_cat == 'PED')]
    for gg, ent in g.items(): pd_[ent] = [x for x in yr(d[d.geo == gg].sort_values('time')) if x[0] >= 2010]
chart(4, 'k4_ped', 'Pedestrians killed in road accidents', 'persons / year', [
    ser('lt', pd_['lt'], source=SRC['eurostat'] + ' tran_sf_roadus'), ser('lv', pd_['lv'], source=SRC['eurostat'] + ' tran_sf_roadus'),
], direction='down')
rk = rd(R, 'KPI04_VRU_avariju_rizika', '..', 'KPI01_Priklausomybe_nuo_automobilio', 'eurostat_urb_ctran_miesto_transportas.csv')
rk = rk[(rk.indic_ur == 'TT1060V') & (rk.cities == 'LV001C')].sort_values('time')
chart(4, 'k4_riga', 'Deaths in road accidents - Riga city', 'persons / year', [
    ser('riga', [p for p in yr(rk) if p[0] >= 2005], source=SRC['urb'] + ' TT1060V'),
], direction='down')

# ================= KPI 6 – last-mile logistics emissions
ldt = {}
for p, g in [(V, {'LT': 'lt'}), (R, {'LV': 'lv'}), (E, {'EU27_2020': 'eu'})]:
    ldt.update(es(os.path.join(p, 'KPI02_Mobilumo_CO2_SESD', 'eurostat_env_air_gge_transporto_SESD.csv'), g, src_crf='CRF1A3B2'))
chart(6, 'k6_ldt', 'GHG from light-duty trucks (vans) - index 2015 = 100', 'index, 2015 = 100', [
    ser(k, index([p for p in ldt[k] if p[0] >= 2005], 2015), source=SRC['eurostat'] + ' env_air_gge (CRF 1.A.3.b.ii)') for k in ['lt', 'lv', 'eu']
], desc='Light-duty vehicles do most urban last-mile deliveries; this is the closest public emissions proxy. National level only.', direction='down', headline=True)
fr = {}
for p, g in [(V, {'LT': 'lt'}), (R, {'LV': 'lv'}), (E, {'EU27_2020': 'eu'})]:
    fr.update(es(os.path.join(p, 'KPI06_Paskutines_mylios_emisijos', 'eurostat_tran_hv_frmod_kroviniu_modalinis.csv'), g, tra_mode='ROAD'))
chart(6, 'k6_road', 'Road share of inland freight (tonne-km)', '% of tonne-km', [ser(k, fr[k], source=SRC['eurostat'] + ' tran_hv_frmod') for k in ['lt', 'lv', 'eu']],
      desc='Context indicator for freight modal structure.', direction='down')
charts.setdefault(8, []).append(dict(charts[6][-1], id='k8_road', desc='Context only - logistics efficiency (delays, cost per delivery) must come from logistics operators in the pilot.', headline=True))

# ================= KPI 12 – peri-urban transport GHG
cars_cnt = osp(os.path.join(V, 'KPI01_Priklausomybe_nuo_automobilio', 'osp_S5R011_M7030305_1.csv'), minyear=2014)
tr = rd(R, 'KPI01_Priklausomybe_nuo_automobilio', 'lsp_TRC011.csv')
tr = tr[(tr.INDICATOR == 'TOTAL') & (tr.VEHICLE_label == 'Passenger cars')]
pier = ['Ādaži municipality', 'Ķekava municipality', 'Mārupe municipality', 'Olaine municipality', 'Ropaži municipality', 'Salaspils municipality', 'Saulkrasti municipality', 'Sigulda municipality']
ps_ = tr[tr.AREA_label.isin(pier)].groupby('Laikotarpis').value.sum()
nmun = tr[tr.AREA_label.isin(pier)].groupby('Laikotarpis').AREA_label.nunique()
ps_ = ps_[(nmun == len(pier)) & (ps_.index >= 2021)]  # municipal reform 1 July 2021: earlier years use old borders
rg = tr[tr.AREA_label == 'Riga'].groupby('Laikotarpis').value.sum(); rg = rg[rg.index >= 2014]
def idx_series(s, base):
    s = s.sort_index(); b = s.get(base)
    return [[int(a), round(float(v) / b * 100, 2)] for a, v in s.items()] if b else []
chart(12, 'k12_fleet', 'Registered passenger cars - peri-urban vs core (index 2021 = 100)', 'index, 2021 = 100', [
    ser('vrd', idx_series(pd.Series(dict(cars_cnt['vrd'])), 2021), source=SRC['osp'] + ' S5R011'),
    ser('vcity', idx_series(pd.Series(dict(cars_cnt['vcity'])), 2021), source=SRC['osp'] + ' S5R011'),
    ser('pieriga', idx_series(ps_, 2021), label='Pierīga peri-urban municipalities (8, aggregated)', source=SRC['lsp'] + ' TRC011'),
    ser('riga', idx_series(rg, 2021), source=SRC['lsp'] + ' TRC011'),
], desc='Activity driver for peri-urban transport emissions: the car fleet grows much faster in the peri-urban ring than in the core cities. Pierīga = Ādaži, Ķekava, Mārupe, Olaine, Ropaži, Salaspils, Saulkrasti, Sigulda; shown from 2021 only (administrative-territorial reform changed borders in 2021).', direction='down', headline=True)
chart(12, 'k12_cars_abs', 'Registered passenger cars - Vilnius District Municipality', 'cars', [
    ser('vrd', cars_cnt['vrd'], source=SRC['osp'] + ' S5R011'),
], direction='down')
chart(12, 'k12_cars_lt', 'GHG from passenger cars (national) - index 2015 = 100', 'index, 2015 = 100', [
    ser(k, index([p for p in v if p[0] >= 2005], 2015), source=SRC['eurostat'] + ' env_air_gge (CRF 1.A.3.b.i)') for k, v in
    {**es(os.path.join(V, 'KPI02_Mobilumo_CO2_SESD', 'eurostat_env_air_gge_transporto_SESD.csv'), {'LT': 'lt'}, src_crf='CRF1A3B1'),
     **es(os.path.join(R, 'KPI02_Mobilumo_CO2_SESD', 'eurostat_env_air_gge_transporto_SESD.csv'), {'LV': 'lv'}, src_crf='CRF1A3B1')}.items()
], desc='National car-emission trend; a pilot-area value requires the emissions model (traffic counts x fleet mix x emission factors).', direction='down')

# ================= KPI 13 – air quality
def eea(path, names=None):
    d = pd.read_csv(path)
    if 'Stotis' not in d.columns:
        st = pd.read_csv(os.path.join(os.path.dirname(path), 'eea_stotys.csv'))
        mp = {('LT/' + r['Sampling Point Id']): r['Air Quality Station Name'].strip('"') + ' (' + r['Air Quality Station Type'] + ')' for _, r in st.iterrows()}
        d['Stotis'] = d.Samplingpoint.map(mp)
    else:
        st = pd.read_csv(os.path.join(os.path.dirname(path), 'eea_stotys.csv'))
        tp = {str(r['Air Quality Station Name']).strip('"'): r['Air Quality Station Type'] for _, r in st.iterrows()}
        d['Stotis'] = d.Stotis.map(lambda s: f"{s} ({tp.get(s, '')})")
    return d
va = eea(os.path.join(V, 'KPI13_Oro_kokybe', 'eea_oro_kokybe_metiniai_vidurkiai.csv'))
ra = eea(os.path.join(R, 'KPI13_Oro_kokybe', 'eea_oro_kokybe_metiniai_vidurkiai.csv'))
def aq(d, pol, city):
    out = []
    for stn, q in d[(d['Teršalas'] == pol) & (d.dienu >= 200)].groupby('Stotis'):
        q = q.sort_values('Metai')
        out.append(dict(entity='stn', label=stn, level='Monitoring station', city=city, freq='A', source=SRC['eea'],
                        note='Annual mean of daily means; 2026 = year to date (partial).' , data=[[int(a), round(float(b), 2)] for a, b in zip(q.Metai, q.metinis_vidurkis)]))
    return out
for pol, lim in [('NO2', 'WHO 2021 guideline 10 µg/m³; EU 2030 limit 20 µg/m³'), ('PM10', 'WHO 2021 guideline 15 µg/m³; EU 2030 limit 20 µg/m³'), ('PM2.5', 'WHO 2021 guideline 5 µg/m³; EU 2030 limit 10 µg/m³')]:
    sv = aq(va, pol, 'Vilnius'); sr = aq(ra, pol, 'Riga')
    chart(13, f'k13_{pol}', f'{pol} annual mean concentration by station', 'µg/m³', sv + sr,
          desc=f'Urban monitoring stations (no station inside Vilnius District pilot area). Years with < 200 valid days excluded. Riga: older stations closed end-2021, new stations reporting from 2025 -> gap 2022-2024. {lim}.',
          direction='down', headline=(pol == 'NO2'), kind='stations')
# Urban audit historical
ua = []
for p, ent, c in [(V, 'vcity', 'LT001C'), (R, 'riga', 'LV001C')]:
    d = rd(p, 'KPI13_Oro_kokybe', 'eurostat_urb_cenv_miesto_aplinka.csv'); d = d[(d.indic_ur == 'EN2026V')].sort_values('time')
    ua.append(ser(ent, yr(d), label=ENT[ent]['name'] if ent != 'vcity' else 'Vilnius city', source=SRC['urb'] + ' EN2026V'))
chart(13, 'k13_ua', 'Annual mean NO2 - historical city series (Urban Audit)', 'µg/m³', ua, desc='Discontinued after 2013; kept for long-run context.', direction='down')

# ================= KPI 14 – noise
nz = {}
for p, g in [(V, {'LT': 'lt'}), (R, {'LV': 'lv'}), (E, {'EU27_2020': 'eu'})]:
    nz.update(es(os.path.join(p, 'KPI14_Triuksmas', 'eurostat_sdg_11_20_triuksmo_poveikis.csv'), g, rskpovth='TOTAL'))
chart(14, 'k14_noise', 'Population reporting noise from neighbours or the street', '% of population', [ser(k, nz[k], source=SRC['eurostat'] + ' sdg_11_20 (EU-SILC)') for k in ['lt', 'lv', 'eu']],
      desc='Survey-based national indicator (EU-SILC). Riga strategic noise maps (2018, 2021; Lden/Lnight GIS layers) are stored in Ryga/_zaliavos for a spatial baseline around the hubs.', direction='down', headline=True)

# ================= KPI 15 – sustainable modes
cyc = osp(os.path.join(V, 'KPI15_Tvarios_keliones', 'osp_S5R006_M7030334.csv'))
rb = rd(R, 'KPI01_Priklausomybe_nuo_automobilio', 'eurostat_urb_ctran_miesto_transportas.csv'); rb = rb[(rb.indic_ur == 'TT1079V') & (rb.cities == 'LV001C')].sort_values('time')
chart(15, 'k15_cyc', 'Length of cycle paths', 'km', [
    ser('vrd', cyc['vrd'], source=SRC['osp'] + ' S5R006'), ser('vcity', cyc['vcity'], source=SRC['osp'] + ' S5R006'),
    ser('riga', yr(rb), source=SRC['urb'] + ' TT1079V'),
], desc='Supply-side enabler of sustainable trips. Vilnius district network grew from 10 km (2020) to 43 km (2025).', direction='up', headline=True)
chart(15, 'k15_pas', 'Passengers on regular bus routes', 'thousand passengers / year', [
    ser('vrd', pas['vrd'], source=SRC['osp'] + ' S5R029'),
], desc='Passengers carried by carriers registered in Vilnius District on regular (mainly suburban) routes.', direction='up')
chart(15, 'k15_rs', 'Riga municipal PT boardings - 12-month rolling total', 'million validations / 12 months', [
    ser('riga', (lambda s: [[k, round(float(v), 2)] for k, v in s.items() if pd.notna(v)])(m.rolling(12).sum()), label='Riga city (Rīgas satiksme network)', freq='M', source=SRC['rs']),
], desc='Rolling sum removes seasonality - best line for judging trend changes after hub openings.', direction='up')
pt = {}
for p, g in [(V, {'LT': 'lt'}), (R, {'LV': 'lv'}), (E, {'EU27_2020': 'eu'})]:
    pt.update(es(os.path.join(p, 'KPI01_Priklausomybe_nuo_automobilio', 'eurostat_tran_hv_psmod_modalinis_pasiskirstymas.csv'), g, vehicle='TRN_BUS_TOT_AVD'))
chart(15, 'k15_modal', 'Bus, coach and train - share of inland passenger-km', '% of passenger-km', [ser(k, pt[k], source=SRC['eurostat'] + ' tran_hv_psmod') for k in ['lt', 'lv', 'eu']], direction='up')

# ================= KPI 16 – health
pm = {}
for p, g in [(V, {'LT': 'lt'}), (R, {'LV': 'lv'}), (E, {'EU27_2020': 'eu'})]:
    pm.update(es(os.path.join(p, 'KPI13_Oro_kokybe', 'eurostat_sdg_11_52_KD2_5_priesmirtines_mirtys.csv'), g, unit='RT'))
chart(16, 'k16_pm', 'Premature deaths attributable to PM2.5 exposure', 'deaths / 100,000 inh.', [ser(k, pm[k], source=SRC['eurostat'] + ' sdg_11_52 (EEA)') for k in ['lt', 'lv', 'eu']],
      desc='EEA health-impact estimate, all sources of PM2.5 (not transport only). National level.', direction='down', headline=True)
hl = {}
for p, g in [(V, {'LT': 'lt'}), (R, {'LV': 'lv'})]:
    d = rd(p, 'KPI16_Tarsos_poveikis_sveikatai', 'eurostat_hlth_cd_aro_mirtingumas_kvepavimo_kraujotakos.csv'); d = d[d.icd10 == 'J']
    for gg, ent in g.items(): hl[ent] = yr(d[d.geo == gg].sort_values('time'))
chart(16, 'k16_resp', 'Deaths from respiratory diseases (ICD-10 J)', 'deaths / year', [ser(k, hl[k], source=SRC['eurostat'] + ' hlth_cd_aro') for k in ['lt', 'lv']],
      desc='Context outcome - strongly influenced by non-transport factors (e.g. COVID-19 in 2020-2021).', direction='down')

# ================= KPI definitions (GA GAP-101239638, Part B)
K = [
 (1, 'Reduction in private car dependency', -35, 'Private car modal share; 35 % modal shift in target areas', 'Environmental / mobility', 'Obj. 2; Table 2.1.2-a (p. 39)',
  'Private car modal share (national): Lithuania 91.7 %, Latvia 83.7 %', 'Trip modal split (household / PUMH user surveys), PT ridership and car flows at the hubs before vs after.', 'proxy'),
 (2, 'Decrease in mobility-related CO2 emissions', -25, '25 % reduction', 'Environmental', 'Obj. 1; Table 2.1.2-a (p. 39)',
  'Transport share of national GHG: Lithuania ~25 % (falling), Latvia ~25 %', 'Pilot-area traffic volumes, vehicle classes and speeds (AI cameras / S7 counters) + emission factors.', 'proxy'),
 (3, 'Increase in multimodal transport efficiency', 35, '+35 % improvement', 'Mobility / operational', 'Obj. 1; Table 2.1.2-a (p. 39)',
  'EU Urban Mobility Scorecard 2024 & pilot diagnostics (TBD)', 'Door-to-door travel and transfer times, punctuality, connections at PUMHs, PT demand.', 'proxy'),
 (4, 'Reduction in VRU-related accident risks', -35, '35 % reduction (Obj. 2 states 40 %)', 'Safety', 'Obj. 2; Table 2.1.2-a (p. 39)',
  'VRU deaths per million: Lithuania 45-65, Latvia 59', 'Accident records with location (S10), VRU exposure counts and conflict / near-miss detection from AI cameras.', 'partial'),
 (5, 'Increase in citizen participation in planning', 40, '+40 % participation (pilot text: from 40 % to 50 %)', 'Social / governance', 'Obj. 4; p. 21',
  '< 20 % of peri-urban residents participate in planning', 'Unique participants vs target population; Citizen-Voice App, VR/AR workshop and consultation registers.', 'pending'),
 (6, 'Decrease in last-mile logistics emissions', -25, '25 % reduction', 'Environmental / logistics', 'Obj. 3',
  'TBD', 'Delivery km, vehicle type, fuel/energy and load from logistics operators; emissions model.', 'proxy'),
 (7, 'Reduction in logistics packaging waste', -25, '25 % reduction', 'Environmental / circular economy', 'Obj. 3 (bioPLU)',
  'TBD', 'Packaging mass by material before vs after bioPLU deployment; operator records, LCA.', 'pending'),
 (8, 'Increase in logistics efficiency', 20, '+20 % (Obj. 3 states 35 %)', 'Economic / logistics', 'Obj. 3',
  'TBD', 'Delivery delays, time and cost per delivery from operators.', 'proxy'),  # 17 Nov 2026: national road-share context series shown -> proxy
 (9, 'Reduction in peri-urban congestion', -30, '30 % reduction', 'Mobility', 'Obj. 2; p. 21',
  'Real-time traffic monitoring / TomTom index (TBD)', 'Travel time, average speed, queue length and flows on the same corridors before vs after (S7 counters, cameras, navigation data).', 'pending'),
 (10, 'Reduction in annual economic losses from congestion', -30, '30 % reduction', 'Economic', 'Expected impacts',
  'TBD', 'Vehicle-hours of delay x value of time; requires congestion KPI 9 plus an economic model.', 'pending'),
 (11, 'Policy compliance process acceleration', -25, '25 % faster policy and regulatory cycles', 'Governance', 'Table 2.1.2-a (p. 40)',
  'Timelines TBD in pilots', 'Submission and decision dates of the relevant permit / planning procedures from municipal registers.', 'pending'),
 (12, 'Reduction in peri-urban transport GHG emissions', -25, '25 % reduction', 'Environmental', 'p. 21; expected impacts',
  'TBD', 'Pilot-territory traffic volumes, VKT and fleet mix; emissions model with defined boundary (avoid double counting with KPI 2).', 'proxy'),
 (13, 'Improvement in air quality', 20, '+20 % (joint with noise)', 'Environmental / health', 'p. 21; expected impacts',
  'EEA station data', 'NO2 / PM concentrations at or near the PUMHs (low-cost sensors) before vs after.', 'partial'),
 (14, 'Reduction in noise pollution', 20, '+20 % (joint with air quality)', 'Environmental / health', 'p. 21; expected impacts',
  'Strategic noise maps (Riga 2018/2021)', 'Lden / Lnight measurements near the hubs and corridors.', 'proxy'),
 (15, 'Increase in sustainable transport adoption', 35, '+35 % adoption and efficiency', 'Mobility / social', 'Obj. 2; Table 2.1.2-a',
  'National PT shares; PT ridership', 'Mode shares of trips, PT boardings at hub stops, pedestrian / cyclist counts.', 'partial'),
 (16, "Reduction in pollution's human-health effect", -30, '30 % reduction', 'Health', 'p. 21; expected impacts',
  'EEA health-impact estimates', 'Population exposure (air + noise) in the pilot area and an exposure-response model.', 'proxy'),
 (17, 'Increase in participatory governance efficiency', 40, '+40 % participation rates & policy co-design cycles', 'Governance', 'Obj. 4; Table 2.1.2-a (p. 39)',
  'Fragmented, low engagement; input mechanisms inconsistent or absent', 'Share of engaged citizens, time to process proposals, number of co-design cycles (Citizen-Voice / VR-AR logs).', 'pending'),
]
kpis = []
for n, name, tgt, tgt_txt, dim, ref, base, primary, status in K:
    ch = charts.get(n, [])
    if not ch: status = 'pending'
    elif status != 'pending':
        ents = {x['entity'] for c in ch for x in c['series']}
        status = 'partial' if ents & {'vrd', 'pieriga'} else 'proxy'  # partial = series at pilot-municipality level exist
    kpis.append(dict(id=n, name=name, target=tgt, target_text=tgt_txt, dimension=dim, ga_ref=ref, ga_baseline=base,
                     primary_data=primary, status=status, charts=ch))

meta = dict(project_start='2026-01', project_end='2029-06', generated=pd.Timestamp.now().strftime('%Y-%m-%d'),
            entities=ENT)
json.dump(dict(meta=meta, kpis=kpis), open(OUT, 'w'), ensure_ascii=False)
print('ok', sum(len(k['charts']) for k in kpis), 'charts;', os.path.getsize(OUT) // 1024, 'KB')
for k in kpis:
    print(k['id'], k['status'], [ (c['id'], len(c['series']), [len(s['data']) for s in c['series']]) for c in k['charts']])
