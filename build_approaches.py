#!/usr/bin/env python3
"""Anfahrtswege je Blitzer und Abschnittsbeginn (Esat, 25.10.2026: „wirklich vor einem auf der Straße“).

Für jeden Blitzer aus out/anchors.json:
- Fußpunkt auf der nächsten Straße (höchstens 40 m entfernt), sonst kein Anfahrtsweg und damit keine Warnung.
- Fahrtrichtungen: Einbahn (oneway, Autobahn, Kreisel) gibt eine vor; sonst die Richtung aus der
  Enforcement-Relation bzw. dem Tag direction (Grad, forward/backward); ohne Angabe beide.
- Abschnittskontrolle: die Richtung, in der die Straße zum Ende führt.
- Von dort wird gegen die Fahrtrichtung 1'100 m die Straße zurückgegangen. An Wegenden geht es weiter auf
  dem Weg mit gleicher Nummer, gleichem Namen oder gleicher Klasse, der am geradesten anschließt und in diese
  Richtung befahren werden darf; ist das nicht eindeutig (Kreuzung ohne klare Fortsetzung), endet der Weg dort.
- Ergebnis in Fahrtrichtung, letzter Punkt beim Blitzer, vereinfacht auf 4 m: out/paths.json
"""
import json, math
from pathlib import Path
import geo

B = Path(__file__).resolve().parent
APPROACH = 1100.0
SNAP = 40.0
CLASS_RANK = {'motorway': 0, 'motorway_link': 0, 'trunk': 1, 'trunk_link': 1, 'primary': 2, 'primary_link': 2,
              'secondary': 3, 'secondary_link': 3, 'tertiary': 4, 'tertiary_link': 4}
CARDINAL = {'N': 0, 'NNE': 22.5, 'NE': 45, 'ENE': 67.5, 'E': 90, 'ESE': 112.5, 'SE': 135, 'SSE': 157.5, 'S': 180,
            'SSW': 202.5, 'SW': 225, 'WSW': 247.5, 'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5}


def angle(a, b):
    d = abs((a - b) % 360)
    return 360 - d if d > 180 else d


def senses_allowed(tags):
    """+1: in Richtung der Knotenfolge befahrbar, -1: dagegen."""
    oneway = tags.get('oneway')
    if oneway in ('yes', '1', 'true'):
        return {1}
    if oneway == '-1':
        return {-1}
    if oneway == 'no':
        return {1, -1}
    if tags.get('highway') in ('motorway', 'motorway_link') or tags.get('junction') in ('roundabout', 'circular'):
        return {1}
    return {1, -1}


def project(lat, lon, a, b):
    cos_lat = math.cos(math.radians(lat))
    kx, ky = 111_320.0 * cos_lat, 111_320.0
    ax, ay = (a[1] - lon) * kx, (a[0] - lat) * ky
    bx, by = (b[1] - lon) * kx, (b[0] - lat) * ky
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / l2))
    return math.hypot(ax + t * dx, ay + t * dy), t, (lat + (ay + t * dy) / ky, lon + (ax + t * dx) / kx)


def simplify(points, tolerance=4.0):
    if len(points) < 3:
        return points
    lat0 = points[0][0]
    k = 111_320.0 * math.cos(math.radians(lat0))
    xy = [((p[1]) * k, p[0] * 111_320.0) for p in points]

    def rdp(i, j, keep):
        ax, ay = xy[i]; bx, by = xy[j]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        worst, index = 0.0, -1
        for m in range(i + 1, j):
            px, py = xy[m]
            t = 0 if l2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / l2))
            d = math.hypot(px - ax - t * dx, py - ay - t * dy)
            if d > worst:
                worst, index = d, m
        if worst > tolerance:
            rdp(i, index, keep); keep.add(index); rdp(index, j, keep)

    keep = {0, len(points) - 1}
    rdp(0, len(points) - 1, keep)
    return [points[i] for i in sorted(keep)]


class Roads:
    def __init__(self, elements):
        self.ways = {}
        for w in elements:
            if w.get('type') != 'way' or 'geometry' not in w or len(w.get('nodes', [])) != len(w['geometry']):
                continue
            self.ways[w['id']] = {'nodes': w['nodes'], 'coords': [(g['lat'], g['lon']) for g in w['geometry']],
                                  'tags': w.get('tags', {})}
        self.at_node = {}
        for wid, w in self.ways.items():
            for i, n in enumerate(w['nodes']):
                self.at_node.setdefault(n, []).append((wid, i))
        self.grid = {}
        for wid, w in self.ways.items():
            for lat, lon in w['coords']:
                self.grid.setdefault((int(lat * 500), int(lon * 500)), set()).add(wid)

    def nearest(self, lat, lon, node_id=None):
        """Weg, auf dem der Blitzer-Knoten liegt, sonst der nächste Weg bis SNAP Meter."""
        if node_id in self.at_node:
            on = [(wid, i) for wid, i in self.at_node[node_id]]
            best = min(on, key=lambda x: CLASS_RANK.get(self.ways[x[0]]['tags'].get('highway'), 9))
            wid, i = best
            c = self.ways[wid]['coords']
            seg = i if i < len(c) - 1 else i - 1
            if seg >= 0:
                return 0.0, wid, seg, (1.0 if seg < i else 0.0), c[i]
        best = None
        cell = (int(lat * 500), int(lon * 500))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for wid in self.grid.get((cell[0] + dy, cell[1] + dx), ()):
                    c = self.ways[wid]['coords']
                    for i in range(len(c) - 1):
                        d, t, p = project(lat, lon, c[i], c[i + 1])
                        if d <= SNAP and (best is None or d < best[0] - 1e-6 or
                                          (abs(d - best[0]) < 3 and CLASS_RANK.get(self.ways[wid]['tags'].get('highway'), 9)
                                           < CLASS_RANK.get(self.ways[best[1]]['tags'].get('highway'), 9))):
                            best = (d, wid, i, t, p)
        return best

    def travel_bearing(self, wid, seg, sense):
        c = self.ways[wid]['coords']
        a, b = c[seg], c[seg + 1]
        return geo.bearing_deg(*(a + b)) if sense == 1 else geo.bearing_deg(*(b + a))

    def walk_back(self, wid, seg, foot, sense, length=APPROACH):
        """Gegen die Fahrtrichtung `sense` vom Fußpunkt aus zurück; liefert die Punkte vom Fußpunkt weg."""
        out = [foot]
        walked = 0.0
        position = foot
        current, step = wid, -sense
        index = seg if step == -1 else seg + 1     # nächster Knoten in Gehrichtung
        visited = {wid}
        headings = []   # (gelaufene Meter, Richtung des Abschnitts in Gehrichtung)
        while walked < length:
            coords = self.ways[current]['coords']
            target = coords[index]
            d = geo.haversine_m(position[0], position[1], target[0], target[1])
            if d > 0.5:
                # Keine Kehrtwende: dreht der Weg innerhalb von 80 m um mehr als 110°, endet er hier
                # (sonst läuft er bei getrennten Fahrbahnen um den Block auf die Gegenfahrbahn).
                heading = geo.bearing_deg(position[0], position[1], target[0], target[1])
                earlier = [h for w, h in headings if walked - w <= 80]
                if any(angle(h, heading) > 110 for h in earlier):
                    break
                headings.append((walked, heading))
            if walked + d >= length:
                f = (length - walked) / d if d else 0
                out.append((position[0] + (target[0] - position[0]) * f, position[1] + (target[1] - position[1]) * f))
                break
            out.append(target); walked += d; position = target
            nxt = index + step
            if 0 <= nxt < len(coords):
                index = nxt
                continue
            # Wegende: Fortsetzung suchen. Fahrtrichtung hier = vom Knoten weg Richtung Blitzer.
            node = self.ways[current]['nodes'][index]
            prev = coords[index - step]
            depart = geo.bearing_deg(target[0], target[1], prev[0], prev[1])
            tags = self.ways[current]['tags']
            options = []
            for w, k in self.at_node.get(node, []):
                if w in visited:
                    continue
                wt = self.ways[w]['tags']; wc = self.ways[w]['coords']; allowed = senses_allowed(wt)
                for walk_step in (-1, 1):
                    j = k + walk_step
                    if not 0 <= j < len(wc):
                        continue
                    travel = -walk_step                      # das Auto fährt von wc[j] nach wc[k]
                    if travel not in allowed:
                        continue
                    arrive = geo.bearing_deg(wc[j][0], wc[j][1], wc[k][0], wc[k][1])
                    turn = angle(arrive, depart)
                    score = 3 if tags.get('ref') and tags.get('ref') == wt.get('ref') else \
                        2 if tags.get('name') and tags.get('name') == wt.get('name') else \
                        1 if tags.get('highway') == wt.get('highway') else 0
                    limit = 75 if score >= 2 else 50
                    if turn <= limit:
                        options.append((score, turn, w, j, walk_step))
            if not options:
                break
            options.sort(key=lambda o: (-o[0], o[1]))
            best = options[0]
            if len(options) > 1 and options[1][0] == best[0] and options[1][1] - best[1] < 20:
                break   # zwei gleich gute Fortsetzungen: nicht eindeutig
            _, _, current, index, step = best
            visited.add(current)
        return out, walked


def senses_for(anchor, roads, hit):
    _, wid, seg, _, foot = hit
    tags = roads.ways[wid]['tags']
    allowed = senses_allowed(tags)
    if len(allowed) == 1:
        return allowed
    if 'section' in anchor:
        end = anchor['section'][2], anchor['section'][3]
        best = None
        for sense in (1, -1):
            # die Seite, auf der die Straße näher zum Ende führt
            pts, _ = roads.walk_back(wid, seg, foot, -sense, 400)
            gain = geo.haversine_m(foot[0], foot[1], *end) - geo.haversine_m(pts[-1][0], pts[-1][1], *end)
            if best is None or gain > best[0]:
                best = (gain, sense)
        return {best[1]} if best and best[0] > 50 else set()
    direction = anchor['point'][4] if anchor['point'][4] >= 0 else None
    tag = (anchor.get('directionTag') or '').strip()
    if direction is None and tag:
        if tag in ('forward', 'backward'):
            node_on_way = anchor['node'] in roads.ways[wid]['nodes']
            if node_on_way:
                return {1} if tag == 'forward' else {-1}
        elif tag.upper() in CARDINAL:
            direction = CARDINAL[tag.upper()]
        else:
            try:
                direction = float(tag.split(';')[0]) % 360
            except ValueError:
                direction = None
    if direction is None:
        return {1, -1}
    matching = {s for s in (1, -1) if angle(roads.travel_bearing(wid, seg, s), direction) <= 60}
    return matching or {1, -1}


def main():
    anchors = json.loads((B / 'out' / 'anchors.json').read_text(encoding='utf-8'))
    by_node = {}
    for a in anchors:
        by_node.setdefault(a['node'], []).append(a)
    jobs = json.loads((B / 'raw' / 'roads' / 'jobs.json').read_text(encoding='utf-8'))
    paths, stats = {}, {'anker': 0, 'ohne_strasse': 0, 'ohne_richtung': 0, 'wege': 0, 'kurz': 0}
    for name, ids in jobs:
        part = B / 'raw' / 'roads' / f'{name}.json'
        roads = Roads(json.loads(part.read_text(encoding='utf-8'))['elements'])
        for node in ids:
            for a in by_node.get(node, []):
                stats['anker'] += 1
                hit = roads.nearest(a['lat'], a['lon'], a['node'])
                if not hit:
                    stats['ohne_strasse'] += 1; continue
                senses = senses_for(a, roads, hit)
                if not senses:
                    stats['ohne_richtung'] += 1; continue
                _, wid, seg, _, foot = hit
                if 'point' in a:
                    p = a['point']; key = f'p:{p[0]},{p[1]}'
                else:
                    s = a['section']; key = f's:{s[0]},{s[1]},{s[2]},{s[3]}'
                for sense in senses:
                    pts, walked = roads.walk_back(wid, seg, foot, sense)
                    if walked < 60:
                        stats['kurz'] += 1; continue
                    line = simplify(list(reversed(pts)))
                    flat = [round(v, 5) for pt in line for v in pt]
                    paths.setdefault(key, []).append(flat)
                    stats['wege'] += 1
    (B / 'out' / 'paths.json').write_text(json.dumps(paths, separators=(',', ':')), encoding='utf-8')
    print('Anfahrtswege:', stats)


if __name__ == '__main__':
    main()
