# Case Study Report: Estimating Forest Crown Closure from Public Geospatial Data

This report addresses the Cabin Resource Management Geospatial Analyst Round 3 case study: design and demonstrate a reproducible workflow that goes from public data to a validated crown closure model. It follows the case study's own structure (Parts 1-4) so it can be checked directly against the brief, then adds sections on trust/limitations, next steps, and a deliverables self-audit.

See `README.md` for the project overview, data source links, and repository layout.


## Part 1: Understanding the Problem

**Regression, not classification.** Crown closure is a continuous percentage (0-100% of ground covered by canopy). Binning it into classes would throw away information and introduce an arbitrary threshold that isn't motivated by anything in the data itself. A regression model that outputs a percentage is also directly interpretable to a forester without translation.

**Ground truth.** The target is the `CROWN_CLOSURE` field from BC's Vegetation Resources Inventory (VRI). This needs to be stated plainly: VRI crown closure is itself a photo-interpreted estimate, not a direct field or LiDAR measurement. Using it as "ground truth" means the model is really learning to reproduce an analyst's photo-interpretation from satellite imagery and terrain, not some independently verified physical quantity. That's a reasonable and common choice given no better province-wide alternative is publicly available, but it caps how good "accuracy" can ever mean here, no matter how well the model fits.

**What I'd clarify with a forestry professional before starting:**
- Is photo-interpreted VRI crown closure an acceptable proxy for their purposes, or would they want the model calibrated against LiDAR-derived canopy cover or field plots instead?
- What precision actually matters operationally? A model that separates <25% / 25-60% / >60% crown closure reliably (useful for fuel modelling) is a very different bar than one that needs to resolve individual percentage points.
- Does "current" mean this calendar year, or is a 1-3 year old base acceptable given how infrequently VRI polygons actually get re-interpreted?
- Should recent disturbance (fire, harvest) be handled explicitly, or is part of the goal to *find* places where VRI is stale precisely because of undetected disturbance?

**Key assumptions and what could make this unsuitable for operational use:**
- That VRI's photo-interpreted crown closure is accurate and consistent enough to train against. Interpreter subjectivity is a real source of label noise this project cannot see or correct for.
- That the Sentinel-2 cloudless mosaic used here reflects "current" conditions. It doesn't, exactly, it's a composite blended over many acquisition dates (more on this in Part 3).
- That VRI's vintage roughly matches the imagery's vintage across the whole AOI. VRI polygons carry their own reference/photo-interpretation dates that were not used here; the project currently treats the whole layer as equally current, which is very likely false in places, and is arguably the central problem the case study is actually about.
- No independent field-truthed validation exists anywhere in this pipeline. Every result here is "agreement with VRI," not "agreement with reality."


## Part 2: Public Data Discovery

Three public sources across three different categories, all retrieved by script (`code/generate_*.py`, no manual downloads required except needing to leave time for a ~4GB and a multi-GB fetch):

**1. BC Vegetation Resources Inventory (forest inventory).** [`VEG_COMP_LYR_R1_POLY`](https://catalogue.data.gov.bc.ca/dataset/vri-2025-forest-vegetation-composite-rank-1-layer-r1-), province-wide polygons with a `CROWN_CLOSURE` attribute. Selected because it's the only public, authoritative, province-wide source of this exact target variable. Retrieved by `generate_crown_closure.py`, which downloads the current File Geodatabase directly from the BC government's public data host, clips to the AOI, and rasterizes. Spatially it's polygon vector data at whatever resolution the original photo-interpretation used (finer than anything else in this pipeline); temporally it's labelled "2025" but individual polygons can be older, since not every polygon gets re-interpreted every cycle.

**2. EOX s2cloudless (satellite imagery).** A global cloud-free Sentinel-2 composite, loaded as a QGIS XYZ layer by `generate_sentinel2.py` and rendered patch by patch for RGB input. Selected specifically to sidestep cloud-masking: rather than pulling raw Sentinel-2 scenes and having to detect and remove cloud cover myself, EOX has already produced a clean composite. The tradeoff, made explicit here, is temporal precision: "s2cloudless-2025" is a blend across the year, not a single acquisition date.

**3. BC Digital Elevation Model (terrain).** NTS 1:250,000 tiles, downloaded and mosaicked by `generate_dem.py`. Selected because elevation is a plausible predictor of vegetation structure independent of what's visible in the imagery (tree line, aspect, exposure), and because it's static (no temporal-matching problem at all).

**What's missing relative to the case study's suggested categories:** no disturbance/fire-history layer was incorporated. Given that VRI staleness is arguably the core motivating problem, this is a real gap and the first thing listed under Next Steps.


## Part 3: Data Cleaning and Dataset Creation

**CRS.** Everything is reprojected to EPSG:3857 (Web Mercator) to match the satellite tile source's native projection and give one consistent working CRS across VRI, DEM, and imagery. Worth flagging: Web Mercator distorts area away from the equator, so the polygon-area histogram (`plots/polygon_area_histogram.png`) is not perfectly accurate in absolute terms at BC's latitude. Relative comparisons within the AOI are unaffected, since the distortion is roughly uniform across such a small span of latitude.

**Raster alignment and resolution.** DEM, the rasterized crown closure layer, and the rendered satellite patches all share a common 25 m/pixel grid, chosen to match VRI's own rasterization scale, a reasonable middle ground between the DEM's native tile resolution and keeping per-patch pixel counts (256×256) manageable for model training.

**Spatial extent.** The AOI spans roughly 49-51°N by 119-125°W (~668 km × ~346 km), split into a 104×54 grid of 6.4 km patches (5,616 total, 368,050,176 pixels). This deliberately covers a mix of terrain: the Lower Mainland and Victoria (urban), the Salish Sea (open water), and the Coast Mountains (steep, forested). That heterogeneity is good for demonstrating a real spatial problem, but it also means a meaningful share of the AOI simply has no forest to have a crown closure value for, which shows up directly in the missing-data numbers below.

**NoData handling.** VRI doesn't have a crown closure value everywhere. About 68% of AOI pixels fall inside a polygon with a valid (non-null) `CROWN_CLOSURE` value; the rest are water, urban land, or unclassified. A validity mask was built explicitly for this (`crown_closure_mask`), and invalid pixels are *excluded* from both training loss and evaluation metrics for both models, not imputed as zero. This was a deliberate choice: imputing 0 would teach the model that "no data" means "confirmed no canopy," which is a different and false claim, an ocean pixel is not the same as a clear-cut.

**Clouds/unusable imagery.** Not handled as a separate step, because using EOX's pre-built cloudless composite removes the problem by construction. The cost of that convenience is stated above: it's a multi-date blend, not a single clean acquisition.

**Temporal differences between sources.** VRI's photo-interpretation dates, the DEM's static acquisition, and the 2025 Sentinel-2 composite are not rigorously date-matched here, they're treated as roughly contemporaneous. This is a simplification stated plainly rather than hidden: a more careful version of this project would use VRI's own per-polygon reference dates to check (and possibly exclude) stale polygons rather than assuming the whole layer is equally current.

**Label quality, sampling, class imbalance.** Crown closure and polygon-area distributions across the AOI are visibly skewed, not uniform (`plots/crown_closure_histogram.png`, `plots/polygon_area_histogram.png`, produced by `generate_crown_closure_histograms.py`). No explicit rebalancing (oversampling rare high/low closure areas, for instance) was applied; the model sees the natural distribution as-is.

**Spatial leakage.** This is the most important caveat in the whole project, and it's an honest one. The train/test split is a random 80/20 split *of individual pixels within each patch*, not a split of geographic regions. Since neighbouring pixels are strongly spatially autocorrelated, a held-out test pixel is very often immediately adjacent to a training pixel the model has already seen. This is a conventional random split, and it is **not** a good defence against spatial leakage: it almost certainly makes test performance look somewhat better than the model's true ability to generalize to genuinely unseen geography. A materially stronger design would hold out entire patches, or clusters of patches, for testing, not pixels scattered through every patch. I'm flagging this as a known weakness rather than presenting the test RMSE as if it were leakage-free, because it isn't.

**Final dataset.**
- **Samples:** 5,616 patches, 368,050,176 pixels total (~250M with valid crown closure labels, ~68%).
- **Input features:** `r`, `g`, `b` (Sentinel-2 cloudless composite), `elevation_m` (BC DEM).
- **Target:** `crown_closure` (%, VRI).
- **Missing data:** excluded via validity mask, not imputed (above).
- **Split:** 80/20 train/test, per pixel, within each patch (see spatial leakage note). No separate validation set was held out for either model: the linear model has no hyperparameters to tune against one (its solution is closed-form), and SegFormer training relied on per-epoch test-set monitoring rather than a true untouched validation set. A production version of this should not conflate the two.

**Decisions that materially affect performance:**
- RGB and elevation are min-max normalized to *fixed, domain-known bounds* (0-255 for RGB, 0-4,671 m for elevation, BC's highest point), not to the min/max of the training data. This was chosen specifically to avoid leaking any statistic derived from the data itself into preprocessing.
- Elevation enters the linear model as a degree-2 polynomial (`elevation_m` and `elevation_m²`), because a straight-line fit against elevation was visibly poor.
- SegFormer was initialized from a checkpoint pretrained on real satellite imagery, not ImageNet or a natural-photo checkpoint, specifically so its early layers already understand overhead/top-down imagery rather than street-level photos.


## Part 4: Machine Learning

**Baseline: multiple linear regression (OLS).** `crown_closure ~ r + g + b + elevation_m + elevation_m²`, fit by closed-form solution. Chosen as the baseline because it's fast, fully interpretable (coefficients and p-values), and gives a defensible answer to "how much of this can be explained by simple per-pixel spectral and terrain values alone" before reaching for anything more complex. Rather than loading all 368M rows into memory (~20GB), the fit streams one patch at a time and accumulates the OLS sufficient statistics (`XᵀX`, `Xᵀy`); because summation is associative, this gives the exact same coefficients as fitting on the full pooled dataset at once, not an approximation.

**Candidate: SegFormer (vision transformer), adapted for dense regression.** Same 4 input channels as the baseline (RGB + elevation), but processed as a full 256×256 image rather than pixel-by-pixel, with the classification head replaced by a single-channel regression output and a masked-MSE loss (so invalid pixels never contribute to the gradient, same principle as the baseline's masking). Chosen because crown closure is plausibly influenced by *local spatial texture and context* (canopy pattern, terrain shading, neighbourhood structure) that a per-pixel linear model cannot see, since it only ever looks at one pixel's own 4 values in isolation. A convolution/attention-based model that sees the whole patch at once can, in principle, use that context.

**Metrics.** RMSE in percentage points of crown closure, chosen specifically because it's in the same units as the target and directly interpretable ("the model is typically off by X points"), rather than a unitless loss. R² and adjusted R² are also reported for the linear model. Coefficient p-values are reported too, with a caveat: because pixels within a patch are spatially autocorrelated, the effective sample size behind those p-values is smaller than the raw pixel count implies, so they are more optimistic (smaller) than a naive reading would suggest. The R² and RMSE numbers are not affected by this in the same way.

**Results.**

| Model | R² | Train RMSE | Test RMSE |
|---|---|---|---|
| Linear regression (baseline) | 0.276 | 20.29% | 20.29% |
| SegFormer, 20 epochs (candidate) | (not applicable) | 13.72% | 13.05% |

SegFormer's test RMSE is a ~36% relative reduction versus the baseline, using the *same* 4 raw input channels. Train and test RMSE stay close for both models (no sign of overfitting), and SegFormer's test loss was still trending downward at epoch 20 rather than plateaued, meaning more training would very likely improve it further.

**What the comparison shows.** The baseline's modest R² (0.276) means RGB and elevation, taken pixel-by-pixel, explain a real but limited share of crown closure. SegFormer's large improvement using the exact same information, just processed with spatial context instead of pixel-by-pixel, points to a meaningful chunk of the missing signal being about the *arrangement* of values (texture, neighbourhood pattern), not their raw numeric values alone. That's a more useful conclusion than "the fancier model won": it says spatial modelling capacity, not additional data, was the main lever available here.


## Where I Would and Would Not Trust This Result

**Would trust:** the relative signal within this AOI, broad areas of likely low versus high canopy cover, given the consistent train/test RMSE (no overfitting) and the large, model-architecture-driven improvement over the naive baseline.

**Would not trust:** precise per-pixel or per-hectare crown closure values for any operational or regulatory decision, for five concrete reasons:
1. The ground truth is itself a photo-interpreted estimate, not a measurement, so "accuracy" here means agreement with another estimate.
2. The per-pixel random split likely overstates true out-of-region generalization (spatial leakage, above).
3. Imagery is a single-composite-date blend; performance on a genuinely different season or year is untested.
4. There is no independent, field-truthed validation set anywhere in this pipeline.
5. VRI's vintage-versus-current mismatch means the model may partly be learning to reproduce a snapshot that is itself already stale in disturbed areas, which is the exact problem this project was meant to help with.


## What I Would Do Next

1. **Fix the spatial split.** Hold out entire patches, or geographic clusters of patches, for testing, not pixels within every patch. This is the single highest-priority change.
2. **Bring in a disturbance/fire-history layer** to explicitly identify where VRI's photo-interpretation is likely stale, directly targeting the "current estimate" goal rather than assuming the whole layer is equally current.
3. **Use VRI's actual per-polygon reference dates** to check and potentially exclude or down-weight stale polygons, instead of treating the AOI as uniformly "2025."
4. **Add a genuine held-out validation set**, separate from the test set used for final reporting.
5. **Multi-date or multi-season Sentinel-2 compositing** instead of a single cloudless mosaic, to capture phenological signal the current single composite can't.
6. **Train SegFormer further** (loss was still improving at epoch 20) and try a couple of architecture/hyperparameter variants.
7. **Independent validation against field plots or LiDAR-derived canopy cover**, since validating against VRI can never catch a systematic bias in VRI itself.

*A smaller implementation note, not a modelling decision:* SegFormer's backward pass hits a real bug in PyTorch's Apple Silicon (MPS) backend on the development machine used here (confirmed via a minimal reproduction, not assumed); training therefore ran on CPU. A gradient-accumulation workaround (physical batch size 1, accumulated over 8 steps, mathematically equivalent to a true batch-8 gradient) was benchmarked at ~8x faster and is a straightforward way to cut training time if this continues on similar hardware.


## Deliverables Self-Audit

Checked against the case study's own list.

**Required:**

| Deliverable | Status |
|---|---|
| Source-code repository | Done |
| README with setup/run instructions | **Partial** — README covers the project, data sources, and structure, but does not yet walk through environment setup or run order step by step. Should be added before submission. |
| Data-source documentation and provenance | Done (README + this report) |
| Environment/dependency definition | **Missing.** No `requirements.txt`/`environment.yml` exists yet. This needs to be added; the pipeline currently spans a QGIS Python environment (GDAL, `qgis.core`) and a separate Anaconda environment (PyTorch, transformers, pandas) that aren't documented anywhere as reproducible environments. |
| Data acquisition/preparation workflow | Done (`code/generate_*.py`) |
| Final model-ready dataset, or reproduce instructions | Done (scripts regenerate everything from public sources) |
| Baseline model | Done (`linear_regression_trainer.ipynb`) |
| Candidate model + comparison results | Done (`segformer_trainer.ipynb`, results above) |

**Optional bonus:**

| Deliverable | Status |
|---|---|
| Extended model evaluation/interpretation | Partial — coefficient p-values, loss curves, distribution histograms exist; no formal spatial error/bias map yet |
| GIS-compatible prediction output | Done — `generate_prediction_mosaics.py` produces georeferenced PNG+worldfile mosaics for both models, loadable directly in QGIS |
| At least one final map | Done — both prediction mosaics, plus `area_of_interest_visualizer.qgz` tying every layer together |

**Before submitting:** add the environment/dependency file and expand the README with explicit setup/run steps. Everything else on the required list is in place.
