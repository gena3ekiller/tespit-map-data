# Offline map style

`build_style.py` writes the light and dark style of the Tespit offline map (`out/`), which the apps bundle together
with `fonts/`.

- **Tiles:** Protomaps basemap, schema v4 (OpenStreetMap data, ODbL). Built by `../build_offline_maps.py`.
- **Colours:** after the OpenStreetMap standard map (openstreetmap-carto, CC0); the dark set is Tespit's own.
- **Fonts:** Noto Sans Regular, Medium and Italic as MapLibre glyphs (`fonts/`, SIL Open Font License 1.1, see
  `fonts/OFL.txt`), from `protomaps/basemaps-assets`. Only the ranges for Latin, Greek, Cyrillic and common symbols.
- **No sprites:** road numbers are text with a halo.
- `package.json` pins `@protomaps/basemaps` (BSD-3), whose layer schema the style follows; it is not run.
