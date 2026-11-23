#!/usr/bin/env python3
"""Make the offline package picker outlines from the exact areas passed to pmtiles extract.

Use Shapely 2.1.2 (GEOS 3.13.1). Run `continent NAME` after building that continent,
then `merge` after assembling offline-maps.json. Neither command downloads tiles.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import build_offline_maps as producer
from build_offline_maps import AREAS, B, CONTINENTS, OUT, bbox_of, polygons


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n'
    temp = path.with_suffix('.tmp')
    temp.write_text(data, encoding='utf-8')
    temp.replace(path)


def polygon_parts(geometry):
    if geometry.geom_type == 'Polygon':
        return [geometry]
    if geometry.geom_type in ('MultiPolygon', 'GeometryCollection'):
        return [p for g in geometry.geoms for p in polygon_parts(g)]
    return []


def package_parts(row, geometry):
    from shapely import make_valid, union_all
    from shapely.geometry import shape

    if bbox_of(polygons(geometry)) != row['bbox']:
        raise ValueError(f"{row['id']} does not match the catalog bounds")
    multi = shape(geometry)
    if multi.is_valid:
        return list(multi.geoms)
    # Grouped regions are collections of adjacent provinces. Join their shared
    # interior edges. A few Natural Earth rings touch themselves at a point.
    pieces = [p for g in multi.geoms for p in polygon_parts(g if g.is_valid else make_valid(g))]
    return polygon_parts(union_all(pieces))


def simplify(rows, geometry_for):
    from shapely import coverage_simplify, from_wkt, orient_polygons, to_wkt
    from shapely.geometry import MultiPolygon, Polygon, mapping

    parts = []
    spans = {}
    packages = {}
    for row in rows:
        package_id = row['id']
        pieces = package_parts(row, geometry_for(package_id))
        if not pieces:
            raise ValueError(f'Empty extract area: {package_id}')
        if row.get('part'):
            # The producer extracts these full rectangles, including their real overlaps.
            packages[package_id] = MultiPolygon(pieces)
            continue
        start = len(parts)
        parts.extend(pieces)
        spans[package_id] = (start, len(parts))

    # Simplify matching boundaries together, so opposite sides of an edge keep the same vertices.
    simplified = coverage_simplify(parts, 0.035) if parts else []
    # VW can reduce a small island or enclave to a triangle that misses its town.
    # Keep these source rings intact and apply the same vertices to their neighbours.
    protected = set()
    for p in parts:
        for ring in [p.exterior, *p.interiors]:
            if Polygon(ring).area <= 0.025:
                protected.update(ring.coords)
            elif ring.bounds[1] == -90 or ring.bounds[3] == 90:
                # The polar closing edge follows the entire map extent. A shortcut
                # from -180 straight to +180 would wrap to zero width on some maps.
                protected.update((x, y) for x, y in ring.coords if abs(y) == 90)
    centres = [p.representative_point() for p in parts]
    hole_centres = [[Polygon(hole).representative_point() for hole in p.interiors] for p in parts]
    while True:
        invalid = []
        for package_id, (start, stop) in spans.items():
            restored = []
            for idx in range(start, stop):
                full, smaller = parts[idx], simplified[idx]
                if smaller.geom_type != 'Polygon' or len(full.interiors) != len(smaller.interiors):
                    raise ValueError(f'Island or hole lost in {package_id}')
                kept = {xy for ring in [smaller.exterior, *smaller.interiors] for xy in ring.coords}
                rings = [[xy for xy in ring.coords if xy in kept or xy in protected]
                         for ring in [full.exterior, *full.interiors]]
                piece = Polygon(rings[0], rings[1:])
                if (not piece.is_valid or not piece.covers(centres[idx])
                        or any(piece.covers(point) for point in hole_centres[idx])):
                    invalid.append(full)
                restored.append(piece)
            packages[package_id] = MultiPolygon(restored)
            if not packages[package_id].is_valid:
                invalid.extend(parts[start:stop])
        if not invalid:
            break
        # A retained island can meet a shortcut across its bay. Restore this package
        # and the corresponding shared vertices on its neighbours before checking again.
        before = len(protected)
        for p in invalid:
            for ring in [p.exterior, *p.interiors]:
                protected.update(ring.coords)
        if len(protected) == before:
            raise ValueError('Invalid topology in original extract polygons')

    features = []
    for row in rows:
        package_id = row['id']
        multi = orient_polygons(packages[package_id])
        # Five decimal places are about a metre at the equator. Keep full precision
        # if rounding would invalidate a tiny coastal feature or enclave.
        rounded = from_wkt(to_wkt(multi, rounding_precision=5))
        if not rounded.is_valid:
            rounded = multi
        if not rounded.is_valid or rounded.is_empty:
            raise ValueError(f'Invalid simplified polygon: {package_id}')
        features.append({'type': 'Feature', 'properties': {'id': package_id}, 'geometry': mapping(rounded)})
    return features


def write_collection(source, features, output):
    ids = [r['id'] for r in json.loads(source)['regions']]
    if len(set(ids)) != len(ids) or not set(ids).issubset(features):
        raise ValueError('Incomplete or duplicate package IDs in catalog/outline set')
    write(output, {'type': 'FeatureCollection', 'catalogSHA256': hashlib.sha256(source).hexdigest(),
                   'attribution': 'Boundaries made with Natural Earth (public domain), https://www.naturalearthdata.com/. '
                                  'Package catalog: © OpenStreetMap contributors, https://www.openstreetmap.org/copyright.',
                   'features': [features[i] for i in ids]})


def merge(catalog_path, stage, output):
    source = catalog_path.read_bytes()
    rows = json.loads(source)['regions']
    features = {f['properties']['id']: f for f in read(output)['features']} if output.exists() else {}
    for continent in CONTINENTS:
        if not (stage / f'regions-{continent}.json').exists():
            continue
        current = read(stage / f'areas-{continent}.geojson')['features']
        ids = [f['properties']['id'] for f in current]
        if len(ids) != len(set(ids)) or set(ids) != {r['id'] for r in rows if r['continent'] == continent}:
            raise ValueError(f'Outlines do not match the new {continent} catalog')
        features.update(zip(ids, current))
    write_collection(source, features, output)


def replay(catalog_path, output):
    """Rebuild extracts from a shipped catalog and its original Natural Earth input, without dry runs."""
    source = catalog_path.read_bytes()
    rows = json.loads(source)['regions']
    ids = {row['id'] for row in rows}
    countries = read(producer.RAW / 'ne_10m_admin_0_countries.geojson')['features']
    # The producer omits tiny territories without their own ISO code. Recognise a
    # published split parent through either its group ID or its named admin-1 children.
    members = {}
    for state in read(producer.RAW / 'ne_10m_admin_1_states_provinces.geojson')['features']:
        props = state['properties']
        members.setdefault(props['adm0_a3'], set()).update((props['name'], props.get('region')))
    omitted = set()
    for country in countries:
        props = country['properties']
        if re.fullmatch('[A-Z]{2}', props.get('ISO_A2') or ''):
            continue
        a3 = props['ADM0_A3']
        code = producer.country_code(props) or a3
        parent = a3.lower()
        if not any(row['id'] == parent or row['id'].startswith(parent + '-') or
                   (row['country'] == code and row['name'] in members.get(a3, ())) for row in rows):
            omitted.add(parent)

    class ShippedPlanner(producer.Planner):
        def __init__(self):
            self.countries = None
            self.used = set()

        def size(self, area_id, polys):
            if area_id in ids:
                return 6_000_000  # fits and is above the producer's uninhabited-speck threshold
            return 0 if area_id in omitted else producer.LIMIT * 2

    features = {}
    for continent in CONTINENTS:
        entries = {e['id']: e for e in producer.plan(continent, ShippedPlanner())}
        expected = [r for r in rows if r['continent'] == continent]
        if set(entries) != {r['id'] for r in expected}:
            raise ValueError(f'Cannot reproduce package IDs in {continent}')
        for row in expected:
            entry = entries[row['id']]
            if any(entry.get(k) != row.get(k) for k in ('name', 'country', 'level', 'part')):
                raise ValueError(f"Cannot reproduce the catalog entry for {row['id']}")
        def geometry(package_id):
            return {'type': 'MultiPolygon', 'coordinates': entries[package_id]['polys']}
        features.update((f['properties']['id'], f) for f in simplify(expected, geometry))
    write_collection(source, features, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    build = subs.add_parser('continent')
    build.add_argument('name', choices=CONTINENTS)
    build.add_argument('--areas', type=Path, default=AREAS)
    build.add_argument('--stage', type=Path, default=OUT)
    finalize = subs.add_parser('merge')
    finalize.add_argument('--catalog', type=Path, default=B / 'offline-maps.json')
    finalize.add_argument('--stage', type=Path, default=OUT)
    finalize.add_argument('--output', type=Path, default=B / 'package-areas.geojson')
    rebuild = subs.add_parser('replay')
    rebuild.add_argument('--catalog', type=Path, default=B / 'offline-maps.json')
    rebuild.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'continent':
        rows = read(args.stage / f'regions-{args.name}.json')
        def geometry(package_id):
            return read(args.areas / (package_id + '.geojson'))['features'][0]['geometry']
        features = simplify(rows, geometry)
        write(args.stage / f'areas-{args.name}.geojson', {'type': 'FeatureCollection', 'features': features})
    elif args.command == 'replay':
        replay(args.catalog, args.output)
    else:
        merge(args.catalog, args.stage, args.output)


if __name__ == '__main__':
    main()
