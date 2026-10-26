# tespit-map-data

Fixed speed camera data for the Tespit app, built from OpenStreetMap.

- **Data:** each release (tag `data-YYYY-MM-DD`) carries `speedtraps.json.gz`: fixed and red-light cameras,
  average-speed sections with their approach along the road, and danger zones in France (no camera positions there).
  ODbL 1.0, © OpenStreetMap contributors (see `DATA-LICENSE.md`).
- **Not included:** countries where such warnings are forbidden or unclear (Switzerland, Liechtenstein, Türkiye,
  North Macedonia, Cyprus, Bosnia and Herzegovina, Slovakia, Ireland, China) and everything up to 3 km before
  their borders. Mobile cameras are not included.
- **`manifest.json`:** the current release (tag, file, size, SHA-256 before and after unpacking, data date), a
  global `enabled` switch and `disabledCountries`. The app only reads it; it can switch warnings off but never on
  for a blocked country, and it carries no URLs.
- **Scripts:** `build_borders.py` (borders and country table, byte-identical with the apps), `fetch_osm.py`,
  `fetch_roads.py`, `fetch_fr_roads.py`, `build_zones.py`, `build_approaches.py`, `build_pack.py`,
  then `publish.py` (deterministic gzip, release, manifest). Raw downloads and the danger-zone salt stay local.

Code: MIT. Data: ODbL 1.0.
