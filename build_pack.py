#!/usr/bin/env python3
"""Baut die Blitzerdatei (Schema 2: mit Anfahrtswegen) aus den OSM-Auszügen (Plan vom 22.10.2026).

- Punkte: feste Blitzer (Art 0) und Rotlichtblitzer (Art 1).
- Abschnitte: Abschnittskontrollen (enforcement=average_speed) als Start und Ende.
- Frankreich: nie Punkte, nur Gefahrenzonen (aus out/fr_zones.json, falls vorhanden).
- Verworfen wird alles in gesperrten Ländern und bis 3 km davor, und alles ausserhalb erlaubter Länder.
- Die Fahrtrichtung kommt nur aus der Enforcement-Relation (from -> Gerät); sonst gilt beide Richtungen.
"""
import datetime, json, re
from pathlib import Path
import geo

B = Path(__file__).resolve().parent
RAW = B / 'raw'
OUT = B / 'out'


def parse_maxspeed(value):
    if not value:
        return 0
    value = value.strip().lower()
    m = re.fullmatch(r'(\d{2,3})\s*(mph)?', value)
    if not m:
        return 0
    speed = int(m.group(1))
    return round(speed * 1.609344) if m.group(2) else speed


def main():
    countries = geo.load_borders()
    policy = geo.load_policy()
    states = policy['states']
    blocked = [c for c in countries if states.get(c['iso']) == 'blocked']
    band_m = policy['pipelineBlockedBandKm'] * 1000

    def admissible(lat, lon):
        iso = geo.country_at(lon, lat, countries)
        state = states.get(iso, policy['default']) if iso else policy['default']
        if state not in ('allowed', 'allowedWithNotice'):
            return None
        for c in blocked:
            limit = 12_000 if c['iso'] == 'CN' else band_m
            if geo.distance_to_country(lon, lat, c, limit) < limit:
                return None
        return iso

    points, sections, stats = {}, [], {}
    anchors = []   # Knoten je Blitzer/Abschnittsbeginn: für fetch_roads.py und build_approaches.py
    for path in sorted(RAW.glob('osm_*.json')):
        source = path.stem[4:]
        if source == 'FR' or len(source) != 2:   # Frankreich nur als Zonen; osm_FR_roads ist keine Länderdatei
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        nodes = {e['id']: e for e in data['elements'] if e['type'] == 'node'}
        ways = {e['id']: e for e in data['elements'] if e['type'] == 'way'}

        def anchor_node(member):
            if member['type'] == 'node' and member['ref'] in nodes:
                return nodes[member['ref']]
            if member['type'] == 'way' and member['ref'] in ways:
                refs = [r for r in ways[member['ref']].get('nodes', []) if r in nodes]
                if refs:
                    return nodes[refs[len(refs) // 2]]
            return None

        def coordinate(member):
            n = anchor_node(member)
            return (n['lat'], n['lon']) if n else None

        directions, red_lights = {}, set()
        for rel in (e for e in data['elements'] if e['type'] == 'relation'):
            tags = rel.get('tags', {})
            kind = tags.get('enforcement')
            members = rel.get('members', [])
            devices = [m for m in members if m.get('role') == 'device' and m['type'] == 'node']
            start = next((coordinate(m) for m in members if m.get('role') == 'from'), None)
            end = next((coordinate(m) for m in members if m.get('role') == 'to'), None)
            if kind == 'average_speed' and start and end:
                if admissible(*start) and admissible(*end):
                    length = geo.haversine_m(start[0], start[1], end[0], end[1])
                    if 300 <= length <= 60_000:
                        row = [round(start[0], 5), round(start[1], 5), round(end[0], 5), round(end[1], 5),
                               parse_maxspeed(tags.get('maxspeed')), round(length)]
                        sections.append(row)
                        first = anchor_node(next(m for m in members if m.get('role') == 'from'))
                        anchors.append({'node': first['id'], 'lat': first['lat'], 'lon': first['lon'], 'section': row,
                                        'iso': source})
                continue
            for d in devices:
                if kind == 'traffic_signals':
                    red_lights.add(d['ref'])
                if start and d['ref'] in nodes:
                    n = nodes[d['ref']]
                    if geo.haversine_m(start[0], start[1], n['lat'], n['lon']) > 15:
                        directions[d['ref']] = round(geo.bearing_deg(start[0], start[1], n['lat'], n['lon']))
                if kind in ('maxspeed', 'traffic_signals') and d['ref'] in nodes:
                    nodes[d['ref']].setdefault('tags', {}).setdefault('highway', 'speed_camera')
                    if kind == 'maxspeed' and tags.get('maxspeed'):
                        nodes[d['ref']]['tags'].setdefault('maxspeed', tags['maxspeed'])

        kept = 0
        for n in nodes.values():
            tags = n.get('tags', {})
            if tags.get('highway') != 'speed_camera' or n['id'] in points:
                continue
            if not admissible(n['lat'], n['lon']):
                continue
            kind = 1 if n['id'] in red_lights else 0
            points[n['id']] = [round(n['lat'], 5), round(n['lon'], 5), kind,
                               parse_maxspeed(tags.get('maxspeed')), directions.get(n['id'], -1)]
            anchors.append({'node': n['id'], 'lat': n['lat'], 'lon': n['lon'], 'point': points[n['id']],
                            'directionTag': tags.get('direction') or tags.get('camera:direction'), 'iso': source})
            kept += 1
        stats[source] = kept

    (OUT / 'anchors.json').write_text(json.dumps(anchors), encoding='utf-8')
    paths_path = OUT / 'paths.json'
    paths = json.loads(paths_path.read_text(encoding='utf-8')) if paths_path.exists() else {}
    zones_path = OUT / 'fr_zones.json'
    zones = json.loads(zones_path.read_text(encoding='utf-8')) if zones_path.exists() else []
    point_list = sorted(points.values())
    section_list = sorted(sections)
    # Anfahrtswege (build_approaches.py): je Blitzer bzw. Abschnittsbeginn ein oder zwei Linienzüge entlang der Straße,
    # in Fahrtrichtung, der letzte Punkt liegt beim Blitzer. Ohne Anfahrtsweg warnt die App nicht.
    path_rows = []
    for i, p in enumerate(point_list):
        for line in paths.get(f'p:{p[0]},{p[1]}', []):
            path_rows.append([i, line])
    for i, sct in enumerate(section_list):
        for line in paths.get(f's:{sct[0]},{sct[1]},{sct[2]},{sct[3]}', []):
            path_rows.append([-1 - i, line])
    pack = {
        'schema': 2,
        'dataDate': datetime.date.today().isoformat(),
        'license': 'ODbL 1.0',
        'attribution': '© OpenStreetMap-Mitwirkende, https://www.openstreetmap.org/copyright',
        'countries': sorted(c for c, s in states.items() if s in ('allowed', 'allowedWithNotice', 'zonesOnly')),
        'fields': {'points': ['lat', 'lon', 'kind(0 fest,1 Rotlicht)', 'maxspeed', 'richtung(-1 beide)'],
                   'sections': ['latStart', 'lonStart', 'latEnd', 'lonEnd', 'maxspeed', 'laengeM'],
                   'zones': 'Linienzug [[lat,lon],...] je Gefahrenzone in Frankreich',
                   'paths': '[Bezug (Punkt-Index, oder -1-Abschnitts-Index), [lat,lon,lat,lon,...]] Anfahrt in Fahrtrichtung'},
        'points': point_list,
        'sections': section_list,
        'paths': path_rows,
        'zones': zones,
    }
    text = json.dumps(pack, ensure_ascii=False, separators=(',', ':'))
    (OUT / 'speedtraps_v1.json').write_text(text, encoding='utf-8')
    print('Punkte je Land:', stats)
    print('Punkte gesamt:', len(points), '| Abschnitte:', len(sections), '| Zonen:', len(zones), '| Anfahrten:', len(path_rows),
          '| Grösse:', round(len(text) / 1e6, 2), 'MB')


if __name__ == '__main__':
    main()
