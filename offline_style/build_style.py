#!/usr/bin/env python3
"""Builds the Tespit offline map style (light and dark) for MapLibre Native.

The tiles are the Protomaps basemap (OpenStreetMap data, ODbL; schema v4). The colours follow the OpenStreetMap
standard map (openstreetmap-carto, CC0), so the offline map looks like the map on openstreetmap.org. Only text labels,
no sprites: the apps bundle the glyphs and nothing else.

Placeholders the apps fill in at run time:
- `{GLYPHS}`: the folder holding `<fontstack>/<range>.pbf` (file URL on iOS, asset URL on Android).
- `{LANG}`: the label language (`de`, `en`, ...); labels fall back to the local name.
- Every layer but the background uses the source `osm`. The apps copy those layers once per downloaded region
  (`<id>#<region>`, source `<region>`), layer by layer, so the drawing order stays the same with several regions.

Output: `out/tespit-osm-light.json`, `out/tespit-osm-dark.json`. Run: `python3 build_style.py`.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'out'

# openstreetmap-carto colours (CC0); the dark set is Tespit's own night version of them.
LIGHT = {
    'water': '#aad3df', 'land': '#f2efe9', 'residential': '#e0dfdf', 'commercial': '#f2dad9',
    'retail': '#ffd6d1', 'industrial': '#ebdbe8', 'park': '#c8facc', 'grass': '#cdebb0', 'wood': '#add19e',
    'farmland': '#eef0d5', 'scrub': '#c8d7ab', 'cemetery': '#aacbaf', 'hospital': '#ffffe5', 'school': '#ffffe5',
    'glacier': '#ddecec', 'sand': '#f5e9c6', 'beach': '#fff1ba', 'military': '#f3e3dd', 'aerodrome': '#e9e7e2',
    'pedestrian': '#dddde8', 'building': '#d9d0c9', 'building_outline': '#c4b6ab',
    'motorway': '#e892a2', 'motorway_casing': '#dc2a67', 'trunk': '#f9b29c', 'trunk_casing': '#c84e2f',
    'primary': '#fcd6a4', 'primary_casing': '#a06b00', 'secondary': '#f7fabf', 'secondary_casing': '#707d05',
    'tertiary': '#ffffff', 'tertiary_casing': '#8f8f8f', 'minor': '#ffffff', 'minor_casing': '#bbbbbb',
    'service': '#ffffff', 'path': '#fa8072', 'track': '#996600', 'rail': '#707070', 'rail_dash': '#ffffff',
    'tunnel_fill': '#f5f2ee', 'boundary': '#8d618b', 'text': '#222222', 'text_halo': '#ffffff',
    'road_text': '#333333', 'water_text': '#4d80b3', 'place_text': '#000000', 'ref_text': '#222222',
    'ref_background': '#ffffff', 'runway': '#bbbbcc',
}
DARK = {
    'water': '#1b2c3c', 'land': '#202124', 'residential': '#28292d', 'commercial': '#2d2729', 'retail': '#30272a',
    'industrial': '#2b2630', 'park': '#1f3326', 'grass': '#22331f', 'wood': '#1c2e1d', 'farmland': '#252720',
    'scrub': '#232b1f', 'cemetery': '#1f2d22', 'hospital': '#2d2d25', 'school': '#2d2d25', 'glacier': '#2a3236',
    'sand': '#302c22', 'beach': '#322e20', 'military': '#2e2826', 'aerodrome': '#28282b', 'pedestrian': '#2a2a33',
    'building': '#34343a', 'building_outline': '#2b2b30',
    'motorway': '#b8566e', 'motorway_casing': '#5e1f31', 'trunk': '#b37356', 'trunk_casing': '#5a2c1c',
    'primary': '#a68a5c', 'primary_casing': '#4d3a14', 'secondary': '#8c8f63', 'secondary_casing': '#3f4214',
    'tertiary': '#5c5e66', 'tertiary_casing': '#2a2b30', 'minor': '#4a4c53', 'minor_casing': '#2a2b30',
    'service': '#43454b', 'path': '#9c5b55', 'track': '#7a5a2e', 'rail': '#6b6b70', 'rail_dash': '#2c2c30',
    'tunnel_fill': '#2a2b2f', 'boundary': '#9c7a9b', 'text': '#e6e6e6', 'text_halo': '#121214',
    'road_text': '#d6d6d6', 'water_text': '#7fa7cc', 'place_text': '#f2f2f2', 'ref_text': '#f0f0f0',
    'ref_background': '#3a3b40', 'runway': '#3d3d47',
}

SOURCE = 'osm'
NAME = ['coalesce', ['get', 'name:{LANG}'], ['get', 'name']]
# One font for every label: Noto Sans Regular covers nearly every script of the world in 6 MB of glyphs (Chinese,
# Japanese and Korean are drawn by MapLibre with the phone's own fonts). Medium and italic would triple that.
# Folder name without spaces, so the glyph URLs need no escaping (file URLs on iOS, asset URLs on Android).
REGULAR = MEDIUM = ITALIC = ['NotoSans-Regular']


def width(*stops):
    """Line width by zoom, growing exponentially like the road widths on openstreetmap.org."""
    return ['interpolate', ['exponential', 1.6], ['zoom'], *[v for stop in stops for v in stop]]


def fill(layer_id, source_layer, color, flt=None, minzoom=None, opacity=None):
    layer = {'id': layer_id, 'type': 'fill', 'source': SOURCE, 'source-layer': source_layer,
             'paint': {'fill-color': color}}
    if flt is not None:
        layer['filter'] = flt
    if minzoom is not None:
        layer['minzoom'] = minzoom
    if opacity is not None:
        layer['paint']['fill-opacity'] = opacity
    return layer


def line(layer_id, flt, color, line_width, minzoom=None, dash=None, cap='round', opacity=None, maxzoom=None):
    layer = {'id': layer_id, 'type': 'line', 'source': SOURCE, 'source-layer': 'roads', 'filter': flt,
             'layout': {'line-cap': cap, 'line-join': 'round'},
             'paint': {'line-color': color, 'line-width': line_width}}
    if minzoom is not None:
        layer['minzoom'] = minzoom
    if maxzoom is not None:
        layer['maxzoom'] = maxzoom
    if dash is not None:
        layer['paint']['line-dasharray'] = dash
    if opacity is not None:
        layer['paint']['line-opacity'] = opacity
    return layer


# Road widths (fill; the casing adds a border on both sides).
MOTORWAY_W = width((5, 0.8), (10, 2.2), (13, 5), (16, 14), (19, 40))
MAJOR_W = width((7, 0.5), (10, 1.4), (13, 4), (16, 12), (19, 34))
MINOR_W = width((12, 0.6), (14, 2.2), (16, 7), (19, 24))
SERVICE_W = width((14, 0.8), (16, 3.5), (19, 12))
LINK_W = width((12, 0.8), (14, 2.2), (16, 6), (19, 18))
PATH_W = width((14, 0.6), (17, 1.6), (19, 3))


def casing(w, extra):
    """The casing is the road's width plus a border that grows with the zoom."""
    return ['+', w, ['interpolate', ['linear'], ['zoom'], 10, extra * 0.5, 16, extra * 2]]


def roads(c, prefix, base_filter, tunnel=False):
    """Casings first, then fills, for one level (tunnel, ground or bridge)."""
    major_color = ['match', ['get', 'kind_detail'], 'trunk', c['trunk'], 'primary', c['primary'],
                   'secondary', c['secondary'], 'tertiary', c['tertiary'], c['primary']]
    major_casing = ['match', ['get', 'kind_detail'], 'trunk', c['trunk_casing'], 'primary', c['primary_casing'],
                    'secondary', c['secondary_casing'], 'tertiary', c['tertiary_casing'], c['primary_casing']]
    is_service = ['in', ['get', 'kind_detail'], ['literal', ['service', 'driveway', 'parking_aisle', 'alley']]]
    minor = ['all', base_filter, ['==', ['get', 'kind'], 'minor_road'], ['!', is_service], ['!', ['has', 'is_link']]]
    service = ['all', base_filter, ['==', ['get', 'kind'], 'minor_road'], is_service]
    major = ['all', base_filter, ['==', ['get', 'kind'], 'major_road'], ['!', ['has', 'is_link']]]
    highway = ['all', base_filter, ['==', ['get', 'kind'], 'highway'], ['!', ['has', 'is_link']]]
    link = ['all', base_filter, ['has', 'is_link']]
    link_color = ['case', ['==', ['get', 'kind'], 'highway'], c['motorway'], major_color]
    link_casing = ['case', ['==', ['get', 'kind'], 'highway'], c['motorway_casing'], major_casing]
    dash = [2, 1] if tunnel else None
    fill_of = (lambda color: c['tunnel_fill']) if tunnel else (lambda color: color)
    return [
        line(f'{prefix}_service_casing', service, c['minor_casing'], casing(SERVICE_W, 0.6), minzoom=14, dash=dash),
        line(f'{prefix}_minor_casing', minor, c['minor_casing'], casing(MINOR_W, 0.8), minzoom=12, dash=dash),
        line(f'{prefix}_link_casing', link, link_casing, casing(LINK_W, 0.8), minzoom=12, dash=dash),
        line(f'{prefix}_major_casing', major, major_casing, casing(MAJOR_W, 0.9), minzoom=8, dash=dash),
        line(f'{prefix}_motorway_casing', highway, c['motorway_casing'], casing(MOTORWAY_W, 1), minzoom=6, dash=dash),
        line(f'{prefix}_service', service, fill_of(c['service']), SERVICE_W, minzoom=14),
        line(f'{prefix}_minor', minor, fill_of(c['minor']), MINOR_W, minzoom=12),
        line(f'{prefix}_link', link, fill_of(link_color), LINK_W, minzoom=12),
        line(f'{prefix}_major', major, fill_of(major_color), MAJOR_W, minzoom=7),
        line(f'{prefix}_motorway', highway, fill_of(c['motorway']), MOTORWAY_W, minzoom=5),
    ]


def style(c, name):
    no_tunnel_bridge = ['all', ['!', ['has', 'is_tunnel']], ['!', ['has', 'is_bridge']]]
    landuse = [
        ('residential', ['residential', 'neighbourhood'], c['residential']),
        ('commercial', ['commercial'], c['commercial']),
        ('retail', ['retail'], c['retail']),
        ('industrial', ['industrial', 'railway', 'brownfield'], c['industrial']),
        ('farmland', ['farmland', 'farm', 'orchard', 'vineyard', 'meadow'], c['farmland']),
        ('grass', ['grass', 'grassland', 'village_green', 'recreation_ground', 'allotments', 'playground',
                   'garden', 'golf_course'], c['grass']),
        ('park', ['park', 'national_park', 'protected_area', 'nature_reserve', 'zoo'], c['park']),
        ('wood', ['wood', 'forest'], c['wood']),
        ('scrub', ['scrub', 'heath'], c['scrub']),
        ('cemetery', ['cemetery', 'grave_yard'], c['cemetery']),
        ('hospital', ['hospital'], c['hospital']),
        ('school', ['school', 'university', 'college', 'kindergarten'], c['school']),
        ('glacier', ['glacier'], c['glacier']),
        ('sand', ['sand', 'bare_rock', 'scree'], c['sand']),
        ('beach', ['beach'], c['beach']),
        ('military', ['military', 'naval_base', 'airfield'], c['military']),
        ('aerodrome', ['aerodrome'], c['aerodrome']),
        ('pedestrian', ['pedestrian', 'dam', 'pier', 'platform'], c['pedestrian']),
    ]
    layers = [
        {'id': 'background', 'type': 'background', 'paint': {'background-color': c['water']}},
        fill('earth', 'earth', c['land']),
        fill('landcover_wood', 'landcover', c['wood'], ['in', ['get', 'kind'], ['literal', ['forest']]], opacity=0.6),
        fill('landcover_grass', 'landcover', c['grass'], ['in', ['get', 'kind'], ['literal', ['grassland', 'scrub']]],
             opacity=0.6),
        fill('landcover_glacier', 'landcover', c['glacier'], ['==', ['get', 'kind'], 'glacier']),
        fill('landcover_farmland', 'landcover', c['farmland'], ['==', ['get', 'kind'], 'farmland'], opacity=0.6),
        fill('landcover_urban', 'landcover', c['residential'], ['==', ['get', 'kind'], 'urban_area'], opacity=0.6),
    ]
    layers += [fill(f'landuse_{key}', 'landuse', color, ['in', ['get', 'kind'], ['literal', kinds]])
               for key, kinds, color in landuse]
    layers += [
        fill('landuse_runway', 'landuse', c['runway'], ['in', ['get', 'kind'], ['literal', ['runway', 'taxiway']]]),
        fill('water', 'water', c['water'], ['==', ['geometry-type'], 'Polygon']),
        {'id': 'water_river', 'type': 'line', 'source': SOURCE, 'source-layer': 'water', 'minzoom': 9,
         'filter': ['in', ['get', 'kind'], ['literal', ['river', 'canal']]],
         'layout': {'line-cap': 'round', 'line-join': 'round'},
         'paint': {'line-color': c['water'], 'line-width': width((9, 0.8), (13, 2.5), (16, 8), (19, 20))}},
        {'id': 'water_stream', 'type': 'line', 'source': SOURCE, 'source-layer': 'water', 'minzoom': 13,
         'filter': ['in', ['get', 'kind'], ['literal', ['stream', 'ditch', 'drain']]],
         'layout': {'line-cap': 'round', 'line-join': 'round'},
         'paint': {'line-color': c['water'], 'line-width': width((13, 0.6), (16, 2), (19, 5))}},
    ]
    layers += roads(c, 'tunnel', ['has', 'is_tunnel'], tunnel=True)
    layers += [
        {'id': 'buildings', 'type': 'fill', 'source': SOURCE, 'source-layer': 'buildings', 'minzoom': 14,
         'filter': ['in', ['get', 'kind'], ['literal', ['building', 'building_part']]],
         'paint': {'fill-color': c['building'], 'fill-outline-color': c['building_outline'],
                   'fill-opacity': ['interpolate', ['linear'], ['zoom'], 14, 0.4, 16, 1]}},
        line('path', ['all', no_tunnel_bridge, ['==', ['get', 'kind'], 'path']], c['path'], PATH_W, minzoom=14,
             dash=[2, 1.5], cap='butt'),
        line('track', ['all', no_tunnel_bridge, ['==', ['get', 'kind_detail'], 'track']], c['track'], PATH_W,
             minzoom=13, dash=[3, 1.5], cap='butt'),
        line('runway', ['==', ['get', 'kind_detail'], 'runway'], c['runway'], width((10, 2), (14, 10), (17, 40)),
             minzoom=10, cap='butt'),
    ]
    layers += roads(c, 'road', no_tunnel_bridge)
    layers += [
        line('rail', ['all', ['==', ['get', 'kind'], 'rail'], ['!', ['has', 'is_tunnel']]], c['rail'],
             width((8, 0.5), (13, 1.6), (17, 3.5)), minzoom=8, cap='butt'),
        line('rail_dash', ['all', ['==', ['get', 'kind'], 'rail'], ['!', ['has', 'is_tunnel']]], c['rail_dash'],
             width((13, 0.8), (17, 2)), minzoom=13, dash=[3, 3], cap='butt'),
    ]
    layers += roads(c, 'bridge', ['has', 'is_bridge'])
    layers += [
        {'id': 'boundaries_country', 'type': 'line', 'source': SOURCE, 'source-layer': 'boundaries',
         'filter': ['<=', ['get', 'kind_detail'], 2], 'layout': {'line-join': 'round'},
         'paint': {'line-color': c['boundary'], 'line-width': width((3, 0.8), (10, 2), (15, 4)),
                   'line-dasharray': [4, 2], 'line-opacity': 0.8}},
        {'id': 'boundaries_region', 'type': 'line', 'source': SOURCE, 'source-layer': 'boundaries', 'minzoom': 6,
         'filter': ['all', ['>', ['get', 'kind_detail'], 2], ['<=', ['get', 'kind_detail'], 4]],
         'layout': {'line-join': 'round'},
         'paint': {'line-color': c['boundary'], 'line-width': width((6, 0.5), (12, 1.2)),
                   'line-dasharray': [3, 2], 'line-opacity': 0.5}},
        # Labels: water, roads, road numbers, places (drawn last, so places win the space).
        {'id': 'label_water', 'type': 'symbol', 'source': SOURCE, 'source-layer': 'water',
         'filter': ['all', ['in', ['get', 'kind'], ['literal', ['lake', 'water', 'sea', 'ocean', 'bay']]],
                    ['has', 'name']],
         'layout': {'text-field': NAME, 'text-font': ITALIC, 'text-size': 13, 'text-max-width': 7},
         'paint': {'text-color': c['water_text'], 'text-halo-color': c['text_halo'], 'text-halo-width': 1.2}},
        {'id': 'label_river', 'type': 'symbol', 'source': SOURCE, 'source-layer': 'water', 'minzoom': 13,
         'filter': ['in', ['get', 'kind'], ['literal', ['river', 'canal', 'stream']]],
         'layout': {'text-field': NAME, 'text-font': ITALIC, 'text-size': 12, 'symbol-placement': 'line'},
         'paint': {'text-color': c['water_text'], 'text-halo-color': c['text_halo'], 'text-halo-width': 1.2}},
        {'id': 'label_roads', 'type': 'symbol', 'source': SOURCE, 'source-layer': 'roads', 'minzoom': 13,
         'filter': ['in', ['get', 'kind'], ['literal', ['major_road', 'minor_road', 'highway']]],
         'layout': {'text-field': NAME, 'text-font': REGULAR, 'symbol-placement': 'line',
                    'text-size': ['interpolate', ['linear'], ['zoom'], 13, 10, 17, 14],
                    'symbol-sort-key': ['get', 'min_zoom']},
         'paint': {'text-color': c['road_text'], 'text-halo-color': c['text_halo'], 'text-halo-width': 1.5}},
        {'id': 'label_road_refs', 'type': 'symbol', 'source': SOURCE, 'source-layer': 'roads', 'minzoom': 8,
         'filter': ['all', ['in', ['get', 'kind'], ['literal', ['highway', 'major_road']]], ['has', 'ref'],
                    ['<=', ['length', ['get', 'ref']], 6]],
         'layout': {'text-field': ['get', 'ref'], 'text-font': MEDIUM, 'text-size': 11,
                    'symbol-placement': 'line', 'symbol-spacing': 400, 'text-rotation-alignment': 'viewport'},
         'paint': {'text-color': c['ref_text'], 'text-halo-color': c['ref_background'], 'text-halo-width': 3}},
        {'id': 'label_subplaces', 'type': 'symbol', 'source': SOURCE, 'source-layer': 'places', 'minzoom': 12,
         'filter': ['in', ['get', 'kind'], ['literal', ['neighbourhood', 'macrohood']]],
         'layout': {'text-field': NAME, 'text-font': REGULAR, 'text-size': 11, 'text-transform': 'uppercase',
                    'text-letter-spacing': 0.08, 'text-max-width': 7},
         'paint': {'text-color': c['text'], 'text-halo-color': c['text_halo'], 'text-halo-width': 1.2,
                   'text-opacity': 0.75}},
        {'id': 'label_localities', 'type': 'symbol', 'source': SOURCE, 'source-layer': 'places',
         'filter': ['==', ['get', 'kind'], 'locality'],
         'layout': {'text-field': NAME, 'text-font': MEDIUM, 'text-max-width': 8,
                    'symbol-sort-key': ['-', 20, ['coalesce', ['get', 'population_rank'], 0]],
                    'text-size': ['interpolate', ['linear'], ['zoom'],
                                  6, ['case', ['>=', ['coalesce', ['get', 'population_rank'], 0], 13], 14, 10],
                                  12, ['case', ['>=', ['coalesce', ['get', 'population_rank'], 0], 13], 20, 14]]},
         'paint': {'text-color': c['place_text'], 'text-halo-color': c['text_halo'], 'text-halo-width': 1.6}},
        {'id': 'label_regions', 'type': 'symbol', 'source': SOURCE, 'source-layer': 'places', 'maxzoom': 8,
         'filter': ['==', ['get', 'kind'], 'region'],
         'layout': {'text-field': NAME, 'text-font': REGULAR, 'text-size': 12, 'text-transform': 'uppercase',
                    'text-letter-spacing': 0.1},
         'paint': {'text-color': c['boundary'], 'text-halo-color': c['text_halo'], 'text-halo-width': 1.2}},
        {'id': 'label_countries', 'type': 'symbol', 'source': SOURCE, 'source-layer': 'places', 'maxzoom': 7,
         'filter': ['==', ['get', 'kind'], 'country'],
         'layout': {'text-field': NAME, 'text-font': MEDIUM, 'text-size': 14, 'text-max-width': 6},
         'paint': {'text-color': c['boundary'], 'text-halo-color': c['text_halo'], 'text-halo-width': 1.5}},
    ]
    return {'version': 8, 'name': name, 'glyphs': '{GLYPHS}/{fontstack}/{range}.pbf', 'sources': {},
            'metadata': {'tespit:attribution': '© OpenStreetMap-Mitwirkende',
                         'tespit:license': 'Style: Tespit, colours after openstreetmap-carto (CC0). '
                                           'Data: OpenStreetMap contributors (ODbL), tiles: Protomaps basemap.'},
            'layers': layers}


def main():
    OUT.mkdir(exist_ok=True)
    for name, colors in (('light', LIGHT), ('dark', DARK)):
        data = style(colors, f'Tespit OSM {name}')
        ids = [layer['id'] for layer in data['layers']]
        assert len(ids) == len(set(ids)), 'layer ids must be unique'
        (OUT / f'tespit-osm-{name}.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
        print(name, len(ids), 'layers')


if __name__ == '__main__':
    main()
