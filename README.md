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
- **Updates:** `weekly.py` rebuilds the data about once a week (only new cameras need new road queries), checks it
  (no point in or near a blocked country, danger zones only in France, no sudden drop) and publishes a new release.

## Offline maps (1.1.22)

- **Packages:** every country of the world as a PMTiles file with all details (zoom 0–15), cut from the newest
  [Protomaps](https://protomaps.com) planet build (OpenStreetMap data, Protomaps basemap schema v4). A package stays
  below 1.9 GB: larger countries are split into their regions (Natural Earth admin 1), a still larger region into
  halves. Releases `maps-<date>-<continent>` (Europe, Asia, Africa, North America, South America, Oceania, Antarctica).
- **`offline-maps.json`:** the list the apps read (id, continent, country, name, file, size, SHA-256, bounding box,
  release tag per region). Like `manifest.json`, it carries no URLs.
- **Built by** `.github/workflows/offline-maps.yml` (started by hand, about 140 GB) with `build_offline_maps.py`.
- **Style:** `offline_style/` (colours after the OpenStreetMap standard map, CC0; Noto Sans glyphs, OFL).
- **License:** ODbL 1.0, © OpenStreetMap contributors. The apps show the attribution on the map.

Code: MIT. Data: ODbL 1.0.
