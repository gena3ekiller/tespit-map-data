#!/usr/bin/env python3
"""Baut die Gefahrenzonen für Frankreich (Esats Entscheid vom 22.10.2026, Pflichten aus der Rechtsprüfung).

- Zone nur als Linienzug entlang der Straße, nie als Kreis.
- Mindestlänge: Autobahn 4 km, ausserorts 2 km, innerorts 300 m.
- Die Lage des Blitzers in der Zone wird mit einem geheimen Salz (HMAC-SHA256) zwischen 20 und 80 % versetzt.
- Nach jeder Kürzung (Kreuzung ohne klare Fortsetzung, Sackgasse, Grenze) liegt der Blitzer mindestens
  0,2 x Mindestlänge von jedem Zonenende entfernt, sonst fällt die Zone weg; ebenso, wenn die Zone kürzer
  als die Mindestlänge wird.
- In der Zone stehen keine OSM-ID, keine Art und kein Tempo, nur Koordinaten.
Ergebnis: out/fr_zones.json (Liste von Linienzügen [[lat, lon], ...]).
"""
import hashlib, hmac, json, math, os, secrets
from pathlib import Path
import geo

B = Path(__file__).resolve().parent
SECRET = B / 'secret' / 'zone_salt.hex'
MOTORWAY, OUTSIDE, INSIDE = 4000.0, 2000.0, 300.0
URBAN_CLASSES = {'residential', 'living_street', 'unclassified'}


def salt():
    SECRET.parent.mkdir(exist_ok=True)
    if not SECRET.exists():
        SECRET.write_text(secrets.token_hex(32), encoding='utf-8')
        os.chmod(SECRET, 0o600)
    return bytes.fromhex(SECRET.read_text(encoding='utf-8').strip())


def offset_fraction(key, node_id):
    digest = hmac.new(key, str(node_id).encode(), hashlib.sha256).digest()
    return 0.2 + 0.6 * (int.from_bytes(digest[:8], 'big') / 2 ** 64)


def project(lat, lon, a, b):
    """Projektion von (lat, lon) auf Segment a-b; liefert (Abstand m, t, Punkt)."""
    cos_lat = math.cos(math.radians(lat))
    kx, ky = 111_320.0 * cos_lat, 111_320.0
    ax, ay = (a[1] - lon) * kx, (a[0] - lat) * ky
    bx, by = (b[1] - lon) * kx, (b[0] - lat) * ky
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / l2))
    px, py = ax + t * dx, ay + t * dy
    point = (lat + py / ky, lon + px / kx)
    return math.hypot(px, py), t, point


def main():
    key = salt()
    countries = geo.load_borders()
    policy = geo.load_policy()
    states = policy['states']
    blocked = [c for c in countries if states.get(c['iso']) == 'blocked']
    france = next(c for c in countries if c['iso'] == 'FR')
    band = policy['pipelineBlockedBandKm'] * 1000

    def inside_france_safely(lat, lon):
        if not any(geo.point_in_polygon(lon, lat, p) for p in france['polys']):
            return False
        return all(geo.distance_to_country(lon, lat, c, band) >= band for c in blocked)

    cams = json.loads((B / 'raw' / 'osm_FR.json').read_text(encoding='utf-8'))['elements']
    cams = [e for e in cams if e['type'] == 'node' and e.get('tags', {}).get('highway') == 'speed_camera']
    roads = json.loads((B / 'raw' / 'osm_FR_roads.json').read_text(encoding='utf-8'))['elements']
    ways = {}
    for w in roads:
        if w['type'] != 'way' or 'geometry' not in w or len(w.get('nodes', [])) != len(w['geometry']):
            continue
        ways[w['id']] = {'nodes': w['nodes'], 'coords': [(g['lat'], g['lon']) for g in w['geometry']],
                         'tags': w.get('tags', {})}
    at_node = {}
    for wid, w in ways.items():
        for i, n in enumerate(w['nodes']):
            at_node.setdefault(n, []).append((wid, i))
    grid = {}
    for wid, w in ways.items():
        for i in range(len(w['coords']) - 1):
            lat, lon = w['coords'][i]
            grid.setdefault((int(lat * 200), int(lon * 200)), set()).add(wid)

    def nearest_way(lat, lon):
        best = None
        cell = (int(lat * 200), int(lon * 200))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for wid in grid.get((cell[0] + dy, cell[1] + dx), ()):
                    c = ways[wid]['coords']
                    for i in range(len(c) - 1):
                        d, t, p = project(lat, lon, c[i], c[i + 1])
                        if d <= 40 and (best is None or d < best[0]):
                            best = (d, wid, i, t, p)
        return best

    def same_road(a, b):
        ta, tb = ways[a]['tags'], ways[b]['tags']
        if ta.get('ref') and ta.get('ref') == tb.get('ref'):
            return 3
        if ta.get('name') and ta.get('name') == tb.get('name'):
            return 2
        if ta.get('highway') == tb.get('highway'):
            return 1
        return 0

    def walk(wid, index, point, forward, length):
        """Läuft ab dem Fußpunkt entlang der Straße; liefert (Punkte, gelaufene Meter)."""
        out = [point]
        walked = 0.0
        current, i, step = wid, index, 1 if forward else -1
        position = point
        visited = {wid}
        while walked < length:
            coords = ways[current]['coords']
            nxt = i + 1 if step == 1 else i
            if 0 <= nxt < len(coords):
                target = coords[nxt]
                seg = geo.haversine_m(position[0], position[1], target[0], target[1])
                if walked + seg >= length:
                    f = (length - walked) / seg if seg else 0
                    end = (position[0] + (target[0] - position[0]) * f, position[1] + (target[1] - position[1]) * f)
                    if not inside_france_safely(*end):
                        break
                    out.append(end); walked = length; break
                if not inside_france_safely(*target):
                    break
                out.append(target); walked += seg; position = target
                i = nxt if step == 1 else nxt - 1
                if step == -1 and i < 0:
                    i = -1
                continue
            node = ways[current]['nodes'][-1 if step == 1 else 0]
            candidates = [(w, k) for w, k in at_node.get(node, []) if w not in visited]
            if not candidates:
                break
            scored = sorted(candidates, key=lambda c: -same_road(current, c[0]))
            best_score = same_road(current, scored[0][0])
            if best_score == 0 or (len(scored) > 1 and same_road(current, scored[1][0]) == best_score and best_score < 3):
                break   # keine eindeutige Fortsetzung: Zone endet hier
            current, k = scored[0]
            visited.add(current)
            n = len(ways[current]['nodes'])
            if k == 0:
                step, i = 1, 0
            elif k == n - 1:
                step, i = -1, n - 1
            else:
                break   # Einmündung mitten in einen Weg: nicht eindeutig
            position = ways[current]['coords'][k]
        return out, walked

    zones, dropped = [], {'kein_weg': 0, 'gesperrt': 0, 'zu_kurz': 0}
    for cam in cams:
        lat, lon = cam['lat'], cam['lon']
        if not inside_france_safely(lat, lon):
            dropped['gesperrt'] += 1
            continue
        hit = nearest_way(lat, lon)
        if not hit:
            dropped['kein_weg'] += 1
            continue
        _, wid, i, t, foot = hit
        tags = ways[wid]['tags']
        speed = tags.get('maxspeed') or cam.get('tags', {}).get('maxspeed') or ''
        urban = tags.get('highway') in URBAN_CLASSES or (speed.isdigit() and int(speed) <= 50)
        minimum = MOTORWAY if tags.get('highway') == 'motorway' else (INSIDE if urban else OUTSIDE)
        length = minimum * 1.15
        p = offset_fraction(key, cam['id'])
        back_pts, back = walk(wid, i, foot, False, p * length)
        fwd_pts, fwd = walk(wid, i, foot, True, (1 - p) * length)
        if back < 0.2 * minimum or fwd < 0.2 * minimum or back + fwd < minimum:
            dropped['zu_kurz'] += 1
            continue
        line = list(reversed(back_pts[1:])) + [foot] + fwd_pts[1:]
        zones.append([[round(a, 5), round(b, 5)] for a, b in line])
    (B / 'out' / 'fr_zones.json').write_text(json.dumps(zones, separators=(',', ':')), encoding='utf-8')
    print('Blitzer FR:', len(cams), '| Zonen:', len(zones), '| verworfen:', dropped)


if __name__ == '__main__':
    main()
