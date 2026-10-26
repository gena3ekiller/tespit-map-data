"""Geometrie für Ländersperre und Pipeline: Punkt im Polygon und Abstand zur Grenze (Meter, lokal eben)."""
import json, math
from pathlib import Path

B = Path(__file__).resolve().parent
R = 6_371_000.0


def load_borders():
    data = json.loads((B / 'out' / 'speedtrap_borders_v1.json').read_text(encoding='utf-8'))
    countries = []
    for c in data['countries']:
        polys = []
        for rings in c['polygons']:
            xs = [p[0] for p in rings[0]]; ys = [p[1] for p in rings[0]]
            polys.append({'rings': rings, 'bbox': (min(xs), min(ys), max(xs), max(ys))})
        countries.append({'iso': c['iso'], 'polys': polys})
    return countries


def load_policy():
    return json.loads((B / 'out' / 'country_policy_v1.json').read_text(encoding='utf-8'))


def point_in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_polygon(lon, lat, poly):
    b = poly['bbox']
    if lon < b[0] or lon > b[2] or lat < b[1] or lat > b[3]:
        return False
    inside = False
    for ring in poly['rings']:
        if point_in_ring(lon, lat, ring):
            inside = not inside   # Löcher gerade/ungerade
    return inside


def country_at(lon, lat, countries):
    for c in countries:
        for p in c['polys']:
            if point_in_polygon(lon, lat, p):
                return c['iso']
    return None


def distance_to_country(lon, lat, country, limit_m):
    """Kleinster Abstand in Metern zur Grenze eines Landes, nur geprüft innerhalb limit_m (sonst inf)."""
    cos_lat = math.cos(math.radians(lat))
    dlat = limit_m / 111_320.0
    dlon = limit_m / (111_320.0 * max(0.05, cos_lat))
    best = math.inf
    for p in country['polys']:
        b = p['bbox']
        if lon < b[0] - dlon or lon > b[2] + dlon or lat < b[1] - dlat or lat > b[3] + dlat:
            continue
        if point_in_polygon(lon, lat, p):
            return 0.0
        for ring in p['rings']:
            for i in range(len(ring) - 1):
                ax, ay = ring[i]; bx, by = ring[i + 1]
                if (min(ax, bx) > lon + dlon or max(ax, bx) < lon - dlon or
                        min(ay, by) > lat + dlat or max(ay, by) < lat - dlat):
                    continue
                best = min(best, segment_distance_m(lon, lat, ax, ay, bx, by, cos_lat))
    return best


def segment_distance_m(px, py, ax, ay, bx, by, cos_lat):
    kx = 111_320.0 * cos_lat; ky = 111_320.0
    ax_, ay_ = (ax - px) * kx, (ay - py) * ky
    bx_, by_ = (bx - px) * kx, (by - py) * ky
    dx, dy = bx_ - ax_, by_ - ay_
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax_ * dx + ay_ * dy) / length2))
    cx, cy = ax_ + t * dx, ay_ + t * dy
    return math.hypot(cx, cy)


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360
