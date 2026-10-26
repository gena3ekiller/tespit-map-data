#!/usr/bin/env python3
"""Baut die Grenzdatei und die Länderregeln für die Blitzer-Ländersperre (Plan vom 22.10.2026).

Ausgabe:
  out/speedtrap_borders_v1.json  vereinfachte Natural-Earth-Grenzen (gemeinfrei)
  out/country_policy_v1.json     Ländertabelle, Säume und Positionsschwellen

Die Ländertabelle ist die einzige Quelle für Swift, Kotlin und die Pipeline.
"""
import json, math
from pathlib import Path

B = Path(__file__).resolve().parent
RAW = B / 'raw' / 'ne_10m_admin_0_countries.geojson'
OUT = B / 'out'

STATES = {
    # gesperrt: verboten oder Rechtslage unklar
    'CH': 'blocked', 'LI': 'blocked', 'TR': 'blocked', 'MK': 'blocked', 'CY': 'blocked',
    'BA': 'blocked', 'SK': 'blocked', 'IE': 'blocked', 'CN': 'blocked',
    # Frankreich: nur Gefahrenzonen, nie Blitzerstandorte
    'FR': 'zonesOnly',
    # Deutschland: läuft mit Hinweis (§ 23 Abs. 1c StVO)
    'DE': 'allowedWithNotice',
    # erlaubt laut Recherche
    'AT': 'allowed', 'IT': 'allowed', 'ES': 'allowed', 'NL': 'allowed', 'BE': 'allowed', 'LU': 'allowed',
    'PL': 'allowed', 'CZ': 'allowed', 'HU': 'allowed', 'DK': 'allowed', 'GB': 'allowed', 'US': 'allowed',
    'HK': 'allowed', 'MO': 'allowed', 'XK': 'allowed',
}

POLICY = {
    'schema': 1,
    'note': 'Strenge: blocked > unknown > zonesOnly > allowedWithNotice > allowed. Nicht gelistete Länder sind unknown (aus).',
    'default': 'unknown',
    'states': STATES,
    'bands': {
        'blocked': {'enterKm': 2.0, 'leaveKm': 2.5},
        'blocked.CN': {'enterKm': 10.0, 'leaveKm': 10.5},
        'zonesOnly': {'enterKm': 1.0, 'leaveKm': 1.5},
        'allowedWithNotice': {'enterKm': 0.5, 'leaveKm': 1.0},
    },
    'positions': {'maxAccuracyM': 65, 'maxAgeS': 5, 'teslaAccuracyM': 65, 'teslaExtraAgeS': 2},
    'relax': {'fixes': 5, 'seconds': 4},
    'pipelineBlockedBandKm': 3.0,
    'appAdmissionBlockedBandKm': 2.0,
}

EUROPE = (-32.0, 27.0, 50.0, 72.0)   # lon_min, lat_min, lon_max, lat_max
EXTRA = {'CN', 'HK', 'MO', 'US'}


def dp(points, tol):
    """Douglas-Peucker in Grad; Ringe bleiben geschlossen."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]; bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        best, idx = 0.0, None
        for i in range(a + 1, b):
            px, py = points[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / norm if norm else math.hypot(px - ax, py - ay)
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def bbox_of(coords):
    xs = [p[0] for ring in coords for p in ring]; ys = [p[1] for ring in coords for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def intersects(b, r):
    return not (b[2] < r[0] or b[0] > r[2] or b[3] < r[1] or b[1] > r[3])


def main():
    data = json.loads(RAW.read_text(encoding='utf-8'))
    countries = []
    for f in data['features']:
        iso = f['properties'].get('ISO_A2_EH')
        if not iso or iso == '-99':
            continue
        if iso not in STATES:
            continue  # nicht gelistete Länder sind ohnehin unknown (aus); ihre Fläche wird nicht gebraucht
        geom = f['geometry']
        polys = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
        europe_polys = []
        for poly in polys:
            b = bbox_of(poly)
            in_europe = intersects(b, EUROPE)
            if not in_europe and iso not in EXTRA:
                continue
            tol = 0.0015 if in_europe else 0.02
            rings = []
            for ring in poly:
                simplified = dp([(round(x, 4), round(y, 4)) for x, y in ring], tol)
                if len(simplified) >= 4:
                    rings.append([[round(x, 4), round(y, 4)] for x, y in simplified])
            if rings:
                europe_polys.append(rings)
        if europe_polys:
            countries.append({'iso': iso, 'polygons': europe_polys})
    countries.sort(key=lambda c: c['iso'])
    OUT.mkdir(exist_ok=True)
    borders = {
        'schema': 1,
        'source': 'Natural Earth 1:10m Admin 0 Countries (public domain), vereinfacht (Douglas-Peucker ~150 m in Europa, 4 Nachkommastellen)',
        'countries': countries,
    }
    text = json.dumps(borders, separators=(',', ':'))
    (OUT / 'speedtrap_borders_v1.json').write_text(text, encoding='utf-8')
    (OUT / 'country_policy_v1.json').write_text(json.dumps(POLICY, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    missing = [iso for iso in STATES if iso not in {c['iso'] for c in countries}]
    print('Länder in der Grenzdatei:', len(countries), '| Größe:', round(len(text) / 1e6, 2), 'MB | fehlende Regelländer:', missing)


if __name__ == '__main__':
    main()
