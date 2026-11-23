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
- **`package-areas.geojson`** contains one WGS84 MultiPolygon per catalog ID, including islands and holes.
  Its `catalogSHA256` identifies the exact bytes of `offline-maps.json`. Both apps bundle the two files for the
  first offline visit. The hand-started workflow publishes the pair together and retains outlines for continents
  it did not rebuild. The fourteen split packages in the November 17 catalog cover rectangles in Canada.
  Their overlaps, including Ottawa, are part of the actual extraction area.
- **Built by** `.github/workflows/offline-maps.yml` (started by hand, about 140 GB) with `build_offline_maps.py`.
- **Style:** `offline_style/` (colours after the OpenStreetMap standard map, CC0; Noto Sans glyphs, OFL).
- **License:** ODbL 1.0, © OpenStreetMap contributors. The apps show the attribution on the map.

Code: MIT. Data: ODbL 1.0.

### Reproducing the package outlines

`build_package_areas.py continent NAME` reads the exact extraction masks left by the PMTiles builder.
It joins grouped provinces, simplifies shared borders, and keeps small islands and enclaves. The source
coordinates describe a generalized selection area. PMTiles can also include neighboring places in boundary tiles.
`build_package_areas.py merge` checks coverage against the catalog and writes its SHA-256 into the collection.

The inaugural catalog is from [data commit 7bd1485](https://github.com/gena3ekiller/tespit-map-data/commit/7bd148588994ce21400f7fe2519ac2b9cf00130c).
The producer used the [Natural Earth 1:10m GeoJSON inputs](https://github.com/nvkelso/natural-earth-vector/tree/ca96624a56bd078437bca8184e78163e5039ad19/geojson).
For an independent rebuild, place `ne_10m_admin_0_countries.geojson` and `ne_10m_admin_1_states_provinces.geojson`
from that revision in `raw/`. The following commands use Shapely 2.1.2 and GEOS 3.13.1.

```sh
python3 build_package_areas.py replay --output /tmp/package-areas.geojson
cmp package-areas.geojson /tmp/package-areas.geojson
```

Replay uses the published package IDs in place of network size probes and checks each reconstructed name,
country, level, split side and bounding box against the catalog. It requires no planet data or PMTiles downloads.
