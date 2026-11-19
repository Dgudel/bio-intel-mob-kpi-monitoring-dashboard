"""Download / refresh the public source data used by the BIO-INTEL-MOB KPI dashboard.

Usage:  python3 scripts/fetch_data.py [data_dir]        (default: ./data/duomenys)

Writes only the CSV files that build_data.py reads, in the same layout as the
original download notebook (data/<Vilnius|Ryga|ES_palyginimas>/KPI<nn>_<name>/<file>.csv).

Safety rules (so a broken portal never breaks the dashboard):
  * every job runs on its own; a failed download keeps the previous file;
  * a new file replaces the old one only if it is non-empty, has the same columns
    and at least 80 % of the old row count;
  * files are written deterministically, so an unchanged source gives a byte-identical
    file and git sees no change.
Sources: Eurostat API, Statistics Lithuania SDMX (osp-rs.stat.gov.lt), Official
Statistics Portal of Latvia PxWeb (data.stat.gov.lv), EEA Air Quality Download
Service, Rigas satiksme e-ticket validations on data.gov.lv (new months only).
"""
import io, os, re, sys, time, zipfile, json
import xml.etree.ElementTree as ET
from datetime import date
import requests
import pandas as pd

DATA = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'duomenys'))
S = requests.Session()
S.headers['User-Agent'] = 'BIO-INTEL-MOB-KPI-dashboard/1.0 (research; scheduled update)'
TIMEOUT = 180
REPORT = []  # (status, file, message)

KPI_DIR = {1: 'KPI01_Priklausomybe_nuo_automobilio', 2: 'KPI02_Mobilumo_CO2_SESD', 3: 'KPI03_Multimodalumo_efektyvumas',
           4: 'KPI04_VRU_avariju_rizika', 6: 'KPI06_Paskutines_mylios_emisijos', 13: 'KPI13_Oro_kokybe',
           14: 'KPI14_Triuksmas', 15: 'KPI15_Tvarios_keliones', 16: 'KPI16_Tarsos_poveikis_sveikatai'}


def get(url, **kw):
    """GET (or POST when json= is given) with retries on network errors and 429/5xx."""
    for i in range(4):
        try:
            r = S.post(url, timeout=TIMEOUT, **kw) if kw.get('json') is not None else S.get(url, timeout=TIMEOUT, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f'HTTP {r.status_code}')
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if i == 3: raise
            time.sleep(10 * (i + 1))


def store(df, city, kpi, name):
    """Validate df against the existing file and write it if it is sane."""
    path = os.path.join(DATA, city, KPI_DIR[kpi], name + '.csv')
    rel = os.path.relpath(path, DATA)
    if df is None or df.empty:
        REPORT.append(('KEPT', rel, 'empty response - previous file kept')); return
    if os.path.exists(path):
        old = pd.read_csv(path, nrows=None, low_memory=False)
        if list(old.columns) != list(df.columns):
            missing = set(old.columns) - set(df.columns)
            if missing:
                REPORT.append(('KEPT', rel, f'columns changed (missing {sorted(missing)}) - previous file kept')); return
            df = df[[c for c in old.columns]]
        if len(df) < 0.8 * len(old):
            REPORT.append(('KEPT', rel, f'only {len(df)} rows vs {len(old)} before - previous file kept')); return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = df.to_csv(index=False, lineterminator='\n').encode('utf-8-sig')
    before = open(path, 'rb').read() if os.path.exists(path) else None
    if before == buf:
        REPORT.append(('same', rel, f'{len(df)} rows')); return
    open(path, 'wb').write(buf)
    REPORT.append(('UPDATED', rel, f'{len(df)} rows'))


def job(fn, *a, label=''):
    try:
        fn(*a)
    except Exception as e:
        REPORT.append(('FAILED', label or getattr(fn, '__name__', '?'), f'{type(e).__name__}: {str(e)[:200]} - previous file kept'))


# ---------------------------------------------------------------- Eurostat (JSON-stat 2.0)
EUROSTAT = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'

def jsonstat_to_df(js):
    ids, sizes, dims = js['id'], js['size'], js['dimension']
    cats = []
    for d in ids:
        idx = dims[d]['category']['index']
        cats.append(sorted(idx, key=idx.get) if isinstance(idx, dict) else list(idx))
    labels = {d: dims[d]['category'].get('label', {}) for d in ids}
    vals, stat = js.get('value', {}), js.get('status', {}) or {}
    if isinstance(vals, list):
        vals = {str(i): v for i, v in enumerate(vals) if v is not None}
    mult = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        mult[i] = mult[i + 1] * sizes[i + 1]
    rows = []
    for key, v in vals.items():
        k = int(key); row = {}
        for i, d in enumerate(ids):
            c = cats[i][(k // mult[i]) % sizes[i]]
            row[d] = c
            if d not in ('time', 'freq') and labels[d].get(c) and labels[d][c] != c:
                row[d + '_label'] = labels[d][c]
        row['value'] = v
        row['status'] = stat.get(key, '') if isinstance(stat, dict) else ''
        rows.append(row)
    df = pd.DataFrame(rows)
    if 'time' in df.columns:
        df = df.sort_values([c for c in ids if c in df.columns]).reset_index(drop=True)
    return df

def eurostat(code, **filters):
    params = [('format', 'JSON'), ('lang', 'EN')]
    for k, v in filters.items():
        for x in (v if isinstance(v, (list, tuple)) else [v]):
            params.append((k, x))
    r = get(EUROSTAT + code, params=params)
    if r.status_code != 200:
        raise RuntimeError(f'Eurostat {code} HTTP {r.status_code}')
    df = jsonstat_to_df(r.json())
    if 'time' in df.columns:  # keep integer years as in the original files
        t = pd.to_numeric(df['time'], errors='coerce')
        if t.notna().all(): df['time'] = t.astype(int)
    return df

NAT = {'Vilnius': ['LT'], 'Ryga': ['LV'], 'ES_palyginimas': ['EU27_2020']}
UA = {'Vilnius': ['LT001C', 'LT001L'], 'Ryga': ['LV001C', 'LV001L']}
GGE = {'unit': 'MIO_T', 'airpol': 'GHG', 'src_crf': ['CRF1A3', 'CRF1A3B', 'CRF1A3B1', 'CRF1A3B2', 'TOTX4_MEMONIA']}
# (dataset, filters, geo map, [(city, kpi)], file name)
EUROSTAT_JOBS = [
    ('tran_hv_psmod', {}, NAT, [('Vilnius', 1), ('Ryga', 1), ('ES_palyginimas', 1)], 'eurostat_tran_hv_psmod_modalinis_pasiskirstymas'),
    ('road_eqs_carhab', {}, {'ES_palyginimas': ['EU27_2020']}, [('ES_palyginimas', 1)], 'eurostat_road_eqs_carhab_automobiliai_1000_gyv'),
    ('tran_hv_frmod', {}, NAT, [('Vilnius', 6), ('Ryga', 6), ('ES_palyginimas', 6)], 'eurostat_tran_hv_frmod_kroviniu_modalinis'),
    ('urb_ctran', {}, {'Ryga': UA['Ryga']}, [('Ryga', 1)], 'eurostat_urb_ctran_miesto_transportas'),
    ('urb_cenv', {}, UA, [('Vilnius', 13), ('Ryga', 13)], 'eurostat_urb_cenv_miesto_aplinka'),
    ('env_air_gge', GGE, NAT, [('Vilnius', 2), ('Ryga', 2), ('ES_palyginimas', 2)], 'eurostat_env_air_gge_transporto_SESD'),
    ('sdg_13_10', {}, {'Vilnius': ['LT'], 'Ryga': ['LV']}, [('Vilnius', 2), ('Ryga', 2)], 'eurostat_sdg_13_10_SESD_bendros'),
    ('tran_sf_roadus', {}, NAT, [('Vilnius', 4), ('Ryga', 4), ('ES_palyginimas', 4)], 'eurostat_tran_sf_roadus_zuve_pagal_eismo_dalyvi'),
    ('sdg_11_52', {}, NAT, [('Vilnius', 13), ('Ryga', 13), ('ES_palyginimas', 13)], 'eurostat_sdg_11_52_KD2_5_priesmirtines_mirtys'),
    ('sdg_11_20', {}, NAT, [('Vilnius', 14), ('Ryga', 14), ('ES_palyginimas', 14)], 'eurostat_sdg_11_20_triuksmo_poveikis'),
    ('hlth_cd_aro', {'icd10': ['J', 'I'], 'sex': 'T', 'age': 'TOTAL', 'resid': 'TOT_IN'}, {'Vilnius': ['LT'], 'Ryga': ['LV']},
     [('Vilnius', 16), ('Ryga', 16)], 'eurostat_hlth_cd_aro_mirtingumas_kvepavimo_kraujotakos'),
]

def run_eurostat():
    for code, flt, geomap, targets, name in EUROSTAT_JOBS:
        for city, kpi in targets:
            def one(code=code, flt=flt, geos=geomap[city], city=city, kpi=kpi, name=name):
                dim = 'cities' if code.startswith('urb_') else 'geo'
                store(eurostat(code, **{dim: geos}, **flt), city, kpi, name)
            job(one, label=f'{city}/{name}')
            time.sleep(0.5)


# ---------------------------------------------------------------- Statistics Lithuania (SDMX)
OSP = 'https://osp-rs.stat.gov.lt/rest_xml/'
XL = '{http://www.w3.org/XML/1998/namespace}lang'
KEEP = {'LT', '00', '0', 'LT01', '10', '13', '41'}
_dsd = {}

def osp_labels(dsd):
    if dsd not in _dsd:
        r = get(OSP + f'datastructure/LSD/{dsd}'); r.raise_for_status()
        lab = {}
        for cl in ET.fromstring(r.content).iter():
            if cl.tag.endswith('}Codelist'):
                for c in cl:
                    if c.tag.endswith('}Code'):
                        nm = {n.get(XL): n.text for n in c if n.tag.endswith('Name')}
                        lab[(cl.get('id'), c.get('id'))] = nm.get('lt') or nm.get('en')
        _dsd[dsd] = lab
    return _dsd[dsd]

def osp_data(fid):
    r = get(OSP + f'data/{fid}'); r.raise_for_status()
    root = ET.fromstring(r.content)
    dsd = next((e.get('structureID') for e in root.iter() if e.tag.endswith('}Structure') and e.get('structureID')), None)
    rows = []
    for ob in root.iter():
        if ob.tag.endswith('}Obs'):
            o = {}
            for c in ob:
                if c.tag.endswith('ObsKey'): o.update({v.get('id'): v.get('value') for v in c})
                elif c.tag.endswith('ObsValue'): o['value'] = c.get('value')
                elif c.tag.endswith('Attributes'):
                    for v in c:
                        if v.get('id') == 'OBS_STATUS': o['OBS_STATUS'] = v.get('value')
            rows.append(o)
    df = pd.DataFrame(rows)
    if df.empty: return df
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    if 'OBS_STATUS' not in df.columns: df['OBS_STATUS'] = None
    lab = osp_labels(dsd)
    for col in [c for c in df.columns if c not in ('value', 'LAIKOTARPIS', 'OBS_STATUS')]:
        m = {k[1]: v for k, v in lab.items() if k[0] == col}
        if m: df[col + '_pavadinimas'] = df[col].map(m)
    df = df.rename(columns={'LAIKOTARPIS': 'TIME_PERIOD'})
    if 'savivaldybesRegdb' in df.columns:
        df = df[df['savivaldybesRegdb'].isin(KEEP)]
    return df

OSP_JOBS = [('S5R086_M7030305_2', 1), ('S5R011_M7030305_1', 1), ('S5R006_M7030334', 15), ('S5R029_M7030327_2', 3),
            ('S5R003_M7030327_3', 3), ('S5R035_M7030322_1', 4), ('S5R034_M7030322_2', 4), ('S5R035_M7030105_1', 4),
            ('S5R034_M7030332', 4)]

def run_osp():
    for fid, kpi in OSP_JOBS:
        def one(fid=fid, kpi=kpi):
            df = osp_data(fid)
            path = os.path.join(DATA, 'Vilnius', KPI_DIR[kpi], f'osp_{fid}.csv')
            if os.path.exists(path):  # same column order and dtypes as the stored file
                old = pd.read_csv(path, nrows=5, dtype=str)
                df = df[[c for c in old.columns if c in df.columns]]
                df = df.sort_values([c for c in df.columns if c not in ('value', 'OBS_STATUS') and not c.endswith('_pavadinimas')]).reset_index(drop=True)
            store(df, 'Vilnius', kpi, f'osp_{fid}')
        job(one, label=f'Vilnius/osp_{fid}')


# ---------------------------------------------------------------- Latvia PxWeb
PX = 'https://data.stat.gov.lv/api/v1/en/OSP_PUB/'
TERR = r'^(?:Latvia|Riga|Rīga|Pierīga|Pieriga|Mārupe|Marupe|Ķekava|Kekava|Ropaži|Ropazi|Ādaži|Adazi|Olaine|Salaspils|Saulkrasti|Sigulda|Jūrmala|Jurmala|Total)'
LV_JOBS = [('NOZ/TR/TRC/TRC010', 1), ('NOZ/TR/TRC/TRC011', 1), ('NOZ/TP/PSTR/TPA010', 3)]

def run_lsp():
    for p, kpi in LV_JOBS:
        def one(p=p, kpi=kpi):
            meta = get(PX + p).json()
            q = {'query': [{'code': v['code'], 'selection': {'filter': 'all', 'values': ['*']}} for v in meta['variables']],
                 'response': {'format': 'json-stat2'}}
            r = get(PX + p, json=q); r.raise_for_status()
            d = jsonstat_to_df(r.json())
            if 'TIME' in d.columns: d = d.rename(columns={'TIME': 'Laikotarpis'})
            if 'AREA_label' in d.columns:
                d = d[d['AREA_label'].astype(str).str.strip().str.contains(TERR, case=False, regex=True)]
            t = pd.to_numeric(d['Laikotarpis'], errors='coerce')
            if t.notna().all(): d['Laikotarpis'] = t.astype(int)
            store(d.reset_index(drop=True), 'Ryga', kpi, 'lsp_' + p.split('/')[-1])
        job(one, label='Ryga/lsp_' + p.split('/')[-1])


# ---------------------------------------------------------------- EEA air quality (annual station means)
EEA_API = 'https://eeadmz1-downloads-api-appservice.azurewebsites.net/'
EEA_META = 'https://discomap.eea.europa.eu/App/AQViewer/download?fqn=Airquality_Dissem.b2g.measurements&f=csv'
EEA_CITIES = {'Vilnius': ('LT', (24.95, 54.55, 25.55, 54.85)), 'Ryga': ('LV', (23.85, 56.85, 24.40, 57.10))}
POLL_CODE = {8: 'NO2', 5: 'PM10', 6001: 'PM2.5'}
EEA_START = '2018-01-01'

def run_eea():
    r = get(EEA_META); r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    meta = pd.read_csv(z.open(z.namelist()[0]), low_memory=False).sort_values('Year').drop_duplicates('Sampling Point Id', keep='last')
    for city, (ctry, (x0, y0, x1, y1)) in EEA_CITIES.items():
        def one(city=city, ctry=ctry, box=(x0, y0, x1, y1)):
            st = meta[meta['Country'].str.contains({'LT': 'Lithuania', 'LV': 'Latvia'}[ctry]) &
                      meta['Longitude'].between(box[0], box[2]) & meta['Latitude'].between(box[1], box[3])]
            ids = set(st['Sampling Point Id'])
            frames = []
            for ds in (2, 1):  # 2 = E1a verified, 1 = E2a up-to-date
                body = {'countries': [ctry], 'cities': [], 'pollutants': list(POLL_CODE.values()), 'dataset': ds, 'source': 'API',
                        'dateTimeStart': f'{EEA_START}T00:00:00Z', 'dateTimeEnd': f'{date.today()}T00:00:00Z', 'aggregationType': 'hour'}
                rr = get(EEA_API + 'ParquetFile/urls', json=body); rr.raise_for_status()
                urls = [u.strip() for u in rr.text.splitlines() if u.strip().startswith('http')]
                for u in urls:
                    if u.rsplit('/', 1)[-1].replace('.parquet', '') not in ids: continue
                    d = pd.read_parquet(io.BytesIO(get(u).content))
                    d['dataset'] = 'E1a' if ds == 2 else 'E2a'
                    frames.append(d)
            if not frames: raise RuntimeError('no EEA files')
            h = pd.concat(frames, ignore_index=True)
            h = h[(h['Start'] >= EEA_START) & (h['Validity'] > 0)].copy()
            h['Value'] = pd.to_numeric(h['Value'], errors='coerce')
            h['Teršalas'] = h['Pollutant'].map(POLL_CODE)
            h['Data'] = h['Start'].dt.date.astype(str)
            h = h.sort_values('dataset').drop_duplicates(['Samplingpoint', 'Pollutant', 'Start'], keep='first')
            names = {f'{ctry}/{k}': v for k, v in zip(st['Sampling Point Id'], st['Air Quality Station Name'].str.strip('"'))}
            daily = h.groupby(['Samplingpoint', 'Teršalas', 'Data']).agg(v=('Value', 'mean')).reset_index()
            daily['Stotis'] = daily['Samplingpoint'].map(names)
            yearly = (daily.assign(Metai=daily['Data'].str[:4].astype(int)).groupby(['Samplingpoint', 'Stotis', 'Teršalas', 'Metai'])
                      .agg(metinis_vidurkis=('v', 'mean'), dienu=('v', 'count')).reset_index())
            yearly['metinis_vidurkis'] = yearly['metinis_vidurkis'].round(4)
            # a station-year missing from today's EEA answer (temporary gap) keeps its previous value
            prev = os.path.join(DATA, city, KPI_DIR[13], 'eea_oro_kokybe_metiniai_vidurkiai.csv')
            if os.path.exists(prev):
                old = pd.read_csv(prev)
                key = ['Samplingpoint', 'Teršalas', 'Metai']
                gone = old.merge(yearly[key], on=key, how='left', indicator=True)
                gone = gone[gone['_merge'] == 'left_only'].drop(columns='_merge')
                yearly = pd.concat([yearly, gone[yearly.columns]], ignore_index=True)
            yearly = yearly.sort_values(['Samplingpoint', 'Teršalas', 'Metai']).reset_index(drop=True)
            store(yearly, city, 13, 'eea_oro_kokybe_metiniai_vidurkiai')
            keep = ['Air Quality Station EoI Code', 'Air Quality Station Name', 'Sampling Point Id', 'Air Pollutant', 'Longitude', 'Latitude',
                    'Air Quality Station Area', 'Air Quality Station Type', 'Operational Activity Begin', 'Operational Activity End', 'Year']
            stl = st[st['Sampling Point Id'].isin(set(h['Samplingpoint'].str.split('/').str[-1]))][keep].sort_values('Sampling Point Id')
            store(stl.reset_index(drop=True), city, 13, 'eea_stotys')
        job(one, label=f'{city}/eea')


# ---------------------------------------------------------------- Rigas satiksme e-ticket validations (incremental)
CK = 'https://data.gov.lv/dati/api/3/action/'
RS_PKG = 'e-talonu-validaciju-dati-rigas-satiksme-sabiedriskajos-transportlidzeklos'
RS_MAX_NEW = int(os.environ.get('RS_MAX_NEW_MONTHS', '6'))  # ~100 MB zip per month

def rs_month(raw):
    """One month zip -> rows (Menuo, TranspVeids, TMarsruts, MarsrNos, validacijos)."""
    out = []
    z = zipfile.ZipFile(io.BytesIO(raw))
    for f in z.namelist():
        b = z.open(f).read()
        if b[:2] in (b'\xff\xfe', b'\xfe\xff'): txt = b.decode('utf-16')
        else:
            try: txt = b.decode('utf-8-sig')
            except UnicodeDecodeError: txt = b.decode('cp1257', errors='replace')
        d = pd.read_csv(io.StringIO(txt), usecols=['TranspVeids', 'TMarsruts', 'MarsrNos', 'Laiks'], dtype=str)
        out.append(d)
    d = pd.concat(out, ignore_index=True)
    d['Menuo'] = pd.to_datetime(d['Laiks'].str[:10], format='%d.%m.%Y', errors='coerce').dt.strftime('%Y-%m')
    d['TMarsruts'] = d['TMarsruts'].str.strip(); d['MarsrNos'] = d['MarsrNos'].fillna('').str.strip()
    g = d.groupby(['Menuo', 'TranspVeids', 'TMarsruts'])
    res = g.size().rename('validacijos').reset_index()
    nm = g['MarsrNos'].agg(lambda s: s.mode().iat[0] if len(s.mode()) else '').rename('MarsrNos').reset_index()
    res = res.merge(nm, on=['Menuo', 'TranspVeids', 'TMarsruts'])
    return res[['Menuo', 'TranspVeids', 'TMarsruts', 'MarsrNos', 'validacijos']]

def run_rs():
    path = os.path.join(DATA, 'Ryga', KPI_DIR[1], 'rigas_satiksme_etalonu_validacijos_marsrutas_menuo.csv')
    old = pd.read_csv(path, dtype={'Menuo': str})
    have = set(old['Menuo'])
    p = get(CK + 'package_show', params={'id': RS_PKG}).json()['result']
    todo = []
    for x in p['resources']:
        m = re.search(r'(\d{2})_(\d{4})', x['name'])
        if m and f'{m.group(2)}-{m.group(1)}' not in have:
            todo.append((f'{m.group(2)}-{m.group(1)}', x['url']))
    todo = sorted(todo)[-RS_MAX_NEW:]
    if not todo:
        REPORT.append(('same', os.path.relpath(path, DATA), f'no new months (latest {max(have)})')); return
    new = []
    for mon, url in todo:
        r = get(url); r.raise_for_status()
        q = rs_month(r.content)
        q = q[q['Menuo'] == mon]  # files can carry a few rows of adjacent days
        if len(q): new.append(q)
    if not new: raise RuntimeError('new month files had no rows')
    df = pd.concat([old] + new, ignore_index=True).sort_values(['Menuo', 'TranspVeids', 'TMarsruts']).reset_index(drop=True)
    store(df, 'Ryga', 1, 'rigas_satiksme_etalonu_validacijos_marsrutas_menuo')


STEPS = {'eurostat': run_eurostat, 'osp': run_osp, 'lsp': run_lsp, 'eea': run_eea, 'rs': run_rs}

if __name__ == '__main__':
    only = os.environ.get('ONLY')  # e.g. ONLY=eurostat,osp
    for k, fn in STEPS.items():
        if only and k not in only.split(','): continue
        print(f'[{k}]', flush=True)
        job(fn, label=k)
    lines = ['| Status | File | Note |', '|---|---|---|'] + [f'| {s} | {f} | {m} |' for s, f, m in REPORT]
    print('\n'.join(lines))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as fh:
            fh.write('## KPI data refresh\n\n' + '\n'.join(lines) + '\n')
    n_fail = sum(1 for s, _, _ in REPORT if s in ('FAILED', 'KEPT'))
    print(f'\n{sum(1 for s,_,_ in REPORT if s == "UPDATED")} updated, {sum(1 for s,_,_ in REPORT if s == "same")} unchanged, {n_fail} kept/failed')
