/**
 * triangulation.js — LS-AoA + Hybrid Bayesian Triangulation
 * ==========================================================
 * Implements:
 *   1) Least Squares Angle-of-Arrival (LS-AoA) — unchanged
 *   2) Midpoint solver — unchanged
 *   3) Bayesian Spatial Grid — UPGRADED: now uses a small 1 km x 1 km
 *      prior search box at 5 m resolution instead of the old 15 km grid.
 *   4) Hybrid solve flow: LS-AoA first, then Bayesian inside prior box,
 *      plus a disagreement distance metric for diagnostics.
 *
 * ── WHAT CHANGED (v1.2 hybrid upgrade) ──────────────────────────
 *   FILE: triangulation.js
 *
 *   NEW helpers added (clearly marked with [NEW]):
 *     • buildPriorBox(centerLat, centerLon, halfSizeM)
 *         Builds a { minLat, maxLat, minLon, maxLon } bounding box
 *         that is 2*halfSizeM wide/tall around the given center.
 *     • isInsidePriorBox(E, N, priorBoxENU)
 *         Fast AABB check for a candidate cell in ENU space.
 *     • isCellInsideActiveMasks(E, N, refLat, refLon, config)
 *         Checks whether a cell also satisfies the rectangle/polygon
 *         search overlays that may be active (both optional).
 *     • lsVsBayesianDisagreement(lsResult, bayesResult)
 *         Returns the haversine distance (metres) between the LS and
 *         Bayesian estimates — used as a stability/quality metric.
 *
 *   bayesianGrid() — CHANGED:
 *     • Accepts an optional `priorConfig` argument:
 *         { centerLat, centerLon, halfSizeM? }
 *       If provided, the Bayesian search runs inside the 1 km × 1 km
 *       prior box at STEP_M = 5 m resolution.
 *     • If no priorConfig is given, falls back to the original 15 km /
 *       100 m grid (safe legacy behaviour, no breakage).
 *     • Grid cells are additionally filtered by active rectangle/polygon
 *       masks when those are enabled in `config`.
 *     • Returns `lsDisagreement_m` in the result object.
 *
 *   solve() — CHANGED:
 *     • For 'bayesian' algo, passes `priorConfig` from config into
 *       bayesianGrid() so the prior box is honoured.
 *     • For 'bayesian' algo, also runs lsAoA in the background and
 *       attaches `lsResult` and `lsDisagreement_m` to the returned
 *       object so main.js can display the diagnostic.
 *     • LS-AoA and midpoint paths are 100% unchanged.
 *
 *   EVERYTHING ELSE — unchanged:
 *     • lsAoA(), midpoint(), filterStations()
 *     • All geometry helpers (rayAABBIntersect, pointInPolygon2D, etc.)
 *     • Public API surface (return object keys are the same)
 *
 * ── ASSUMPTIONS ──────────────────────────────────────────────────
 *   • priorConfig is provided by main.js from a new UI field (prior
 *     center lat/lon). If absent, legacy Bayesian runs unchanged.
 *   • halfSizeM defaults to 500 m → 1 km × 1 km total box.
 *   • Flat-earth ENU approximation is valid for a 1 km box.
 *   • Rectangle mask (aabb) and polygon mask (polyBounds) constraints
 *     are optional; if inactive they simply don't filter cells.
 */

const Triangulation = (() => {

    const DEG2RAD = Math.PI / 180;
    const RAD2DEG = 180 / Math.PI;
    const EARTH_R  = 6371000; // metres

    // ── Coordinate Helpers (unchanged) ───────────────────────────

    function latLonToENU(lat, lon, refLat, refLon) {
        const dLat = (lat - refLat) * DEG2RAD;
        const dLon = (lon - refLon) * DEG2RAD;
        const N = dLat * EARTH_R;
        const E = dLon * EARTH_R * Math.cos(refLat * DEG2RAD);
        return { E, N };
    }

    function enuToLatLon(E, N, refLat, refLon) {
        const lat = refLat + (N / EARTH_R) * RAD2DEG;
        const lon = refLon + (E / (EARTH_R * Math.cos(refLat * DEG2RAD))) * RAD2DEG;
        return { lat, lon };
    }

    // ── LS-AoA Solver (unchanged) ─────────────────────────────────

    function lsAoA(stations) {
        if (!stations || stations.length < 2) return null;

        const refLat = stations.reduce((s, st) => s + st.lat, 0) / stations.length;
        const refLon = stations.reduce((s, st) => s + st.lon, 0) / stations.length;

        let AtWA = [[0,0],[0,0]];
        let AtWb = [0, 0];

        for (const st of stations) {
            const w = st.confidence ?? 1.0;
            const { E, N } = latLonToENU(st.lat, st.lon, refLat, refLon);
            const theta = (90 - st.bearing_deg) * DEG2RAD;
            const sinT = Math.sin(theta);
            const cosT = Math.cos(theta);
            const a = sinT;
            const b = -cosT;
            const c = sinT * E - cosT * N;
            AtWA[0][0] += w * a * a;
            AtWA[0][1] += w * a * b;
            AtWA[1][0] += w * b * a;
            AtWA[1][1] += w * b * b;
            AtWb[0]    += w * a * c;
            AtWb[1]    += w * b * c;
        }

        const det = AtWA[0][0] * AtWA[1][1] - AtWA[0][1] * AtWA[1][0];
        if (Math.abs(det) < 1e-10) {
            console.warn('[Triangulation] Singular matrix — bearings may be parallel.');
            return null;
        }

        const x = (AtWb[0] * AtWA[1][1] - AtWb[1] * AtWA[0][1]) / det;
        const y = (AtWA[0][0] * AtWb[1] - AtWA[1][0] * AtWb[0]) / det;

        let totalResidual = 0;
        for (const st of stations) {
            const { E, N } = latLonToENU(st.lat, st.lon, refLat, refLon);
            const theta = (90 - st.bearing_deg) * DEG2RAD;
            const sinT = Math.sin(theta);
            const cosT = Math.cos(theta);
            const dist = Math.abs(sinT * (x - E) - cosT * (y - N));
            totalResidual += dist;
        }
        const residual = totalResidual / stations.length;

        const result = enuToLatLon(x, y, refLat, refLon);
        return {
            lat: result.lat,
            lon: result.lon,
            residual_m: residual,
            stationsUsed: stations.length,
        };
    }

    // ── Midpoint Solver (unchanged) ───────────────────────────────

    function midpoint(stations) {
        if (!stations || stations.length < 2) return null;
        const [a, b] = stations;
        const refLat = (a.lat + b.lat) / 2;
        const refLon = (a.lon + b.lon) / 2;
        const pA = latLonToENU(a.lat, a.lon, refLat, refLon);
        const pB = latLonToENU(b.lat, b.lon, refLat, refLon);
        const tA = (90 - a.bearing_deg) * DEG2RAD;
        const tB = (90 - b.bearing_deg) * DEG2RAD;
        const dA = { x: Math.cos(tA), y: Math.sin(tA) };
        const dB = { x: Math.cos(tB), y: Math.sin(tB) };
        const dx = pB.E - pA.E;
        const dy = pB.N - pA.N;
        const cross = dA.x * dB.y - dA.y * dB.x;
        if (Math.abs(cross) < 1e-10) return null;
        const t = (dx * dB.y - dy * dB.x) / cross;
        const ix = pA.E + t * dA.x;
        const iy = pA.N + t * dA.y;
        const res = enuToLatLon(ix, iy, refLat, refLon);
        return { lat: res.lat, lon: res.lon, residual_m: 0, stationsUsed: 2 };
    }

    // ── [NEW] Prior Box Helpers ───────────────────────────────────

    /**
     * [NEW] buildPriorBox
     * Converts a center (lat, lon) into a lat/lon bounding box.
     *
     * @param {number} centerLat  — Latitude of the operator-specified center
     * @param {number} centerLon  — Longitude of the operator-specified center
     * @param {number} halfSizeM  — Half-width/height in metres (default 500 → 1 km box)
     * @returns {{ minLat, maxLat, minLon, maxLon, centerLat, centerLon, halfSizeM }}
     */
    function buildPriorBox(centerLat, centerLon, halfSizeM = 500) {
        // Convert half-size in metres to degrees (flat-earth approximation)
        const dLat = (halfSizeM / EARTH_R) * RAD2DEG;
        const dLon = (halfSizeM / (EARTH_R * Math.cos(centerLat * DEG2RAD))) * RAD2DEG;
        return {
            centerLat,
            centerLon,
            halfSizeM,
            minLat: centerLat - dLat,
            maxLat: centerLat + dLat,
            minLon: centerLon - dLon,
            maxLon: centerLon + dLon,
        };
    }

    /**
     * [NEW] isInsidePriorBox
     * Fast AABB check in ENU space — is candidate cell (E, N) inside the
     * prior box expressed in ENU relative to priorBoxENU?
     *
     * @param {number} E             — Candidate cell East metres
     * @param {number} N             — Candidate cell North metres
     * @param {{ minE, maxE, minN, maxN }} priorBoxENU
     * @returns {boolean}
     */
    function isInsidePriorBox(E, N, priorBoxENU) {
        return (
            E >= priorBoxENU.minE && E <= priorBoxENU.maxE &&
            N >= priorBoxENU.minN && N <= priorBoxENU.maxN
        );
    }

    /**
     * [NEW] isCellInsideActiveMasks
     * Returns true if the candidate cell satisfies whatever search-area
     * overlays are currently active (rectangle AABB and/or polygon).
     * If neither mask is active this always returns true.
     *
     * This lets the Bayesian grid respect the same masks that already
     * filter observations — the prior box is the outer boundary, and
     * active masks are optional inner constraints.
     *
     * @param {number} E            — Candidate cell East metres (ENU, relative to refLat/refLon)
     * @param {number} N            — Candidate cell North metres
     * @param {number} refLat       — ENU reference latitude (= prior box center)
     * @param {number} refLon       — ENU reference longitude
     * @param {Object} config       — Same config object passed to filterStations/solve
     * @returns {boolean}
     */
    function isCellInsideActiveMasks(E, N, refLat, refLon, config) {
        // ── Rectangle AABB check ──
        if (config.filterSpatial && config.aabb) {
            const { minLat, maxLat, minLon, maxLon } = config.aabb;
            // Convert AABB corners to ENU relative to our reference origin
            const bMin = latLonToENU(minLat, minLon, refLat, refLon);
            const bMax = latLonToENU(maxLat, maxLon, refLat, refLon);
            const boxMinE = Math.min(bMin.E, bMax.E);
            const boxMaxE = Math.max(bMin.E, bMax.E);
            const boxMinN = Math.min(bMin.N, bMax.N);
            const boxMaxN = Math.max(bMin.N, bMax.N);
            if (E < boxMinE || E > boxMaxE || N < boxMinN || N > boxMaxN) {
                return false; // Cell is outside the rectangle mask
            }
        }

        // ── Polygon check ──
        if (config.filterPoly && config.polyBounds && config.polyBounds.length > 2) {
            const polyENU = config.polyBounds.map(p =>
                latLonToENU(p.lat, p.lon, refLat, refLon)
            );
            const pt = { x: E, y: N };
            if (!pointInPolygon2D(pt, polyENU)) {
                return false; // Cell is outside the polygon mask
            }
        }

        return true; // No active masks, or cell passes all of them
    }

    /**
     * [NEW] lsVsBayesianDisagreement
     * Computes the straight-line haversine distance between the LS-AoA
     * result and the Bayesian result. This is used as a stability metric:
     *   • Small disagreement  → both methods agree, high confidence
     *   • Large disagreement  → estimates are unstable, use caution
     *
     * @param {{ lat, lon }|null} lsResult
     * @param {{ lat, lon }|null} bayesResult
     * @returns {number|null}  Distance in metres, or null if either is missing
     */
    function lsVsBayesianDisagreement(lsResult, bayesResult) {
        if (!lsResult || !bayesResult) return null;
        return distanceMeters(lsResult.lat, lsResult.lon, bayesResult.lat, bayesResult.lon);
    }

    // ── Bayesian Grid Solver (UPGRADED) ──────────────────────────

    /**
     * bayesianGrid
     * Bayesian spatial grid scoring of candidate target locations.
     *
     * UPGRADE: If `priorConfig` is provided (with centerLat/centerLon),
     * the search domain is a 1 km × 1 km box around that center, evaluated
     * at 5 m grid resolution. This is ~40 000 cells vs the old ~22 500 cells
     * at 100 m, but confined to the area that matters.
     *
     * If `priorConfig` is absent, the original 15 km / 100 m fallback runs.
     *
     * Active rectangle/polygon masks are applied to skip cells outside them.
     *
     * @param {Array}  stations    — Filtered station observations
     * @param {Object} [priorConfig] — { centerLat, centerLon, halfSizeM? }
     * @param {Object} [config]    — Filtering config (aabb, filterSpatial, etc.)
     * @returns {{ lat, lon, residual_m, stationsUsed, heatGrid,
     *             lsDisagreement_m }} | null
     */
    function bayesianGrid(stations, priorConfig = null, config = {}) {
        if (!stations || stations.length < 2) return null;

        // ── Step 1: Determine the search domain ──────────────────
        // [NEW] If we have a prior center, build a small tight box.
        // Otherwise fall back to the old behaviour (LS-AoA center, 15 km grid).

        let refLat, refLon, GRID_HALF_M, STEP_M;

        if (priorConfig && priorConfig.centerLat != null && priorConfig.centerLon != null) {
            // ── [NEW] Prior-box mode: 1 km × 1 km at 5 m steps ──
            const halfSize = priorConfig.halfSizeM ?? 500; // default 500 m → 1 km box
            refLat    = priorConfig.centerLat;
            refLon    = priorConfig.centerLon;
            GRID_HALF_M = halfSize;
            STEP_M    = 5; // 5 m resolution inside the prior box
            console.log(`[Bayesian] Prior-box mode: center=(${refLat.toFixed(6)}, ${refLon.toFixed(6)}), ` +
                        `box=${halfSize*2} m, step=${STEP_M} m`);
        } else {
            // ── Legacy mode: large 15 km grid centred on LS-AoA ──
            const lsFallback = lsAoA(stations);
            refLat = lsFallback ? lsFallback.lat
                                : stations.reduce((s, st) => s + st.lat, 0) / stations.length;
            refLon = lsFallback ? lsFallback.lon
                                : stations.reduce((s, st) => s + st.lon, 0) / stations.length;
            GRID_HALF_M = 7500; // 15 km total
            STEP_M      = 100;  // 100 m resolution
            console.log(`[Bayesian] Legacy mode: 15 km grid at 100 m steps`);
        }

        // ── Step 2: Pre-build prior-box ENU bounds for fast cell check ─
        // [NEW] In prior-box mode we use these for the cell loop bounds.
        const priorBoxENU = {
            minE: -GRID_HALF_M, maxE: GRID_HALF_M,
            minN: -GRID_HALF_M, maxN: GRID_HALF_M,
        };

        const SIGMA = 5.0; // degrees std deviation for bearing blur (unchanged)

        let maxScore  = -Infinity;
        let bestE = 0, bestN = 0;
        const heatPoints = [];

        // Pre-convert stations to ENU relative to our reference origin
        const enuStations = stations.map(st => ({
            ...st,
            enu: latLonToENU(st.lat, st.lon, refLat, refLon)
        }));

        // ── Step 3: Traverse the grid ────────────────────────────
        for (let y = -GRID_HALF_M; y <= GRID_HALF_M; y += STEP_M) {
            for (let x = -GRID_HALF_M; x <= GRID_HALF_M; x += STEP_M) {

                // [NEW] Skip cell if it falls outside active rectangle/polygon masks.
                // Prior box is already the loop boundary, so we only need to check
                // the additional user-drawn overlays here.
                if (!isCellInsideActiveMasks(x, y, refLat, refLon, config)) {
                    continue;
                }

                // Score this cell: sum of weighted log-probabilities
                let logScore = 0;
                for (const st of enuStations) {
                    const dx = x - st.enu.E;
                    const dy = y - st.enu.N;

                    const mathAngle = Math.atan2(dy, dx) * RAD2DEG;
                    let targetBearing = 90 - mathAngle;
                    if (targetBearing < 0) targetBearing += 360;

                    let diff = Math.abs(targetBearing - st.bearing_deg) % 360;
                    if (diff > 180) diff = 360 - diff;

                    const weight = st.confidence ?? 1.0;
                    logScore += weight * (-(diff * diff) / (2 * SIGMA * SIGMA));
                }

                if (logScore > maxScore) {
                    maxScore = logScore;
                    bestE = x;
                    bestN = y;
                }
                heatPoints.push({ x, y, score: logScore });
            }
        }

        // ── Step 4: Normalise heat scores to probabilities ───────
        // (same logic as before — unchanged)
        const visualGrid = heatPoints
            .map(pt => {
                pt.prob = Math.exp(pt.score - maxScore); // peak cell = 1.0
                return pt;
            })
            .filter(pt => pt.prob > 0.1)
            .map(pt => {
                const ll = enuToLatLon(pt.x, pt.y, refLat, refLon);
                return [ll.lat, ll.lon, pt.prob];
            });

        const resultLatLon = enuToLatLon(bestE, bestN, refLat, refLon);

        // Geometric residual (same formula as before)
        let totalResidual = 0;
        for (const st of enuStations) {
            const theta = (90 - st.bearing_deg) * DEG2RAD;
            const dist = Math.abs(
                Math.sin(theta) * (bestE - st.enu.E) -
                Math.cos(theta) * (bestN - st.enu.N)
            );
            totalResidual += dist;
        }

        return {
            lat: resultLatLon.lat,
            lon: resultLatLon.lon,
            residual_m: totalResidual / stations.length,
            stationsUsed: stations.length,
            heatGrid: visualGrid,
            // [NEW] lsDisagreement_m is filled in by solve() below
            lsDisagreement_m: null,
        };
    }

    // ── Geometry Helpers (all unchanged) ─────────────────────────

    function getIntersection(a, b, refLat, refLon) {
        const pA = latLonToENU(a.lat, a.lon, refLat, refLon);
        const pB = latLonToENU(b.lat, b.lon, refLat, refLon);
        const tA = (90 - a.bearing_deg) * DEG2RAD;
        const tB = (90 - b.bearing_deg) * DEG2RAD;
        const dA = { x: Math.cos(tA), y: Math.sin(tA) };
        const dB = { x: Math.cos(tB), y: Math.sin(tB) };
        const dx = pB.E - pA.E;
        const dy = pB.N - pA.N;
        const cross = dA.x * dB.y - dA.y * dB.x;
        if (Math.abs(cross) < 1e-5) return null;
        const t = (dx * dB.y - dy * dB.x) / cross;
        const ix = pA.E + t * dA.x;
        const iy = pA.N + t * dA.y;
        const dpA = (ix - pA.E)*dA.x + (iy - pA.N)*dA.y;
        const dpB = (ix - pB.E)*dB.x + (iy - pB.N)*dB.y;
        if (dpA < 0 || dpB < 0) return null;
        return { E: ix, N: iy };
    }

    function rayAABBIntersect(origin, dir, min, max) {
        let tmin = -Infinity, tmax = Infinity;
        if (dir.x !== 0) {
            let t1 = (min.x - origin.x) / dir.x;
            let t2 = (max.x - origin.x) / dir.x;
            tmin = Math.max(tmin, Math.min(t1, t2));
            tmax = Math.min(tmax, Math.max(t1, t2));
        } else if (origin.x < min.x || origin.x > max.x) {
            return false;
        }
        if (dir.y !== 0) {
            let t1 = (min.y - origin.y) / dir.y;
            let t2 = (max.y - origin.y) / dir.y;
            tmin = Math.max(tmin, Math.min(t1, t2));
            tmax = Math.min(tmax, Math.max(t1, t2));
        } else if (origin.y < min.y || origin.y > max.y) {
            return false;
        }
        return tmax >= Math.max(0, tmin);
    }

    function pointInPolygon2D(pt, poly) {
        let inside = false;
        for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
            const xi = poly[i].E, yi = poly[i].N;
            const xj = poly[j].E, yj = poly[j].N;
            const intersect = ((yi > pt.y) !== (yj > pt.y)) &&
                              (pt.x < (xj - xi) * (pt.y - yi) / (yj - yi) + xi);
            if (intersect) inside = !inside;
        }
        return inside;
    }

    function raySegmentIntersect2D(origin, dir, p1, p2) {
        const dx = dir.x, dy = dir.y;
        const vx = p2.E - p1.E, vy = p2.N - p1.N;
        const wx = p1.E - origin.x, wy = p1.N - origin.y;
        const det = vx * dy - vy * dx;
        if (Math.abs(det) < 1e-6) return false;
        const t = (vx * wy - vy * wx) / det;
        const u = (dx * wy - dy * wx) / det;
        return (t >= 0 && u >= 0 && u <= 1);
    }

    // ── filterStations (unchanged) ────────────────────────────────

    function filterStations(stations, config) {
        if (!stations || stations.length < 1) return stations;
        let filtered = [...stations];

        if (config.filterSpatial && config.aabb) {
            const { minLat, maxLat, minLon, maxLon } = config.aabb;
            const refLat = (minLat + maxLat) / 2;
            const refLon = (minLon + maxLon) / 2;
            const bMin = latLonToENU(minLat, minLon, refLat, refLon);
            const bMax = latLonToENU(maxLat, maxLon, refLat, refLon);
            filtered = filtered.filter(st => {
                const origin = latLonToENU(st.lat, st.lon, refLat, refLon);
                const theta = (90 - st.bearing_deg) * DEG2RAD;
                const dir = { x: Math.cos(theta), y: Math.sin(theta) };
                const boxMin = { x: Math.min(bMin.E, bMax.E), y: Math.min(bMin.N, bMax.N) };
                const boxMax = { x: Math.max(bMin.E, bMax.E), y: Math.max(bMin.N, bMax.N) };
                return rayAABBIntersect({ x: origin.E, y: origin.N }, dir, boxMin, boxMax);
            });
        }

        if (config.filterPoly && config.polyBounds && config.polyBounds.length > 2) {
            const refLat = config.polyBounds[0].lat;
            const refLon = config.polyBounds[0].lon;
            const polyENU = config.polyBounds.map(p => latLonToENU(p.lat, p.lon, refLat, refLon));
            filtered = filtered.filter(st => {
                const origin = latLonToENU(st.lat, st.lon, refLat, refLon);
                const theta = (90 - st.bearing_deg) * DEG2RAD;
                const dir = { x: Math.cos(theta), y: Math.sin(theta) };
                const oPt = { x: origin.E, y: origin.N };
                if (pointInPolygon2D(oPt, polyENU)) return true;
                for (let i = 0, j = polyENU.length - 1; i < polyENU.length; j = i++) {
                    if (raySegmentIntersect2D(oPt, dir, polyENU[j], polyENU[i])) {
                        return true;
                    }
                }
                return false;
            });
        }

        if (filtered.length < 2) return filtered;

        if (config.filterAngular) {
            const minAngleSep = 2.0;
            const pruned = [];
            for (const st of filtered) {
                let tooClose = false;
                for (const other of pruned) {
                    let diff = Math.abs(st.bearing_deg - other.bearing_deg) % 360;
                    if (diff > 180) diff = 360 - diff;
                    if (diff < minAngleSep || Math.abs(180 - diff) < minAngleSep) {
                        tooClose = true;
                        break;
                    }
                }
                if (!tooClose || pruned.length === 0) {
                    pruned.push(st);
                }
            }
            if (pruned.length >= 2) {
                filtered = pruned;
            }
        }

        if (config.filterSpatial && filtered.length > 2) {
            const refLat = filtered[0].lat;
            const refLon = filtered[0].lon;
            const intersections = [];
            for (let i = 0; i < filtered.length; i++) {
                for (let j = i + 1; j < filtered.length; j++) {
                    const ix = getIntersection(filtered[i], filtered[j], refLat, refLon);
                    if (ix) intersections.push(ix);
                }
            }
            if (intersections.length > 0) {
                intersections.sort((a,b) => a.E - b.E);
                const medE = intersections[Math.floor(intersections.length / 2)].E;
                intersections.sort((a,b) => a.N - b.N);
                const medN = intersections[Math.floor(intersections.length / 2)].N;
                const inliers = filtered.filter(st => {
                    const p = latLonToENU(st.lat, st.lon, refLat, refLon);
                    const theta = (90 - st.bearing_deg) * DEG2RAD;
                    const sinT = Math.sin(theta);
                    const cosT = Math.cos(theta);
                    const dist = Math.abs(sinT * (medE - p.E) - cosT * (medN - p.N));
                    return dist < 200;
                });
                if (inliers.length >= 2) {
                    filtered = inliers;
                }
            }
        }

        return filtered;
    }

    // ── Distance Helpers (unchanged) ─────────────────────────────

    function distanceMeters(lat1, lon1, lat2, lon2) {
        const dLat = (lat2 - lat1) * DEG2RAD;
        const dLon = (lon2 - lon1) * DEG2RAD;
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                  Math.cos(lat1 * DEG2RAD) * Math.cos(lat2 * DEG2RAD) *
                  Math.sin(dLon / 2) * Math.sin(dLon / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return EARTH_R * c;
    }

    function distanceFeet(lat1, lon1, lat2, lon2) {
        return distanceMeters(lat1, lon1, lat2, lon2) * 3.28084;
    }

    // ── Public API ────────────────────────────────────────────────

    return {
        lsAoA,
        midpoint,
        bayesianGrid,
        filterStations,
        distanceMeters,
        distanceFeet,
        buildPriorBox,            // [NEW] exposed for main.js preview/debug
        lsVsBayesianDisagreement, // [NEW] exposed for main.js diagnostic display

        /**
         * Main entry: picks algorithm based on settings.
         *
         * HYBRID UPGRADE: For 'bayesian', this now:
         *   1. Runs the normal filtering pipeline (unchanged)
         *   2. Runs LS-AoA as a fast background estimate
         *   3. Runs Bayesian inside the prior box (if priorConfig given)
         *   4. Returns the Bayesian result as the final answer, with
         *      `lsResult` and `lsDisagreement_m` attached as diagnostics
         *
         * @param {Array}  stations  — raw station objects (pre-filtering)
         * @param {string} algo      — 'ls_aoa' | 'midpoint' | 'bayesian'
         * @param {Object} config    — filtering options map; may contain:
         *                             config.priorConfig = { centerLat, centerLon, halfSizeM? }
         */
        solve(stations, algo = 'ls_aoa', config = {}) {
            const filtered = this.filterStations(stations, config);
            if (!filtered || filtered.length < 2) return null;

            // ── Midpoint: unchanged ──
            if (algo === 'midpoint' && filtered.length === 2) {
                return midpoint(filtered);
            }

            // ── LS-AoA: unchanged ──
            if (algo === 'ls_aoa') {
                return lsAoA(filtered);
            }

            // ── [NEW] Hybrid Bayesian flow ────────────────────────
            if (algo === 'bayesian') {
                // Option A: LS-AoA runs first as a fast background estimate.
                // It is NOT returned to the user — Bayesian is the final answer.
                const lsResult = lsAoA(filtered);

                // Pull the operator-defined prior center out of config (may be null).
                // config.priorConfig = { centerLat, centerLon, halfSizeM? }
                const priorConfig = config.priorConfig ?? null;

                // Run Bayesian inside the prior box (or legacy grid if no prior given).
                // Pass config so isCellInsideActiveMasks can check rect/poly overlays.
                const bayesResult = bayesianGrid(filtered, priorConfig, config);

                if (!bayesResult) return lsResult; // fallback: return LS if Bayes failed

                // Option B: attach the LS vs Bayesian disagreement distance as a
                // stability metric. Large values = the two methods disagree = less trust.
                const disagreement = lsVsBayesianDisagreement(lsResult, bayesResult);
                bayesResult.lsDisagreement_m = disagreement;

                // Also expose the raw LS result on the object for optional display in UI
                bayesResult.lsResult = lsResult ?? null;

                // Log the diagnostic to console for the engineering team
                if (disagreement !== null) {
                    console.log(`[Hybrid] LS=(${lsResult.lat.toFixed(6)}, ${lsResult.lon.toFixed(6)}) ` +
                                `Bayes=(${bayesResult.lat.toFixed(6)}, ${bayesResult.lon.toFixed(6)}) ` +
                                `disagreement=${disagreement.toFixed(1)} m`);
                }

                // Final result: Bayesian wins (refined estimate)
                return bayesResult;
            }

            // Fallback — should not reach here
            return lsAoA(filtered);
        },
    };
})();