#!/usr/bin/env python3
"""Lädt einmalig die Straßen rund um die französischen Blitzer (für die Gefahrenzonen).

Radien nach der grössten nötigen Zonenhälfte: Autobahn 4 km (bis 80 % = 3,2 km),
ausserorts 2 km (1,6 km), innerorts 300 m (240 m). Ganz Frankreich in einer Abfrage ist für
Overpass zu gross, darum in Kacheln von 1° rund um die Blitzer aus raw/osm_FR.json.
Ergebnis: raw/osm_FR_roads.json (alle Kacheln zusammengeführt, jeder Weg einmal).
"""
import json, time, urllib.parse, urllib.request
from pathlib import Path

B = Path(__file__).resolve().parent
URL = 'https://overpass-api.de/api/interpreter'
TILE = 1.0
QUERY = """[out:json][timeout:600];
node["highway"="speed_camera"]({s},{w},{n},{e})->.c;
(
  way(around.c:3300)["highway"~"^(motorway|trunk|motorway_link|trunk_link)$"];
  way(around.c:1700)["highway"~"^(primary|secondary|tertiary|primary_link|secondary_link|tertiary_link)$"];
  way(around.c:350)["highway"~"^(unclassified|residential|living_street)$"];
);
out body geom qt;
"""


def fetch(query, attempts=5):
    data = urllib.parse.urlencode({'data': query}).encode()
    request = urllib.request.Request(URL, data=data, headers={'User-Agent': 'Tespit-Kartendaten/1 (einmaliger Aufbau)'})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=900) as reply:
                return json.loads(reply.read())
        except Exception as error:  # noqa: BLE001
            print('  Versuch', attempt + 1, 'fehlgeschlagen:', error, flush=True)
            time.sleep(30 * (attempt + 1))
    return None


def fetch_tile(s, w, size):
    """Eine Kachel; zu grosse (Paris) werden geviertelt, bis Overpass sie liefert."""
    result = fetch(QUERY.format(s=s, w=w, n=s + size, e=w + size), attempts=3 if size > 0.2 else 5)
    if result is not None:
        return result
    if size <= 0.2:
        raise SystemExit('Kachel nicht ladbar')
    half = size / 2
    elements = {}
    for ds in (0, half):
        for dw in (0, half):
            print(f'  Viertel ({s + ds}, {w + dw}, {half}°)', flush=True)
            for element in fetch_tile(s + ds, w + dw, half)['elements']:
                elements[element['id']] = element
            time.sleep(5)
    return {'elements': list(elements.values())}


if __name__ == '__main__':
    cams = [e for e in json.loads((B / 'raw' / 'osm_FR.json').read_text(encoding='utf-8'))['elements']
            if e['type'] == 'node' and e.get('tags', {}).get('highway') == 'speed_camera']
    tiles = sorted({(int(c['lat'] // TILE), int(c['lon'] // TILE)) for c in cams})
    if 'rueckwaerts' in __import__('sys').argv:   # zweiter Lauf von hinten, Overpass erlaubt zwei Anfragen
        tiles.reverse()
    cache = B / 'raw' / 'fr_roads_tiles'
    cache.mkdir(exist_ok=True)
    ways = {}
    for number, (row, column) in enumerate(tiles, 1):
        part = cache / f'{row}_{column}.json'
        if not part.exists() or part.stat().st_size == 0:
            s, w = row * TILE, column * TILE
            print(f'Kachel {number}/{len(tiles)} ({s}, {w})', flush=True)
            result = fetch_tile(s, w, TILE)
            part.write_text(json.dumps(result), encoding='utf-8')
            time.sleep(5)
        for element in json.loads(part.read_text(encoding='utf-8'))['elements']:
            ways[element['id']] = element
    (B / 'raw' / 'osm_FR_roads.json').write_text(json.dumps({'elements': list(ways.values())}), encoding='utf-8')
    print('ok', len(tiles), 'Kacheln,', len(ways), 'Wege')
