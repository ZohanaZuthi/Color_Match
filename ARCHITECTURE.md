# Color_Match architecture

## Current simplified flow

Photo upload → normalized image → zoom/pan/rectangle selection → `POST /api/images/{id}/primary` → one RYB + white percentage result.

The UI presents only Red, Yellow, Blue, White, plus the selected color swatch and a concise approximation label. It makes no catalog or notebook requests. Zoom is 1–8 times the fitted image size. A scrollable viewport supports panning; pointer coordinates are computed from the actual displayed image rectangle, so selection coordinates are independent of zoom and scroll offset. Zoom preserves the viewed image center; Fit resets to full-image view. Keyboard selection is supported.

Primary proportions use an RGB-to-RYB hue heuristic applied to the selected region's mean Lab color, with a display-space white fraction `min(R,G,B)/255`. Subtract the minimum channel for hue extraction; normalize the resulting RYB weights to the remaining nonwhite fraction. This is not an inversion of a physical paint model and is not trained on NTU. Neutral selections with every RGB channel at least 250 return 100% white; other neutrals return null percentages with a short message. Dark chromatic samples (maximum RGB below 245) carry a darkness limitation warning. These cutoffs are heuristic, not measured gamut boundaries. Four rounded integer percentages sum to 100 whenever a result is available. White is not a water-dilution estimate. Method identifier: `approximate_rybw`. See `backend/colors.py::primary_proportions` and its tests.

The measured-dataset architecture below remains available through research APIs. It no longer describes the main user-facing output. No old saved data is removed.

## Retained research runtime

React/TypeScript + Vite → same-origin FastAPI → Pillow/NumPy/colour-science → in-memory measured catalog. Normalized images and a SQLite notebook are stored on disk. The built frontend can be served directly by FastAPI. Training infrastructure, external LLM APIs, queues, and GPU hosting are not needed for this version.

1. `POST /api/images`: validate encoded size, format and pixel limits; apply EXIF orientation; convert ICC profile or assume sRGB; composite transparency on white; preserve full image resolution for zoomed sampling; return canonical image dimensions and URL.
2. Browser displays the exact normalized image. Rectangle and point selections use normalized coordinates; arrow-key controls provide a keyboard alternative.
3. `POST /api/images/{id}/selections`: validate bounds, crop, downsample, convert sRGB to Lab, cluster and merge nearby colors, return representative swatches and area percentages. Representatives are actual sampled pixel colors.
4. `POST /api/matches`: validate target Lab and paint IDs; filter measured recipes; rank by CIEDE2000; collapse identical ingredient/ratio alternatives; return measured result, ingredient fractions and source records.
5. `POST /api/saved-recipes`: look up the recipe server-side and persist the selection, target, recipe, and catalog version. `GET /api/saved-recipes` returns stored notebook entries. The current frontend does not expose the notebook or JSON exports.

The current UI cancels stale selection requests with AbortController. Photo processing and matching run off the ASGI event loop. Dataset absence produces an actionable 503 for research catalog requests; the simplified four-color endpoint works independently of the dataset.

## Data preparation

`scripts/prepare_data.py` fetches original CSVs and retains them unmodified. Input features are interleaved per wavelength: transmission A, transmission B, reflectance A, reflectance B, paper reflectance; the final two values are quantities. Outputs are mixture reflectance.

An eight-decimal spectral fingerprint identifies equal primary reflectance curves. When an output equals a known primary spectrum, the increment relation links the two input spectra and that output into one study group. This reconstructs 13 groups; the result is an inferred structural grouping with unverified names. A future name-mapping manifest must document primary-source evidence for each label.

For recipes, merge identical paint identities, round quantities to eight decimal places, sort ingredients, and deduplicate by quantities plus output fingerprint. Preserve every originating split and CSV line number. Precompute D65 Lab and display sRGB from each measured output. Store full reflectance for future colorimetric work.

## API schemas

- Region: `{x, y, width, height}` in normalized image coordinates.
- Color: `{hex, lab: [L, a, b], coverage}`; coverage is image percentage.
- Match request: `{lab, paint_ids?: string[], limit?: number}`. Omitted paint IDs means all; an empty array means none.
- Recipe: `{id, ingredients: [{paint_id, quantity_ml, fraction, paint}], total_quantity_ml, lab, hex, evidence, delta_e, sources, reference_area_cm2, paper}`.
- Save request: `{image_id, region, lab, recipe_id}`. The server obtains authoritative ingredient amounts from its catalog.

## Next steps

1. Resolve and verify commercial paint names; preserve explicit identity provenance. Do not guess from appearance.
2. Evaluate whether the measured recipe coverage is sufficient for artists' real references. Show poor matches rather than inventing quantities.
3. Add trained forward spectral prediction only after a leakage-controlled evaluation. Keep equivalent swapped records and records based on the same physical sample in one split. Compare against measured lookup/interpolation baselines. Separate measured and estimated recipe evidence.
4. Add verified physical test-swatch measurements before claiming practical accuracy across papers, paint ranges, or dilution levels. Do not train on uncalibrated user photos as if they were spectrometer readings.
5. Public hosting: per-user storage and authorization, request/body/concurrency limits, retention/deletion policy, and managed database/object storage. These are unnecessary for local single-user testing but required before sharing with unrelated users.

Current scope is a four-color heuristic interface with a separately retained dataset-backed research API. It is not a named-paint formulation product, and no trained prediction model is included.
