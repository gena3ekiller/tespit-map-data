#!/usr/bin/env python3
"""Veröffentlicht out/speedtraps_v1.json als Release und schreibt manifest.json (Datenweg 1.1.16).

- gzip ohne Zeitstempel und Namen: gleicher Inhalt ergibt dieselbe Datei und denselben SHA-256.
- Ein Release je Datenstand (Tag data-YYYY-MM-DD, bei mehreren am Tag .2, .3 …); vorhandene Releases werden
  nie überschrieben und bleiben mindestens 180 Tage stehen (ODbL).
- manifest.json enthält keine URLs; die App baut sie aus Tag und Dateiname.

publish.py            Release anlegen, manifest.json schreiben (danach committen und pushen)
publish.py --dry-run  nur dist/ und manifest.json schreiben
publish.py --off      Notabschaltung: enabled=false (die App löscht ihre Daten)
publish.py --on       wieder einschalten
publish.py --disable DE,AT / --enable DE   einzelne Länder abschalten oder wieder freigeben
"""
import argparse, gzip, hashlib, io, json, subprocess, sys
from pathlib import Path

B = Path(__file__).resolve().parent
REPO = 'gena3ekiller/tespit-map-data'
SOURCE = B / 'out' / 'speedtraps_v1.json'
DIST = B / 'dist'
FILE = 'speedtraps.json.gz'
MANIFEST = B / 'manifest.json'
MIN_APP_VERSION = '1.1.16'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def pack_gzip(raw):
    buffer = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', compresslevel=9, fileobj=buffer, mtime=0) as handle:
        handle.write(raw)
    return buffer.getvalue()


def load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding='utf-8'))
    return {'schema': 1, 'enabled': True, 'disabledCountries': [], 'minAppVersion': MIN_APP_VERSION, 'pack': None}


def write_manifest(manifest):
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('manifest.json:', json.dumps({k: v for k, v in manifest.items() if k != 'pack'}), manifest.get('pack', {}) and manifest['pack']['tag'])


def existing_tags():
    out = subprocess.run(['gh', 'release', 'list', '--repo', REPO, '--limit', '200', '--json', 'tagName'],
                         capture_output=True, text=True)
    return {r['tagName'] for r in json.loads(out.stdout or '[]')} if out.returncode == 0 else set()


def publish(dry_run):
    raw = SOURCE.read_bytes()
    root = json.loads(raw)
    if root.get('schema') != 2:
        sys.exit('Schema 2 erwartet')
    date = root['dataDate']
    packed = pack_gzip(raw)
    manifest = load_manifest()
    previous = manifest.get('pack') or {}
    if previous.get('unpackedSha256') == sha256(raw):
        print('Unverändert, kein neues Release:', previous.get('tag'))
        return
    tags = existing_tags()
    tag, n = f'data-{date}', 1
    while tag in tags:
        n += 1
        tag = f'data-{date}.{n}'
    DIST.mkdir(exist_ok=True)
    (DIST / FILE).write_bytes(packed)
    manifest['pack'] = {
        'tag': tag, 'file': FILE, 'size': len(packed), 'sha256': sha256(packed),
        'unpackedSize': len(raw), 'unpackedSha256': sha256(raw), 'dataDate': date,
    }
    if dry_run:
        write_manifest(manifest)
        return
    notes = (f'Speed camera data, OpenStreetMap as of {date}. {len(root["points"])} cameras, '
             f'{len(root["sections"])} sections, {len(root["zones"])} danger zones (France).\n\n'
             '© OpenStreetMap contributors, ODbL 1.0 — https://www.openstreetmap.org/copyright')
    subprocess.run(['gh', 'release', 'create', tag, str(DIST / FILE), '--repo', REPO,
                    '--title', f'Data {date}', '--notes', notes], check=True)
    write_manifest(manifest)
    print('Jetzt manifest.json committen und pushen.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--off', action='store_true')
    parser.add_argument('--on', action='store_true')
    parser.add_argument('--disable')
    parser.add_argument('--enable')
    args = parser.parse_args()
    if args.off or args.on or args.disable or args.enable:
        manifest = load_manifest()
        if args.off:
            manifest['enabled'] = False
        if args.on:
            manifest['enabled'] = True
        countries = set(manifest.get('disabledCountries', []))
        countries |= {c.strip().upper() for c in (args.disable or '').split(',') if c.strip()}
        countries -= {c.strip().upper() for c in (args.enable or '').split(',') if c.strip()}
        manifest['disabledCountries'] = sorted(countries)
        write_manifest(manifest)
        print('Jetzt manifest.json committen und pushen.')
        return
    publish(args.dry_run)


if __name__ == '__main__':
    main()
