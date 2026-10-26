#!/usr/bin/env python3
"""Lädt die OSM-Blitzer der Länder, für die Tespit Daten zeigt (Plan vom 22.10.2026).

Nur erlaubte Länder, Deutschland (mit Hinweis) und Frankreich (nur für Gefahrenzonen).
Gesperrte Länder werden nie abgefragt. Ergebnis: raw/osm_<ISO>.json
Aufruf: fetch_osm.py [--neu] [ISO …]   (--neu lädt auch vorhandene Länder neu, wöchentlicher Lauf;
eine Datei wird erst nach erfolgreichem Laden ersetzt, Exit-Code 1, wenn ein Land scheitert)
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

B = Path(__file__).resolve().parent
RAW = B / 'raw'
# Hauptserver und ein zweiter öffentlicher Server; die Versuche wechseln sich ab (der Hauptserver ist oft voll).
URLS = ['https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter']
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


def fetch(iso, again=False):
    target = RAW / f'osm_{iso}.json'
    if not again and target.exists() and target.stat().st_size > 100:
        return iso, 'vorhanden', target.stat().st_size
    data = urllib.parse.urlencode({'data': QUERY.format(iso=iso)}).encode()
    request = lambda attempt: urllib.request.Request(URLS[attempt % len(URLS)], data=data, headers={'User-Agent': 'Tespit-Kartendaten/1 (wöchentlich, github.com/gena3ekiller/tespit-map-data)'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request(attempt), timeout=1000) as reply:
                body = reply.read()
            if not json.loads(body).get('elements'):
                raise ValueError('leer')
            temporary = target.with_suffix('.tmp')
            temporary.write_bytes(body)
            temporary.replace(target)
            return iso, 'ok', len(body)
        except Exception as error:  # noqa: BLE001
            print(f'{iso}: Versuch {attempt + 1} fehlgeschlagen: {error}', flush=True)
            time.sleep(60 * (attempt + 1))
    return iso, 'fehlgeschlagen', 0


if __name__ == '__main__':
    RAW.mkdir(exist_ok=True)
    again = '--neu' in sys.argv
    failed = []
    for iso in ([a for a in sys.argv[1:] if not a.startswith('--')] or COUNTRIES):
        result = fetch(iso, again)
        print(*result, flush=True)
        if result[1] == 'fehlgeschlagen':
            failed.append(iso)
        time.sleep(5)
    sys.exit(1 if failed else 0)
