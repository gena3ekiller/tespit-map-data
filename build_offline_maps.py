#!/usr/bin/env python3
"""Builds the worldwide offline map packages for the Tespit apps (1.1.22).

Esat, 17.11.2026: "Eigene OSM-Pakete", "mit allen Details", "für alle Kontinente". Runs in GitHub Actions
(`.github/workflows/offline-maps.yml`): about 140 GB of map data, too much for a home connection.

Every country of a continent is cut out of the newest Protomaps planet build (OpenStreetMap data, ODbL; Protomaps
basemap schema v4) with all details (zoom 15). A package must stay below 1.9 GB (GitHub allows 2 GiB per release
file, and the phone must hold it): a larger country is split into its regions (Natural Earth admin 1, grouped by their
`region` where a country has many), a still larger region into halves of its bounding box. `pmtiles extract
--dry-run` tells the size before anything is downloaded.

Commands:
- `select`: the newest planet build with schema 4 (`key=…`, `date=…` for `$GITHUB_OUTPUT`).
- `build <continent> --planet KEY [--tag TAG] [--upload] [--only id,id]`: plans and extracts the continent's
  packages into `dist/offline/`; with `--upload` each package goes into the release TAG and is deleted locally. Writes
  `dist/offline/regions-<continent>.json`.
- `manifest --planet KEY`: merges the continents' region lists into `offline-maps.json` (repository root).
- `plan <continent> --planet KEY`: only the plan, with sizes (dry runs).

Needs the `pmtiles` command. Borders: Natural Earth admin 0 and admin 1 (public domain) in `raw/` (downloaded by the
workflow).
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

B = Path(__file__).resolve().parent
RAW = B / 'raw'
OUT = B / 'dist' / 'offline'
AREAS = OUT / 'areas'
BUILDS = 'https://build-metadata.protomaps.dev/builds.json'
PLANET = 'https://build.protomaps.com/{key}'
USER_AGENT = 'tespit-map-data offline map builder'
SCHEMA_MAJOR = '4.'
MAXZOOM = 15
LIMIT = 1_900_000_000
CONTINENTS = ['europe', 'asia', 'africa', 'north-america', 'south-america', 'oceania', 'antarctica']
# Natural Earth's names in other languages; keys as the apps' language codes.
NAME_LANGUAGES = {'ar': 'ar', 'bn': 'bn', 'de': 'de', 'en': 'en', 'es': 'es', 'fr': 'fr', 'el': 'el', 'hi': 'hi',
                  'hu': 'hu', 'id': 'id', 'it': 'it', 'ja': 'ja', 'ko': 'ko', 'nl': 'nl', 'pl': 'pl', 'pt': 'pt',
                  'ru': 'ru', 'sv': 'sv', 'tr': 'tr', 'vi': 'vi', 'zh': 'zh-Hans', 'zht': 'zh-Hant', 'he': 'he',
                  'uk': 'uk', 'ur': 'ur', 'fa': 'fa'}
# A country with this many states is first split into Natural Earth's larger `region` groups.
GROUP_FROM = 30


def log(*args):
    print(*args, flush=True)


def newest_build():
    request = urllib.request.Request(BUILDS, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        builds = json.load(response)
    usable = [b for b in builds if str(b.get('version', '')).startswith(SCHEMA_MAJOR) and b['key'].endswith('.pmtiles')]
    if not usable:
        sys.exit('no planet build with schema 4')
    return usable[-1]


def date_of(key):
    return f'{key[:4]}-{key[4:6]}-{key[6:8]}'


def slug(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')[:40] or 'x'


def continent_of(props):
    region, sub = props.get('REGION_UN'), props.get('SUBREGION')
    if region == 'Americas':
        return 'south-america' if sub == 'South America' else 'north-america'
    return {'Europe': 'europe', 'Asia': 'asia', 'Africa': 'africa', 'Oceania': 'oceania',
            'Antarctica': 'antarctica'}.get(region)


def country_code(props):
    for key in ('ISO_A2', 'ISO_A2_EH'):
        value = props.get(key) or ''
        if re.fullmatch(r'[A-Z]{2}', value):
            return value
    return None


def names(props, upper):
    out = {}
    for suffix, language in NAME_LANGUAGES.items():
        value = props.get(f'NAME_{suffix.upper()}' if upper else f'name_{suffix}')
        if isinstance(value, str) and value.strip():
            out[language] = value.strip()
    return out


def polygons(geometry):
    if geometry['type'] == 'Polygon':
        return [geometry['coordinates']]
    if geometry['type'] == 'MultiPolygon':
        return list(geometry['coordinates'])
    return []


def bbox_of(polys):
    xs = [p[0] for poly in polys for ring in poly for p in ring]
    ys = [p[1] for poly in polys for ring in poly for p in ring]
    return [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)]


def rectangle(box):
    """A box as MultiPolygon coordinates: one polygon with one ring (17.11.2026: one level less was invalid GeoJSON)."""
    w, s, e, n = box
    return [[[[w, s], [e, s], [e, n], [w, n], [w, s]]]]


class Planner:
    def __init__(self, planet, countries=None):
        self.planet = planet
        self.sizes = {}
        self.used = set()
        # Only these countries (ISO codes), for trying the plan out.
        self.countries = countries
        AREAS.mkdir(parents=True, exist_ok=True)

    def unique(self, area_id):
        """Natural Earth gives a few states the same ISO code (Jervis Bay and New South Wales): number the later ones."""
        candidate, n = area_id, 2
        while candidate in self.used:
            candidate, n = f'{area_id}-{n}', n + 1
        self.used.add(candidate)
        return candidate

    def area_file(self, area_id, polys):
        path = AREAS / f'{area_id}.geojson'
        path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {},
                        'geometry': {'type': 'MultiPolygon', 'coordinates': polys}}]}))
        return path

    def size(self, area_id, polys):
        """The archive size for the area, from a dry run (only the planet's directories are read)."""
        if area_id in self.sizes:
            return self.sizes[area_id]
        path = self.area_file(area_id, polys)
        # Three tries: a dry run reads the planet's directories over the network (17.11.2026: one failed silently).
        for attempt in range(3):
            result = subprocess.run(['pmtiles', 'extract', self.planet, str(OUT / 'dry.pmtiles'), f'--region={path}',
                                     f'--maxzoom={MAXZOOM}', '--dry-run'], capture_output=True, text=True)
            output = result.stdout + result.stderr
            match = re.search(r'archive size of (\d+(?:\.\d+)?) (B|kB|KB|MB|GB)', output)
            if result.returncode == 0 and match:
                break
            log(f'  dry run {area_id} attempt {attempt + 1} failed (exit {result.returncode}): {output[-800:]}')
            time.sleep(20 * (attempt + 1))
        else:
            sys.exit(f'dry run {area_id} failed three times')
        factor = {'B': 1, 'kB': 1e3, 'KB': 1e3, 'MB': 1e6, 'GB': 1e9}[match.group(2)]
        self.sizes[area_id] = float(match.group(1)) * factor
        return self.sizes[area_id]

    def split(self, entry, polys, depth=0):
        """Halves of the bounding box until every half fits; the halves are named by their side."""
        if self.size(entry['id'], polys) <= LIMIT * 0.97:
            return [dict(entry, polys=polys)]
        if depth >= 6:
            sys.exit(f"{entry['id']} still too large after splitting")
        w, s, e, n = bbox_of(polys)
        if (e - w) * 0.75 >= (n - s):
            middle = (w + e) / 2
            halves = [('w', [w, s, middle, n]), ('e', [middle, s, e, n])]
        else:
            middle = (s + n) / 2
            halves = [('s', [w, s, e, middle]), ('n', [w, middle, e, n])]
        out = []
        for side, box in halves:
            part = dict(entry, id=f"{entry['id']}-{side}", part=(entry.get('part', '') + side))
            out += self.split(part, rectangle(box), depth + 1)
        return out


def plan(continent, planner):
    countries = json.loads((RAW / 'ne_10m_admin_0_countries.geojson').read_text())['features']
    states = json.loads((RAW / 'ne_10m_admin_1_states_provinces.geojson').read_text())['features']
    entries = []
    for feature in sorted(countries, key=lambda f: f['properties']['NAME']):
        props = feature['properties']
        if continent_of(props) != continent:
            continue
        if planner.countries and (country_code(props) or '') not in planner.countries:
            continue
        code = country_code(props)
        polys = polygons(feature['geometry'])
        if not polys:
            continue
        # The id: the ISO code where Natural Earth gives the territory its own; otherwise its A3 code (France and
        # Norway carry their ISO code only as ISO_A2_EH, small territories share their state's, like Ashmore with AU).
        own_code = re.fullmatch(r'[A-Z]{2}', props.get('ISO_A2') or '') is not None
        country_id = planner.unique((props['ISO_A2'] if own_code else props['ADM0_A3']).lower())
        base = {'id': country_id, 'continent': continent, 'country': code or props['ADM0_A3'],
                'name': props['NAME'], 'names': names(props, upper=True), 'level': 'country'}
        size = planner.size(country_id, polys)
        log(f"  {country_id} {props['NAME']}: {size / 1e6:.0f} MB")
        if not own_code and size < 5e6:
            continue   # uninhabited specks without an ISO code of their own (reefs, buffer zones)
        if size <= LIMIT * 0.97:
            entries.append(dict(base, polys=polys))
            continue
        members = [s for s in states if s['properties'].get('adm0_a3') == props['ADM0_A3'] and polygons(s['geometry'])]
        if not members:
            entries += planner.split(base, polys)
            continue
        groups = {}
        grouped = len(members) >= GROUP_FROM and len({m['properties'].get('region') for m in members}) > 1
        for member in members:
            key = (member['properties'].get('region') or member['properties']['name']) if grouped else member['properties']['name']
            groups.setdefault(key, []).append(member)
        for key, group in sorted(groups.items()):
            entries += plan_group(country_id, base, key, group, planner)
    ids = [e['id'] for e in entries]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        sys.exit(f'duplicate ids: {sorted(duplicates)}')
    return entries


def state_id(country_id, props):
    code = (props.get('iso_3166_2') or '').lower()
    if re.fullmatch(r'[a-z]{2}-[a-z0-9]{1,3}', code):
        return code
    return f"{country_id}-{slug(props.get('name') or props.get('adm1_code') or 'x')}"


def plan_group(country_id, base, key, group, planner):
    """A region group, or a single state; a group too large falls apart into its states."""
    polys = [p for member in group for p in polygons(member['geometry'])]
    if len(group) == 1:
        props = group[0]['properties']
        entry = dict(base, id=planner.unique(state_id(country_id, props)), name=props['name'],
                     names=names(props, upper=False), level='region')
        return planner.split(entry, polys)
    entry = dict(base, id=planner.unique(f'{country_id}-{slug(key)}'), name=key, names={}, level='region')
    if planner.size(entry['id'], polys) <= LIMIT * 0.97:
        return [dict(entry, polys=polys)]
    out = []
    for member in group:
        props = member['properties']
        single = dict(base, id=planner.unique(state_id(country_id, props)), name=props['name'],
                      names=names(props, upper=False), level='region')
        out += planner.split(single, polygons(member['geometry']))
    return out


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def release_assets(tag):
    """The release's packages with size and SHA-256 (GitHub's digest), or None without the release."""
    result = subprocess.run(['gh', 'release', 'view', tag, '--json', 'assets'], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    assets = {}
    for asset in json.loads(result.stdout).get('assets', []):
        digest = asset.get('digest') or ''
        if digest.startswith('sha256:'):
            assets[asset['name']] = (asset['size'], digest.removeprefix('sha256:'))
    return assets


def build(args):
    planet = PLANET.format(key=args.planet)
    planner = Planner(planet)
    log('plan', args.continent, args.planet)
    entries = plan(args.continent, planner)
    only = set(args.only.split(',')) if args.only else None
    done_file = OUT / f'regions-{args.continent}.json'
    done = {r['id']: r for r in json.loads(done_file.read_text())} if done_file.exists() else {}
    uploaded = {}
    if args.upload:
        uploaded = release_assets(args.tag)
        if uploaded is None:
            subprocess.run(['gh', 'release', 'create', args.tag, '--latest=false', '--title', args.tag, '--notes',
                            'Tespit offline map packages (PMTiles, Protomaps basemap schema v4, zoom 0–15). '
                            'Data © OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).'],
                           check=True)
            uploaded = {}
    results = []
    for entry in entries:
        file_name = f"{entry['id']}.pmtiles"
        if only and entry['id'] not in only:
            continue
        if entry['id'] in done and (not args.upload or file_name in uploaded):
            results.append(done[entry['id']])
            continue
        if file_name in uploaded:
            # Already in the release from an earlier, interrupted run.
            size, digest = uploaded[file_name]
            record = {k: v for k, v in entry.items() if k != 'polys' and v not in ({}, None, '')}
            record.update(file=file_name, size=size, sha256=digest, bbox=bbox_of(entry['polys']), tag=args.tag)
            results.append(record)
            done[entry['id']] = record
            continue
        target = OUT / file_name
        area = planner.area_file(entry['id'], entry['polys'])
        log('extract', entry['id'])
        partial = OUT / f"{entry['id']}.partial"
        for attempt in range(3):
            result = subprocess.run(['pmtiles', 'extract', planet, str(partial), f'--region={area}',
                                     f'--maxzoom={MAXZOOM}', '--download-threads=4'], capture_output=True, text=True)
            if result.returncode == 0:
                break
            log(f"  extract {entry['id']} attempt {attempt + 1} failed (exit {result.returncode}): "
                f"{(result.stdout + result.stderr)[-800:]}")
            partial.unlink(missing_ok=True)
            time.sleep(30 * (attempt + 1))
        else:
            sys.exit(f"extract {entry['id']} failed three times")
        partial.replace(target)
        size = target.stat().st_size
        if size >= LIMIT:
            sys.exit(f"{entry['id']}: {size} bytes over the limit")
        record = {k: v for k, v in entry.items() if k != 'polys' and v not in ({}, None, '')}
        record.update(file=file_name, size=size, sha256=sha256(target), bbox=bbox_of(entry['polys']), tag=args.tag)
        if args.upload:
            subprocess.run(['gh', 'release', 'upload', args.tag, str(target), '--clobber'], check=True)
            target.unlink()
        results.append(record)
        done[entry['id']] = record
        done_file.write_text(json.dumps(list(done.values()), ensure_ascii=False))
        log(f"  {entry['id']}: {size / 1e6:.0f} MB")
    done_file.write_text(json.dumps(results, ensure_ascii=False))
    log(args.continent, len(results), 'packages', f"{sum(r['size'] for r in results) / 1e9:.1f} GB")


def manifest(args):
    """New continents replace theirs; the others stay as they are in the current manifest (a run may build only some)."""
    current = B / 'offline-maps.json'
    previous = json.loads(current.read_text())['regions'] if current.exists() else []
    regions = []
    for continent in CONTINENTS:
        path = OUT / f'regions-{continent}.json'
        if path.exists():
            regions += json.loads(path.read_text())
        else:
            regions += [r for r in previous if r.get('continent') == continent]
    if not regions:
        sys.exit('no regions')
    data = {
        'schema': 1,
        'enabled': True,
        'minAppVersion': '1.1.22',
        'dataDate': date_of(args.planet),
        # Each region also carries its own release tag: continents can come from different runs.
        'tiles': 'protomaps-basemap-v4',
        'maxzoom': MAXZOOM,
        'attribution': '© OpenStreetMap-Mitwirkende, https://www.openstreetmap.org/copyright',
        'regions': regions,
    }
    (B / 'offline-maps.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
    log('manifest', len(regions), 'regions', f"{sum(r['size'] for r in regions) / 1e9:.1f} GB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['select', 'plan', 'build', 'manifest'])
    parser.add_argument('continent', nargs='?', choices=CONTINENTS)
    parser.add_argument('--planet')
    parser.add_argument('--tag')
    parser.add_argument('--upload', action='store_true')
    parser.add_argument('--only')
    parser.add_argument('--countries', help='ISO codes, comma separated: plan only these (for trying it out)')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.command == 'select':
        build_info = newest_build()
        print(f"key={build_info['key']}")
        print(f"date={date_of(build_info['key'])}")
        return
    if not args.planet:
        sys.exit('--planet is needed')
    if args.command == 'manifest':
        manifest(args)
        return
    if not args.continent:
        sys.exit('a continent is needed')
    if args.command == 'plan':
        countries = set(args.countries.upper().split(',')) if args.countries else None
        entries = plan(args.continent, Planner(PLANET.format(key=args.planet), countries))
        for e in entries:
            log(e['id'], e['name'], e.get('part', ''))
        log(len(entries), 'packages')
        return
    if args.upload and not args.tag:
        sys.exit('--upload needs --tag')
    args.tag = args.tag or f'maps-{date_of(args.planet)}-{args.continent}'
    build(args)


if __name__ == '__main__':
    main()
