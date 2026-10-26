#!/usr/bin/env python3
"""Lädt einmalig die Straßen rund um jeden Blitzer und Abschnittsbeginn (für die Anfahrtswege, 25.10.2026).

Die App warnt nur noch, wenn das Auto auf dem Anfahrtsweg des Blitzers fährt, nicht mehr in einem Kegel.
Dafür braucht jeder Blitzer die Straße bis gut 1 km davor. Abgefragt wird je Kachel von 1° in Paketen von
höchstens 250 Blitzer-Knoten (ganze Länder lehnt Overpass ab); ein Paket, das scheitert, wird halbiert.
Ergebnis: raw/roads/<Kachel>_<Paket>.json (je Paket für sich vollständig, build_approaches.py liest sie einzeln).
Aufruf: fetch_roads.py [rueckwaerts]   (zweiter Lauf von hinten, Overpass erlaubt zwei Anfragen)
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

B = Path(__file__).resolve().parent
URL = 'https://overpass-api.de/api/interpreter'
CHUNK = 250
QUERY = """[out:json][timeout:600];
node(id:{ids})->.c;
way(around.c:1150)["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|road|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link)$"];
out body geom qt;
"""


def fetch(ids, attempts):
    data = urllib.parse.urlencode({'data': QUERY.format(ids=','.join(map(str, ids)))}).encode()
    request = urllib.request.Request(URL, data=data, headers={'User-Agent': 'Tespit-Kartendaten/1 (einmaliger Aufbau)'})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=900) as reply:
                return json.loads(reply.read())
        except Exception as error:  # noqa: BLE001
            print('  Versuch', attempt + 1, 'fehlgeschlagen:', error, flush=True)
            time.sleep(30 * (attempt + 1))
    return None


def fetch_chunk(ids):
    result = fetch(ids, 3 if len(ids) > 20 else 6)
    if result is not None:
        return result
    if len(ids) <= 20:
        raise SystemExit('Paket nicht ladbar')
    half = len(ids) // 2
    print(f'  halbiert ({len(ids)} Knoten)', flush=True)
    elements = {}
    for part in (ids[:half], ids[half:]):
        for element in fetch_chunk(part)['elements']:
            elements[element['id']] = element
        time.sleep(5)
    return {'elements': list(elements.values())}


if __name__ == '__main__':
    anchors = json.loads((B / 'out' / 'anchors.json').read_text(encoding='utf-8'))
    tiles = {}
    for a in anchors:
        tiles.setdefault((int(a['lat'] // 1), int(a['lon'] // 1)), set()).add(a['node'])
    jobs = []
    for (row, column), ids in sorted(tiles.items()):
        ids = sorted(ids)
        for k in range(0, len(ids), CHUNK):
            jobs.append((f'{row}_{column}_{k // CHUNK}', ids[k:k + CHUNK]))
    if 'rueckwaerts' in sys.argv:
        jobs.reverse()
    cache = B / 'raw' / 'roads'
    cache.mkdir(parents=True, exist_ok=True)
    for number, (name, ids) in enumerate(jobs, 1):
        part = cache / f'{name}.json'
        if part.exists() and part.stat().st_size > 0:
            continue
        print(f'Paket {number}/{len(jobs)} {name} ({len(ids)} Knoten)', flush=True)
        result = fetch_chunk(ids)
        tmp = part.with_suffix('.tmp')
        tmp.write_text(json.dumps(result), encoding='utf-8')
        tmp.replace(part)
        time.sleep(3)
    (cache / 'jobs.json').write_text(json.dumps([[n, i] for n, i in jobs]), encoding='utf-8')
    print('ok', len(jobs), 'Pakete')
