#!/usr/bin/env python3
"""Wöchentlicher Lauf (Esat, 26.10.2026): neue Blitzerdaten aus OpenStreetMap bauen, prüfen und veröffentlichen.

Läuft auf dem Mac (launchd, jede Nacht 03:17; gearbeitet wird nur, wenn die letzte Veröffentlichung mindestens
6 Tage her ist, so wird ein gescheiterter Montag am Dienstag nachgeholt), nicht auf GitHub: das Salz der Gefahrenzonen und die Straßen-Zwischenstände
(raw/roads, 2 GB) bleiben lokal, und Overpass bekommt nur die neuen Blitzer statt einer ganzen Nacht Abfragen.

Ablauf:
1. fetch_osm.py --neu        alle erlaubten Länder neu (scheitert eines: Abbruch, nichts wird veröffentlicht)
2. build_pack.py             Anker für die Anfahrtswege
3. fetch_roads.py            Straßen nur für neue Blitzer
4. build_approaches.py       Anfahrtswege
5. fetch_fr_roads.py         Straßen nur für französische Kacheln mit neuen Blitzern
6. build_zones.py            Gefahrenzonen (mit dem lokalen Salz)
7. build_pack.py             die fertige Datei
8. Gegenprobe                Mengen gegen die zuletzt veröffentlichte Datei (höchstens 15 % weniger), kein Punkt
                             in einem gesperrten Land oder bis 2 km davor, Zonen nur in Frankreich, Größe
9. publish.py                Release und manifest.json; dann commit und push
Jede Stufe schreibt nach logs/weekly-<Datum>.log. Mitteilung auf dem Mac bei Erfolg; bei einem Fehler erst, wenn
seit 9 Tagen nichts veröffentlicht wurde (Overpass ist manchmal tagelang voll, die Apps warnen erst nach 30 Tagen).

weekly.py            ganzer Lauf, sofern fällig (--jetzt: auch wenn nicht fällig)
weekly.py --pruefen  nur die Gegenprobe der vorhandenen out/speedtraps_v1.json
"""
import datetime, fcntl, json, subprocess, sys
from pathlib import Path

import geo

B = Path(__file__).resolve().parent
LOGS = B / 'logs'
PACK = B / 'out' / 'speedtraps_v1.json'
LAST = B / 'out' / 'published_stats.json'
PYTHON = sys.executable
MAX_DROP = 0.15
MIN_POINTS = 15_000
SUCCESS = LOGS / 'last_success.txt'
DUE_DAYS = 6
ALARM_DAYS = 9


def days_since_success():
    try:
        last = datetime.datetime.fromisoformat(SUCCESS.read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        return None
    return (datetime.datetime.now() - last).total_seconds() / 86_400


def notify(title, text):
    script = f'display notification {json.dumps(text)} with title {json.dumps(title)}'
    subprocess.run(['osascript', '-e', script], capture_output=True)


def run(log, *command):
    log.write(f'\n$ {" ".join(command)}\n')
    log.flush()
    result = subprocess.run(command, cwd=B, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f'{Path(command[1]).name if len(command) > 1 else command[0]} fehlgeschlagen ({result.returncode})')


def stats(pack):
    return {'points': len(pack['points']), 'sections': len(pack['sections']),
            'zones': len(pack['zones']), 'paths': len(pack['paths'])}


def verify(pack):
    """Gegenprobe der fertigen Datei; gibt die Mengen zurück oder wirft mit dem Grund."""
    countries = geo.load_borders()
    policy = geo.load_policy()
    states = policy['states']
    blocked = [c for c in countries if states.get(c['iso']) == 'blocked']
    band = policy['appAdmissionBlockedBandKm'] * 1000

    def state(lat, lon):
        iso = geo.country_at(lon, lat, countries)
        return states.get(iso, policy['default']) if iso else policy['default']

    def near_blocked(lat, lon):
        for c in blocked:
            limit = 10_500 if c['iso'] == 'CN' else band
            if geo.distance_to_country(lon, lat, c, limit) < limit:
                return True
        return False

    for lat, lon, *_ in pack['points']:
        if state(lat, lon) not in ('allowed', 'allowedWithNotice') or near_blocked(lat, lon):
            raise ValueError(f'Punkt außerhalb erlaubter Länder: {lat},{lon}')
    for la, lo, lb, lob, *_ in pack['sections']:
        for lat, lon in ((la, lo), (lb, lob)):
            if state(lat, lon) not in ('allowed', 'allowedWithNotice') or near_blocked(lat, lon):
                raise ValueError(f'Abschnitt außerhalb erlaubter Länder: {lat},{lon}')
    for zone in pack['zones']:
        if any(state(lat, lon) != 'zonesOnly' for lat, lon in zone):
            raise ValueError('Gefahrenzone außerhalb Frankreichs')
    current = stats(pack)
    if current['points'] < MIN_POINTS:
        raise ValueError(f'nur {current["points"]} Punkte')
    if LAST.exists():
        previous = json.loads(LAST.read_text(encoding='utf-8'))
        for key, value in current.items():
            if previous.get(key) and value < previous[key] * (1 - MAX_DROP):
                raise ValueError(f'{key}: {value} statt {previous[key]} (mehr als 15 % weniger)')
    return current


def main():
    LOGS.mkdir(exist_ok=True)
    if '--pruefen' in sys.argv:
        print(verify(json.loads(PACK.read_text(encoding='utf-8'))))
        return
    lock = open(B / '.weekly.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('Läuft schon.')
        return
    since = days_since_success()
    if '--jetzt' not in sys.argv and since is not None and since < DUE_DAYS:
        print(f'Nicht fällig (letzte Veröffentlichung vor {since:.1f} Tagen).')
        return
    today = datetime.date.today().isoformat()
    log_path = LOGS / f'weekly-{today}.log'
    with open(log_path, 'a', encoding='utf-8') as log:
        try:
            run(log, PYTHON, 'fetch_osm.py', '--neu')
            run(log, PYTHON, 'build_pack.py')
            run(log, PYTHON, 'fetch_roads.py')
            run(log, PYTHON, 'build_approaches.py')
            run(log, PYTHON, 'fetch_fr_roads.py')
            run(log, PYTHON, 'build_zones.py')
            run(log, PYTHON, 'build_pack.py')
            current = verify(json.loads(PACK.read_text(encoding='utf-8')))
            log.write(f'\nGegenprobe ok: {current}\n')
            run(log, PYTHON, 'publish.py')
            changed = subprocess.run(['git', 'diff', '--quiet', '--', 'manifest.json'], cwd=B).returncode != 0
            if changed:
                run(log, 'git', 'add', 'manifest.json')
                run(log, 'git', 'commit', '-m', f'Data {today}')
                run(log, 'git', 'push', 'origin', 'main')
            LAST.write_text(json.dumps(current), encoding='utf-8')
            SUCCESS.write_text(datetime.datetime.now().isoformat(timespec='seconds'), encoding='utf-8')
            log.write(f'\nfertig: {"veröffentlicht" if changed else "unverändert"}\n')
            notify('Tespit Blitzerdaten', f'{"Neu veröffentlicht" if changed else "Unverändert"}: '
                   f'{current["points"]} Blitzer, {current["zones"]} Zonen')
        except Exception as error:  # noqa: BLE001
            log.write(f'\nABBRUCH: {error}\n')
            if since is None or since >= ALARM_DAYS:
                notify('Tespit Blitzerdaten: nicht veröffentlicht', f'{error} – seit {since or 0:.0f} Tagen nichts neu, '
                       f'siehe logs/{log_path.name}')
            sys.exit(1)


if __name__ == '__main__':
    main()
