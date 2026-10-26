#!/usr/bin/env python3
"""Lädt einmalig die OSM-Blitzer der Länder, für die Tespit Daten zeigt (Plan vom 22.10.2026).

Nur erlaubte Länder, Deutschland (mit Hinweis) und Frankreich (nur für Gefahrenzonen).
Gesperrte Länder werden nie abgefragt. Ergebnis: raw/osm_<ISO>.json
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

B = Path(__file__).resolve().parent
RAW = B / 'raw'
URL = 'https://overpass-api.de/api/interpreter'
COUNTRIES = ['AT', 'IT', 'ES', 'NL', 'BE', 'LU', 'PL', 'CZ', 'HU', 'DK', 'GB', 'XK', 'DE', 'FR']

QUERY = """[out:json][timeout:900];
area["ISO3166-1"="{iso}"][admin_level=2]->.a;
(
  node["highway"="speed_camera"](area.a);
  relation["type"="enforcement"](area.a);
);
out body;
>;
out skel qt;
"""


def fetch(iso):
    target = RAW / f'osm_{iso}.json'
    if target.exists() and target.stat().st_size > 100:
        return iso, 'vorhanden', target.stat().st_size
    data = urllib.parse.urlencode({'data': QUERY.format(iso=iso)}).encode()
    request = urllib.request.Request(URL, data=data, headers={'User-Agent': 'Tespit-Kartendaten/1 (einmaliger Aufbau)'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=1000) as reply:
                body = reply.read()
            json.loads(body)
            target.write_bytes(body)
            return iso, 'ok', len(body)
        except Exception as error:  # noqa: BLE001
            print(f'{iso}: Versuch {attempt + 1} fehlgeschlagen: {error}', flush=True)
            time.sleep(60 * (attempt + 1))
    return iso, 'fehlgeschlagen', 0


if __name__ == '__main__':
    RAW.mkdir(exist_ok=True)
    for iso in (sys.argv[1:] or COUNTRIES):
        print(*fetch(iso), flush=True)
        time.sleep(5)
