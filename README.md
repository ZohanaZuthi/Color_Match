# Color_Match

A simple watercolor color helper: upload a photograph, zoom into a detail, select an area, and see estimated red, yellow, blue, and white percentages.

> Experimental color approximation—not scientifically validated paint-mixing recipes. The current four-color output does not use the measured watercolor dataset.

## Features

- JPEG, PNG, and WebP uploads up to 15 MB and 20 megapixels.
- Zoom from 100% to 800%, pan, and fit the photo to the viewport.
- Click a small spot or drag a rectangle to sample an area.
- Four integer percentages totaling 100% when an estimate is available.
- Responsive layout, keyboard selection, and warnings for unsupported shades.
- Local backend processing; no external AI service, API key, or GPU required.

## Current interface

The interface now contains only upload, Select/Move, zoom (100–800%), Fit, and four color percentages. Click a point or drag a rectangle. In Move mode, drag to pan a zoomed photo. Selection coordinates remain tied to the source image through zoom and pan. Keyboard users can focus the image, move a selection with arrows, resize with Shift+arrows, and press Enter to analyze.

**The displayed percentages are approximate RYB + white tint proportions, not measured watercolor paint amounts.** The current endpoint averages the selected pixels in Lab and converts to RGB. It retains `min(R,G,B)/255` as the white fraction, subtracts that neutral component, extracts yellow, and maps remaining green to yellow+blue. The remaining fraction is distributed over the RYB hue weights. This white fraction is a display-space convention, not a measured amount of white paint or water dilution. Percentages are rounded to integers summing to 100. For example, digital pink `#ff8080` yields 50% red and 50% white instead of 100% red.

White and near-white neutral selections (all RGB channels at least 250) yield 100% white; other gray/black selections return no ratio. Chromatic colors with maximum RGB below 245 carry a warning that the estimate cannot reproduce their darkness. These thresholds are UI heuristics, not measured physical limits. This simplified mode does not use the NTU catalog or claim physical accuracy; darkness, water dilution and pigment-specific behavior are not modeled. Adding white does not validate the mixing model. Conventional RGB-to-RYB conversion is discussed in [ArtColors](https://github.com/ProfJski/ArtColors) and [RGB/RYB conversion examples](https://gist.github.com/jagracar/d1332b555e8d1c9f46f6ac581b5f1041).

The previous dataset and research endpoints are retained for future calibrated mixing work, but palette catalogs, recipe alternatives, source details and the notebook have been removed from the user interface. Existing saved data remains on disk.

## Run

Requirements: Python 3.12 and Node.js 22 with npm. Clone the repository, then run the app:

```sh
git clone https://github.com/ZohanaZuthi/Color_Match.git
cd Color_Match
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cd frontend
npm ci
npm run build
cd ..
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
```

Open http://localhost:8010. Build the frontend before starting the backend to serve the complete application from one port. With uv installed, `uv venv --python 3.12 .venv` and `uv pip install --python .venv/bin/python -r requirements.lock` can replace the environment/install steps. The lockfile records the tested dependency versions; `requirements.txt` defines the allowed upgrade ranges.

On Windows, use `py -3.12 -m venv .venv` and replace `.venv/bin/python` with `.venv\Scripts\python.exe`.

For frontend development, leave the backend on port 8010, then run `npm run dev` in `frontend/`. Open http://localhost:5174. Vite proxies `/api` to the backend.

`scripts/prepare_data.py` is optional for the four-color interface; it is needed only for the retained research endpoints and dataset tests.

## How to use

1. Upload a photo.
2. Zoom into the desired detail. Choose **Move** to pan the image.
3. Choose **Select**, then click a spot or drag a box.
4. Read the red, yellow, blue, and white estimates below the photo.

Keyboard: focus the photo viewport; use arrows to move the selection, Shift + arrows to resize it, Enter to analyze, and + / − to zoom.

The selected-color dot shows the sampled photo color, not a simulated result of mixing the suggested proportions. The percentages do not specify paint volume, mass, brush loads, or water dilution. Paint brand, pigment strength, transparency, paper, lighting, and camera processing are not calibrated.

## Project structure

```text
backend/                FastAPI endpoints and color calculations
frontend/               React + TypeScript + Vite interface
scripts/prepare_data.py  Optional research dataset importer
tests/                  Backend and API tests
requirements.lock       Pinned Python dependencies
ARCHITECTURE.md          Implementation and research-backend details
data/                   Generated local data; not committed
```

Pillow handles image normalization; NumPy and colour-science handle color processing. SQLite stores the retained research notebook. No LLM or trained prediction model is used.

## Retained research backend

- JPEG, PNG, WebP uploads; EXIF orientation and ICC-to-sRGB normalization.
- Region selection endpoints accept normalized rectangle coordinates.
- Deterministic Lab clustering into up to five representative colors, with area coverage.
- CIEDE2000 matching against measured NTU WPSM recipes; palette filtering and three alternatives.
- Paint volume ratios, reference application quantities, measured swatches, and source CSV rows.
- SQLite-backed saved recipes remain accessible through the backend API.

## Dataset integrity and current limitation

Source: Mei-Yun Chen et al., [NTU WPSM / Prediction Model for Semitransparent Watercolor Pigment Mixtures](https://arxiv.org/abs/1904.00275). The preparer downloads the four original ancillary CSVs, validates dimensions and finite values, and records SHA-256 hashes in `data/audit.json`. The source article is CC BY-NC-SA 4.0; confirm ancillary-data rights before commercial reuse. Raw data and derived catalogs are not committed.

The CSVs have spectral and quantity columns but **no commercial paint-name labels**. Exact equality of primary reflectance spectra and increment outputs connects 142 input spectra into 13 study-paint groups. IDs are deterministic spectral fingerprints; **these are recovered groups, not verified commercial identities**. Research API responses use generic labels such as “Study paint 01”; these are not displayed in the current four-color UI. The research backend cannot yet tell an artist which named tubes to buy/use. A verified mapping from the authors or companion metadata is needed before practical named-paint instructions can be offered. No names are inferred from RGB similarity.

The 2,444 rows include swapped-ingredient augmentation and multiple representations of the same increment. After canonicalizing ingredients and quantities, the current importer produces **923 unique recipes: 780 two-paint mixtures and 143 single-paint applications**. Both train and test CSVs are used for retrieval, not model training; there is no held-out predictive-accuracy claim.

Color conversion uses D65, the CIE 1931 2° observer, and 41 bands (380–780 nm at 10 nm intervals). Negative/out-of-sRGB display components are clipped only for preview; matching uses unclipped Lab. Each ingredient percentage refers to **paint volume**, not grams, pigment mass, water, or brush loads. Paper and application quantity affect watercolor appearance. The sample conditions are Canson Ca grain paper and a 1.5 × 1.5 cm area. No water-dilution estimate, arbitrary-brand compatibility, or recovery of the photo's original ingredients is claimed.

The old example image and notebook interface are no longer shown.

## Storage and operation

`data/raw/`: original CSVs. `data/catalog.json`: generated spectral recipe catalog. `data/audit.json`: provenance and import statistics. `data/runtime/`: normalized images and SQLite notebook. `WATERCOLOR_DATA_DIR` overrides the runtime location. This is a single-user local prototype with no authentication. Keep the backend bound to localhost; add user isolation and access controls before public hosting. Images are sent only to this backend, not to an external AI provider. Fonts are requested from Google Fonts, with system-font fallbacks.

## Verify

The complete backend suite checks the optional research catalog, so prepare it before running all tests. Restart the backend after preparation to enable the research APIs.

```sh
.venv/bin/python scripts/prepare_data.py
.venv/bin/python -m pytest tests -q
cd frontend
npm run build
```

Tests check four-color percentages, white tints, rounding, neutral/dark limitations, preserved image resolution, a published CIEDE2000 reference pair, spectral white, RGB round trips, catalog ratios and provenance, region extraction, color coverage, exact recipe lookup, filtering, persisted saves, EXIF rotation, transparency, and invalid input. Passing software tests does not establish physical paint-matching accuracy.

## Repository and data policy

Uploaded images and saved recipes remain on disk until removed; there is no automatic retention policy. Runtime data, downloaded datasets, dependencies, build output, and `.env` files are excluded from Git. Never commit personal uploads or credentials.

The source article's CC BY-NC-SA 4.0 terms do not automatically establish the ancillary dataset's reuse rights or the license for this application's code. Confirm dataset terms before commercial use or redistribution. No additional software license is granted by this README.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the implemented design and next development steps.
