/**
 * main.js — App Orchestrator (Single Mobile KrakenSDR Model)
 * ===========================================================
 * Wires tab routing, settings, bearing log, and the
 * full data pipeline:
 *   DataFeed -> Triangulation.solve(observation_history) -> MapView + HeatmapView
 *
 * ── WHAT CHANGED (v1.2 hybrid upgrade) ──────────────────────────
 *   FILE: main.js
 *
 *   1) Prior box state variables added:
 *        _priorLat, _priorLon  — operator-typed center coordinates
 *        _priorBoxLayer        — Leaflet rectangle showing the box on the map
 *
 *   2) _getPriorConfig()
 *        Reads the prior lat/lon inputs and returns a priorConfig object
 *        { centerLat, centerLon, halfSizeM: 500 } for triangulation.js,
 *        or null if no valid center has been entered.
 *
 *   3) _drawPriorBoxOnMap(priorConfig)
 *        Draws/updates a dashed cyan rectangle on the main map showing
 *        the 1 km × 1 km prior search box. Clears old box on each call.
 *
 *   4) Prior box UI wiring (DOMContentLoaded block):
 *        • 'prior-lat' and 'prior-lon' inputs → update state + redraw box
 *        • 'btn-prior-clear' → clears box and inputs
 *        Both are wired inside the existing DOMContentLoaded listener.
 *
 *   5) _processData() — changed section:
 *        config.priorConfig is now populated from _getPriorConfig().
 *        The Bayesian solver receives this so it knows where to search.
 *
 *   6) updateResultPanel() — changed section:
 *        If the result carries `lsDisagreement_m` (only set by hybrid
 *        Bayesian), it is displayed in the sidebar as "LS vs Bayes".
 *        The element id is 'res-ls-disagreement' (new HTML element in
 *        index.html — see paste instructions below).
 *
 *   EVERYTHING ELSE is unchanged:
 *        Tab routing, convergence, estimation log, heatmap controls,
 *        mask sync, filter wiring, DataFeed, MapView calls — all identical.
 *
 * ── ASSUMPTIONS ──────────────────────────────────────────────────
 *   • index.html has two new <input> elements:
 *       id="prior-lat"   (number, step=0.000001)
 *       id="prior-lon"   (number, step=0.000001)
 *     and a clear button:
 *       id="btn-prior-clear"
 *     and a result display span:
 *       id="res-ls-disagreement"
 *     See index.html for the exact snippet to add.
 *   • MapView is already initialised before _drawPriorBoxOnMap runs.
 *   • The prior box is drawn on the existing 'map' Leaflet instance
 *     via MapView.getMap() (a one-line getter added to map.js — see note).
 */

(function () {

    // ── Tab Routing ────────────────────────────────────────────────
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanels  = document.querySelectorAll('.tab-panel');

    let _estimationMap = null;
    let _estimationMarkers = null;
    let _estimationHits = [];
    let _estIdCounter = 0;

    function initEstimationMap() {
        if (_estimationMap) {
            _estimationMap.invalidateSize();
            return;
        }
        _estimationMap = L.map('estimation-map', { zoomControl: true });
        _estimationMap.setView([0, 0], 2);

        const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap'
        });
        tileLayer.addTo(_estimationMap);
        _estimationMarkers = L.layerGroup().addTo(_estimationMap);

        const elTile = document.getElementById('setting-tile');
        if (elTile && typeof TILE_CONFIGS !== 'undefined') {
            const tc = TILE_CONFIGS[elTile.value] || TILE_CONFIGS['osm'];
            tileLayer.setUrl(tc.url);
        }
    }

    function switchTab(targetId) {
        tabButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.tab === targetId));
        tabPanels.forEach(panel => {
            panel.classList.toggle('active', panel.id === `panel-${targetId}`);
        });
        if (targetId === 'map') requestAnimationFrame(() => MapView.invalidateSize());
        if (targetId === 'estimation') requestAnimationFrame(() => initEstimationMap());
    }

    function _formatCoord(c) {
        return c.toFixed(6);
    }

    // ── [NEW] Prior Box State ──────────────────────────────────────
    // Stores the operator-entered prior center. Null = prior box inactive.
    let _priorLat = null;
    let _priorLon = null;
    let _priorBoxLayer = null; // Leaflet rectangle on the main map

    /**
     * [NEW] _getPriorConfig
     * Reads the prior lat/lon inputs and returns a priorConfig object
     * ready to pass into Triangulation.solve(), or null if not set.
     * halfSizeM = 500 → 1 km × 1 km box.
     */
    function _getPriorConfig() {
        if (_priorLat == null || _priorLon == null) return null;
        if (isNaN(_priorLat) || isNaN(_priorLon)) return null;
        return {
            centerLat: _priorLat,
            centerLon: _priorLon,
            halfSizeM: 500, // 500 m each direction → 1 km × 1 km
        };
    }

    /**
     * [NEW] _drawPriorBoxOnMap
     * Draws (or redraws) the 1 km × 1 km prior search box as a dashed
     * cyan rectangle on the main GPS map, so the operator can see it.
     * Clears the previous box layer before drawing a new one.
     *
     * Uses MapView.getMap() — a tiny one-liner getter in map.js.
     * If MapView.getMap is not yet available this silently skips.
     */
    function _drawPriorBoxOnMap(priorConfig) {
        // Remove old box if present
        if (_priorBoxLayer) {
            if (typeof MapView.getMap === 'function') {
                MapView.getMap().removeLayer(_priorBoxLayer);
            }
            _priorBoxLayer = null;
        }
        if (!priorConfig) return;

        // Build lat/lon bounding box from priorConfig
        const box = Triangulation.buildPriorBox(
            priorConfig.centerLat,
            priorConfig.centerLon,
            priorConfig.halfSizeM
        );

        if (typeof MapView.getMap !== 'function') {
            // map.js doesn't expose getMap yet — skip visual, math still works
            console.warn('[PriorBox] MapView.getMap() not available — box not drawn on map.');
            return;
        }

        const map = MapView.getMap();
        _priorBoxLayer = L.rectangle(
            [[box.minLat, box.minLon], [box.maxLat, box.maxLon]],
            {
                color: '#00d4ff',       // accent-cyan
                weight: 2,
                dashArray: '6 4',
                fill: true,
                fillColor: '#00d4ff',
                fillOpacity: 0.04,
                interactive: false,
            }
        ).addTo(map);

        // Tooltip so operator can confirm center
        _priorBoxLayer.bindTooltip(
            `Prior Box: ${priorConfig.centerLat.toFixed(6)}, ${priorConfig.centerLon.toFixed(6)}`,
            { permanent: false, direction: 'top' }
        );
    }

    // ── Convergence Computation (unchanged) ───────────────────────

    function _computeConvergence() {
        if (_estimationHits.length < 2) return null;

        let totalWeight = 0;
        let wLat = 0, wLon = 0;

        for (const hit of _estimationHits) {
            const residual = Math.max(hit.residual_m ?? 1, 0.1);
            const w = 1.0 / residual;
            wLat += w * hit.lat;
            wLon += w * hit.lon;
            totalWeight += w;
        }

        const cLat = wLat / totalWeight;
        const cLon = wLon / totalWeight;

        let wSumSqDist = 0;
        for (const hit of _estimationHits) {
            const residual = Math.max(hit.residual_m ?? 1, 0.1);
            const w = 1.0 / residual;
            const distM = Triangulation.distanceMeters(cLat, cLon, hit.lat, hit.lon);
            wSumSqDist += w * distM * distM;
        }
        const spreadM = Math.sqrt(wSumSqDist / totalWeight);

        return {
            lat: cLat,
            lon: cLon,
            spreadM: spreadM,
            count: _estimationHits.length
        };
    }

    function _renderEstimationLog() {
        const histContainer = document.getElementById('est-log-history');
        const hitCountEl = document.getElementById('est-hit-count');
        if (!histContainer) return;

        const convergenceEnabled = document.getElementById('setting-convergence')?.checked ?? true;
        _updateConvergedCard(convergenceEnabled);

        histContainer.innerHTML = '';
        if (hitCountEl) hitCountEl.textContent = `${_estimationHits.length} hits`;

        if (_estimationHits.length === 0) {
            histContainer.innerHTML = `<div style="font-size:0.75rem; color:var(--text-muted); font-style:italic; padding:8px; text-align:center;">No hits recorded inside search area.</div>`;
            return;
        }

        const normHits = [..._estimationHits].reverse();

        normHits.forEach(hit => {
            const itemDiv = document.createElement('div');
            itemDiv.className = `estimation-item significant`;
            const residualLabel = hit.residual_m != null ? hit.residual_m.toFixed(1) + ' m' : '—';
            itemDiv.innerHTML = `
                <div class="est-row">
                    <span>Lat/Lon</span>
                    <span class="est-val">${_formatCoord(hit.lat)}, ${_formatCoord(hit.lon)}</span>
                </div>
                <div class="est-row">
                    <span>Residual</span>
                    <span class="est-val">${residualLabel}</span>
                </div>
                <div class="est-row">
                    <span>Time</span>
                    <span class="est-val">${new Date(hit.timestamp).toLocaleTimeString()}</span>
                </div>
                <div class="est-actions">
                    <button class="est-btn transmit" data-id="${hit.id}">Transmit</button>
                    <button class="est-btn delete" data-id="${hit.id}">Delete</button>
                </div>
            `;
            histContainer.appendChild(itemDiv);
        });

        document.querySelectorAll('.est-btn.transmit').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = parseInt(e.target.dataset.id);
                const hit = _estimationHits.find(h => h.id === id);
                if (hit) {
                    console.log(`[Telemetry] TRANSMITTING: ${hit.lat}, ${hit.lon}`);
                    alert(`Transmitted coordinates to GCS: \nLat: ${hit.lat}\nLon: ${hit.lon}`);
                }
            });
        });
        document.querySelectorAll('.est-btn.delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = parseInt(e.target.dataset.id);
                _estimationHits = _estimationHits.filter(h => h.id !== id);
                _redrawEstimationMarkers();
                _renderEstimationLog();
            });
        });
    }

    function _updateConvergedCard(enabled) {
        const card = document.getElementById('converged-estimate-card');
        const badge = document.getElementById('converged-status-badge');
        const btnTransmit = document.getElementById('btn-conv-transmit');
        if (!card) return;

        if (!enabled) {
            card.className = 'converged-card converged-disabled';
            if (badge) badge.textContent = 'OFF';
            if (btnTransmit) btnTransmit.disabled = true;
            return;
        }

        const conv = _computeConvergence();

        if (!conv) {
            card.className = 'converged-card converged-active';
            if (badge) badge.textContent = _estimationHits.length === 0 ? 'WAITING' : '1 HIT';
            document.getElementById('conv-lat').textContent = _estimationHits.length === 1 ? _estimationHits[0].lat.toFixed(6) + '°' : '—';
            document.getElementById('conv-lon').textContent = _estimationHits.length === 1 ? _estimationHits[0].lon.toFixed(6) + '°' : '—';
            document.getElementById('conv-count').textContent = `${_estimationHits.length} hits`;
            document.getElementById('conv-spread').textContent = '—';
            if (btnTransmit) btnTransmit.disabled = _estimationHits.length < 1;
            return;
        }

        card.className = 'converged-card converged-active';
        if (badge) badge.textContent = 'LIVE';

        document.getElementById('conv-lat').textContent = conv.lat.toFixed(6) + '°';
        document.getElementById('conv-lon').textContent = conv.lon.toFixed(6) + '°';
        document.getElementById('conv-count').textContent = `${conv.count} hits`;

        const isImperial = document.getElementById('setting-units')?.value === 'imperial';
        if (isImperial) {
            const spreadFt = conv.spreadM * 3.28084;
            document.getElementById('conv-spread').textContent = spreadFt >= 5280
                ? `± ${(spreadFt / 5280).toFixed(2)} mi`
                : `± ${spreadFt.toFixed(1)} ft`;
        } else {
            document.getElementById('conv-spread').textContent = conv.spreadM >= 1000
                ? `± ${(conv.spreadM / 1000).toFixed(2)} km`
                : `± ${conv.spreadM.toFixed(1)} m`;
        }

        if (btnTransmit) btnTransmit.disabled = false;
    }

    function _redrawEstimationMarkers() {
        if (!_estimationMarkers) return;
        _estimationMarkers.clearLayers();

        _estimationHits.forEach(hit => {
            L.circleMarker([hit.lat, hit.lon], {
                radius: 5,
                color: '#fff',
                weight: 1,
                fillColor: '#00e87a',
                fillOpacity: 0.8
            }).addTo(_estimationMarkers);
        });

        const convergenceEnabled = document.getElementById('setting-convergence')?.checked ?? true;
        if (convergenceEnabled) {
            const conv = _computeConvergence();
            if (conv) {
                L.circleMarker([conv.lat, conv.lon], {
                    radius: 14,
                    color: '#00e87a',
                    weight: 2,
                    fillColor: '#00e87a',
                    fillOpacity: 0.12,
                    dashArray: '4 4'
                }).addTo(_estimationMarkers);

                L.circleMarker([conv.lat, conv.lon], {
                    radius: 7,
                    color: '#fff',
                    weight: 2,
                    fillColor: '#00e87a',
                    fillOpacity: 1.0
                }).addTo(_estimationMarkers)
                    .bindTooltip(`Converged: ${conv.lat.toFixed(6)}, ${conv.lon.toFixed(6)}`, {
                        permanent: false,
                        direction: 'top',
                        offset: [0, -12]
                    });
            }
        }
    }

    function _addEstimationHit(result) {
        const isSpam = _estimationHits.some(h => {
            if (Triangulation && Triangulation.distanceMeters) {
                return Triangulation.distanceMeters(h.lat, h.lon, result.lat, result.lon) < 1.0;
            }
            return Math.abs(h.lat - result.lat) < 0.00001 && Math.abs(h.lon - result.lon) < 0.00001;
        });

        if (isSpam) return;

        const hit = {
            id: ++_estIdCounter,
            lat: result.lat,
            lon: result.lon,
            residual_m: result.residual_m ?? null,
            timestamp: Date.now()
        };

        _estimationHits.push(hit);
        _redrawEstimationMarkers();
        _renderEstimationLog();

        if (_estimationMap && _estimationMap.getZoom() === 2) {
            _estimationMap.setView([result.lat, result.lon], 17);
        }
    }

    // ── DOMContentLoaded: button wiring ───────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('btn-est-clear-all')?.addEventListener('click', () => {
            if (confirm("Clear all estimation history?")) {
                _estimationHits = [];
                _redrawEstimationMarkers();
                _renderEstimationLog();
            }
        });

        document.getElementById('btn-conv-transmit')?.addEventListener('click', () => {
            const convergenceEnabled = document.getElementById('setting-convergence')?.checked ?? true;
            if (!convergenceEnabled) return;

            const conv = _computeConvergence();
            if (conv) {
                console.log(`[Telemetry] TRANSMITTING CONVERGED: ${conv.lat}, ${conv.lon} (±${conv.spreadM.toFixed(1)}m, ${conv.count} hits)`);
                alert(`Transmitted CONVERGED coordinates to GCS:\nLat: ${conv.lat.toFixed(6)}\nLon: ${conv.lon.toFixed(6)}\nSpread: ±${conv.spreadM.toFixed(1)}m\nBased on: ${conv.count} hits`);
            } else if (_estimationHits.length === 1) {
                const hit = _estimationHits[0];
                console.log(`[Telemetry] TRANSMITTING SINGLE: ${hit.lat}, ${hit.lon}`);
                alert(`Transmitted coordinates to GCS:\nLat: ${hit.lat.toFixed(6)}\nLon: ${hit.lon.toFixed(6)}`);
            }
        });

        // ── [NEW] Prior Box UI Wiring ────────────────────────────
        // Wire the prior-lat and prior-lon inputs so that whenever the
        // operator types a center coordinate, the prior box is immediately
        // redrawn on the map and the next solve uses it.

        const elPriorLat = document.getElementById('prior-lat');
        const elPriorLon = document.getElementById('prior-lon');
        const elPriorClear = document.getElementById('btn-prior-clear');

        function _onPriorChange() {
            const lat = parseFloat(elPriorLat?.value);
            const lon = parseFloat(elPriorLon?.value);
            _priorLat = isNaN(lat) ? null : lat;
            _priorLon = isNaN(lon) ? null : lon;

            // Redraw (or clear) the prior box rectangle on the main map
            const pc = _getPriorConfig();
            _drawPriorBoxOnMap(pc);

            // Immediately re-solve with the new prior if we have data
            if (_lastData) _processData(_lastData);
        }

        elPriorLat?.addEventListener('change', _onPriorChange);
        elPriorLon?.addEventListener('change', _onPriorChange);

        // Clear button: wipe inputs, remove box, re-solve without prior
        elPriorClear?.addEventListener('click', () => {
            if (elPriorLat) elPriorLat.value = '';
            if (elPriorLon) elPriorLon.value = '';
            _priorLat = null;
            _priorLon = null;
            _drawPriorBoxOnMap(null);
            if (_lastData) _processData(_lastData);
        });
        // ── end prior box wiring ─────────────────────────────────
    });

    tabButtons.forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
    switchTab('map');

    // ── Settings Wiring (unchanged) ───────────────────────────────
    const elPollInterval  = document.getElementById('setting-poll-interval');
    const elTile          = document.getElementById('setting-tile');
    const elUncertainty   = document.getElementById('setting-uncertainty');
    const elLineLength    = document.getElementById('setting-line-length');
    const elAlgo          = document.getElementById('setting-algo');
    const elMinConf       = document.getElementById('setting-min-conf');
    const elUnits         = document.getElementById('setting-units');
    const elConvergence   = document.getElementById('setting-convergence');

    function bindSetting(el) {
        if (!el) return;
        const key = `kraken_setting_${el.id}`;
        const saved = localStorage.getItem(key);
        if (saved !== null) {
            if (el.type === 'checkbox') el.checked = (saved === 'true');
            else el.value = saved;
        }
        el.addEventListener('change', () => {
            const val = el.type === 'checkbox' ? el.checked : el.value;
            localStorage.setItem(key, val);
        });
    }

    const _allSettings = [elPollInterval, elTile, elUncertainty, elLineLength, elAlgo, elMinConf, elUnits,
        document.getElementById('setting-filter-spatial'),
        document.getElementById('setting-filter-temporal'),
        document.getElementById('setting-filter-attitude'),
        document.getElementById('setting-filter-angular'),
        elConvergence];

    _allSettings.forEach(bindSetting);

    elConvergence?.addEventListener('change', () => {
        _renderEstimationLog();
    });

    elPollInterval?.addEventListener('change', () =>
        DataFeed.setPollInterval(parseInt(elPollInterval.value, 10) || 2000));
    elTile?.addEventListener('change', () => MapView.setTile(elTile.value));
    elUncertainty?.addEventListener('change', () => MapView.setShowUncertainty(elUncertainty.checked));
    elLineLength?.addEventListener('change', () => {
        const isImp = document.getElementById('setting-units')?.value === 'imperial';
        let len = parseFloat(elLineLength.value) || 2;
        if (isImp) len = len * 1.60934;
        MapView.setLineLength(len);
        if (_lastData) _processData(_lastData);
    });

    const elFilterSpatial = document.getElementById('setting-filter-spatial');
    const elFilterTemporal = document.getElementById('setting-filter-temporal');
    const elFilterAttitude = document.getElementById('setting-filter-attitude');
    const elFilterAngular = document.getElementById('setting-filter-angular');

    [elFilterSpatial, elFilterTemporal, elFilterAttitude, elFilterAngular, elAlgo, elMinConf].forEach(el => {
        el?.addEventListener('change', () => {
            if (_lastData) _processData(_lastData);
        });
    });

    elUnits?.addEventListener('change', () => {
        MapView.refreshCustomMarkers();

        const isImperial = elUnits.value === 'imperial';
        const isPrevImperial = elUnits.dataset.prev === 'imperial';

        document.querySelectorAll('.mask-unit-lbl').forEach(lbl => {
            lbl.textContent = isImperial ? 'mi' : 'km';
        });

        const lineLenLbl = document.getElementById('line-length-unit');
        if (lineLenLbl) lineLenLbl.textContent = isImperial ? 'mi' : 'km';

        if (elUnits.dataset.prev && isImperial !== isPrevImperial) {
            if (elLineLength) {
                let v = parseFloat(elLineLength.value);
                if (!isNaN(v)) {
                    elLineLength.value = isImperial ? (v / 1.60934).toFixed(1) : (v * 1.60934).toFixed(1);
                    elLineLength.dispatchEvent(new Event('change'));
                }
            }
        }

        elUnits.dataset.prev = elUnits.value;
        if (window._syncMaskUI) window._syncMaskUI();
        if (_lastData) _processData(_lastData);
    });
    elUnits.dataset.prev = elUnits.value;
    elUnits?.dispatchEvent(new Event('change'));

    document.getElementById('btn-shutdown')?.addEventListener('click', async () => {
        if (!confirm("Are you sure you want to stop the background tracking server? You will lose live telemetry. The terminal will exit.")) return;
        try {
            await fetch('/api/shutdown', { method: 'POST' });
            document.body.innerHTML = '<div style="display:flex; height:100vh; align-items:center; justify-content:center; color:#fff; text-align:center; font-family:sans-serif;"><h1>Server Shutdown Successfully. <br><span style="font-size:16px; color:#888;">You can safely close this browser tab.</span></h1></div>';
            setTimeout(() => window.close(), 500);
        } catch(e) {}
    });

    document.getElementById('btn-collapse-obs')?.addEventListener('click', () => {
        const card = document.getElementById('station-list-card');
        if (card) card.classList.toggle('obs-collapsed');
    });

    // ── Heatmap Controls (unchanged) ──────────────────────────────
    function wireSlider(id, valId, factor, setFn) {
        const slider = document.getElementById(id);
        const label  = document.getElementById(valId);
        if (!slider) return;
        slider.addEventListener('input', () => {
            const v = parseInt(slider.value, 10);
            label.textContent = factor ? (v * factor).toFixed(1) : v;
            setFn(factor ? v * factor : v);
        });
    }
    wireSlider('hm-radius',  'hm-radius-val',  null, MapView.setHeatRadius);
    wireSlider('hm-blur',    'hm-blur-val',    null, MapView.setHeatBlur);
    wireSlider('hm-opacity', 'hm-opacity-val', 0.1,  MapView.setHeatOpacity);
    document.getElementById('hm-clear-btn')?.addEventListener('click', MapView.clearHeat);

    // ── Global App Logic (unchanged) ──────────────────────────────
    window._triggerAppUpdate = () => { if (_lastData) _processData(_lastData); };

    document.getElementById('btn-master-clear')?.addEventListener('click', () => {
        if (!confirm('Clear all logged data, heatmaps, and running observation arrays?')) return;
        document.getElementById('log-clear-btn')?.click();
        MapView.clearHeat();
        if (_lastData && _lastData.observation_history) {
            _lastData.observation_history = [];
            _lastData.current_observation = null;
        }
        _processData(_lastData);
    });

    const syncMenuStates = () => {
        const maskToggle = document.getElementById('btn-draw-mask-toggle');
        const polyToggle = document.getElementById('btn-draw-poly-toggle');
        const maskBlock = document.getElementById('mask-tools-block');
        const polyBlock = document.getElementById('poly-tools-block');

        if (maskToggle && polyToggle && maskBlock && polyBlock) {
            const maskToggleRow = maskToggle.closest('div');
            const polyToggleRow = polyToggle.closest('div');

            maskBlock.style.opacity = '1'; maskBlock.style.pointerEvents = 'auto';
            polyBlock.style.opacity = '1'; polyBlock.style.pointerEvents = 'auto';
            if (maskToggleRow) { maskToggleRow.style.opacity = '1'; maskToggleRow.style.pointerEvents = 'auto'; maskToggle.disabled = false; }
            if (polyToggleRow) { polyToggleRow.style.opacity = '1'; polyToggleRow.style.pointerEvents = 'auto'; polyToggle.disabled = false; }

            if (maskToggle.checked) {
                polyBlock.style.opacity = '0.3'; polyBlock.style.pointerEvents = 'none';
                if (polyToggleRow) { polyToggleRow.style.opacity = '0.3'; polyToggleRow.style.pointerEvents = 'none'; polyToggle.disabled = true; }
            } else if (polyToggle.checked) {
                maskBlock.style.opacity = '0.3'; maskBlock.style.pointerEvents = 'none';
                if (maskToggleRow) { maskToggleRow.style.opacity = '0.3'; maskToggleRow.style.pointerEvents = 'none'; maskToggle.disabled = true; }
            }
        }
    };

    document.getElementById('btn-draw-mask-toggle')?.addEventListener('change', (e) => {
        if (!window.drawDefaultMask) return;
        if (e.target.checked) {
            const polyToggle = document.getElementById('btn-draw-poly-toggle');
            if (polyToggle && polyToggle.checked) {
                polyToggle.checked = false;
                if (window.clearPoly) window.clearPoly();
            }
            window.drawDefaultMask(null, null);
        } else {
            if (window.clearMask) window.clearMask();
        }
        syncMenuStates();
    });

    document.getElementById('btn-draw-poly-toggle')?.addEventListener('change', (e) => {
        if (!window.drawPolygonMask) return;
        if (e.target.checked) {
            const maskToggle = document.getElementById('btn-draw-mask-toggle');
            if (maskToggle && maskToggle.checked) {
                maskToggle.checked = false;
                if (window.clearMask) window.clearMask();
            }
            const verts = parseInt(document.getElementById('poly-vertices')?.value || 6);
            const color = document.getElementById('poly-color')?.value || '#fa8231';
            window.drawPolygonMask(verts, color);
        } else {
            if (window.clearPoly) window.clearPoly();
        }
        syncMenuStates();
    });

    document.getElementById('btn-clear-mask')?.addEventListener('click', () => {
        const toggle = document.getElementById('btn-draw-mask-toggle');
        if (toggle) toggle.checked = false;
        if (window.clearMask) window.clearMask();
        syncMenuStates();
    });

    document.getElementById('btn-clear-poly')?.addEventListener('click', () => {
        const toggle = document.getElementById('btn-draw-poly-toggle');
        if (toggle) toggle.checked = false;
        if (window.clearPoly) window.clearPoly();
        syncMenuStates();
    });

    const updatePolyLive = () => {
        const toggle = document.getElementById('btn-draw-poly-toggle');
        if (toggle && toggle.checked && window.updatePolyStyle) {
            const verts = parseInt(document.getElementById('poly-vertices')?.value || 6);
            const color = document.getElementById('poly-color')?.value || '#fa8231';
            window.updatePolyStyle(verts, color);
        }
    };
    document.getElementById('poly-vertices')?.addEventListener('change', () => {
        updatePolyLive();
        if (window._triggerAppUpdate) window._triggerAppUpdate();
    });
    document.getElementById('poly-color')?.addEventListener('input', () => {
        updatePolyLive();
    });
    document.getElementById('poly-lock')?.addEventListener('change', (e) => {
        if (window.togglePolyLock) window.togglePolyLock(e.target.checked);
    });

    document.getElementById('btn-clear-all-overlays')?.addEventListener('click', () => {
        if (window.clearMask) window.clearMask();
        if (window.clearPoly) window.clearPoly();
        if (MapView.clearHeat) MapView.clearHeat();

        const maskToggle = document.getElementById('btn-draw-mask-toggle');
        if (maskToggle) maskToggle.checked = false;
        const polyToggle = document.getElementById('btn-draw-poly-toggle');
        if (polyToggle) polyToggle.checked = false;
        syncMenuStates();
    });

    window._triggerAppUpdate = () => {
        if (_lastData) _processData(_lastData);
    };

    window._syncMaskUI = (overrideBounds = null) => {
        const bounds = overrideBounds || (typeof window.getMaskBounds === 'function' ? window.getMaskBounds() : null);
        if (!bounds) return;

        const isImperial = (document.getElementById('setting-units')?.value === 'imperial');
        const factor = isImperial ? 1609.34 : 1000;

        const latMid = (bounds.minLat + bounds.maxLat) / 2;
        const widthM = L.latLng(latMid, bounds.minLon).distanceTo(L.latLng(latMid, bounds.maxLon));
        const heightM = L.latLng(bounds.minLat, bounds.minLon).distanceTo(L.latLng(bounds.maxLat, bounds.minLon));

        const elW = document.getElementById('mask-width');
        const elH = document.getElementById('mask-height');
        if (elW) elW.value = (widthM / factor).toFixed(2);
        if (elH) elH.value = (heightM / factor).toFixed(2);
    };

    const updateMaskFromInputs = () => {
        const widthVal = document.getElementById('mask-width')?.value;
        const heightVal = document.getElementById('mask-height')?.value;
        if (!widthVal || !heightVal || !window.drawDefaultMask) return;

        const isImperial = (document.getElementById('setting-units')?.value === 'imperial');
        const widthMeters = parseFloat(widthVal) * (isImperial ? 1609.34 : 1000);
        const heightMeters = parseFloat(heightVal) * (isImperial ? 1609.34 : 1000);

        let oldCenterLat = null;
        let oldCenterLng = null;
        if (typeof window.getMaskCenter === 'function') {
            const c = window.getMaskCenter();
            if (c) {
                oldCenterLat = c.lat;
                oldCenterLng = c.lng;
            }
        }

        if (window.clearMask) window.clearMask();
        window.drawDefaultMask(widthMeters, heightMeters, '#9b59b6', oldCenterLat, oldCenterLng);
        const toggle = document.getElementById('btn-draw-mask-toggle');
        if (toggle) toggle.checked = true;
    };

    ['mask-width', 'mask-height'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', updateMaskFromInputs);
    });

    // ── Bearing Log (unchanged) ───────────────────────────────────
    let _logEntries = [];
    let _logCounter = 0;
    let _loggedIds  = new Set();

    document.getElementById('log-clear-btn')?.addEventListener('click', () => {
        _logEntries = [];
        _logCounter = 0;
        _loggedIds.clear();
        const tbody = document.getElementById('log-body');
        tbody.innerHTML = '<tr class="log-placeholder"><td colspan="6">Log cleared.</td></tr>';
        document.getElementById('log-count').textContent = '0 entries';
    });

    document.getElementById('log-export-btn')?.addEventListener('click', () => {
        const blob = new Blob([JSON.stringify(_logEntries, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `kraken_bearing_log_${Date.now()}.json`;
        a.click();
    });

    function appendNewObservations(data) {
        const observations = data?.observation_history ?? [];
        const tbody = document.getElementById('log-body');
        const placeholder = tbody.querySelector('.log-placeholder');
        const freqMHz = data?.frequency_hz ? (data.frequency_hz / 1e6).toFixed(4) : '—';
        let addedAny = false;

        observations.forEach(obs => {
            if (_loggedIds.has(obs.id)) return;
            _loggedIds.add(obs.id);
            addedAny = true;
            _logCounter++;

            const conf = obs.confidence ?? 0;
            const confClass = conf >= 0.8 ? 'conf-high' : conf >= 0.5 ? 'conf-med' : 'conf-low';
            const time = obs.received_at
                ? new Date(obs.received_at).toLocaleTimeString()
                : new Date().toLocaleTimeString();

            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${_logCounter}</td>
                <td>${time}</td>
                <td>${obs.label || obs.id}</td>
                <td>${obs.bearing_deg.toFixed(1)}&deg;</td>
                <td class="${confClass}">${(conf * 100).toFixed(0)}%</td>
                <td>${freqMHz}</td>
            `;
            if (placeholder) placeholder.remove();
            tbody.appendChild(row);
            _logEntries.push({
                n: _logCounter, time, id: obs.id,
                bearing_deg: obs.bearing_deg, confidence: conf,
                lat: obs.lat, lon: obs.lon, freq_hz: data.frequency_hz,
            });
        });

        if (addedAny) {
            document.getElementById('log-count').textContent = `${_logCounter} entries`;
        }
    }

    // ── Sidebar Result Panel (CHANGED: adds LS vs Bayes row) ──────
    function updateResultPanel(data, result, displayHistory) {
        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val ?? '—';
        };

        const current = data?.current_observation;

        if (result) {
            set('res-lat',      result.lat.toFixed(6) + '\u00b0');
            set('res-lon',      result.lon.toFixed(6) + '\u00b0');

            const isEmp = document.getElementById('setting-units')?.value === 'imperial';
            if (isEmp) {
                const ft = result.residual_m * 3.28084;
                if (ft >= 5280) set('res-error', (ft / 5280).toFixed(2) + ' mi');
                else set('res-error', ft.toFixed(1) + ' ft');
            } else {
                if (result.residual_m >= 1000) set('res-error', (result.residual_m / 1000).toFixed(2) + ' km');
                else set('res-error', result.residual_m.toFixed(1) + ' m');
            }

            set('res-stations', `${result.stationsUsed} / ${displayHistory.length}`);

            // [NEW] Show LS vs Bayesian disagreement when in hybrid mode.
            // If lsDisagreement_m is present, the Bayesian prior-box flow ran.
            // A null value means LS-AoA or midpoint was used (no disagreement row).
            if (result.lsDisagreement_m != null) {
                const d = result.lsDisagreement_m;
                const isEmpD = document.getElementById('setting-units')?.value === 'imperial';
                let dLabel;
                if (isEmpD) {
                    const dFt = d * 3.28084;
                    dLabel = dFt >= 5280 ? (dFt / 5280).toFixed(2) + ' mi' : dFt.toFixed(1) + ' ft';
                } else {
                    dLabel = d >= 1000 ? (d / 1000).toFixed(2) + ' km' : d.toFixed(1) + ' m';
                }
                // Colour-code: green < 20 m, amber < 100 m, red ≥ 100 m
                const colour = d < 20 ? '#00e87a' : d < 100 ? '#ffb84d' : '#ff4d6a';
                set('res-ls-disagreement', dLabel);
                const el = document.getElementById('res-ls-disagreement');
                if (el) el.style.color = colour;
            } else {
                set('res-ls-disagreement', '—');
                const el = document.getElementById('res-ls-disagreement');
                if (el) el.style.color = '';
            }

        } else {
            ['res-lat','res-lon','res-error','res-stations','res-ls-disagreement'].forEach(id => set(id, '—'));
        }

        const freqMHz = data?.frequency_hz ? (data.frequency_hz / 1e6).toFixed(4) + ' MHz' : '—';
        set('res-freq', freqMHz);
        set('res-doa',  data?.doa_method ?? '—');
        set('res-timestamp', new Date().toLocaleTimeString());

        const stList = document.getElementById('station-list');
        if (stList && displayHistory.length > 0) {
            const isCurrent = (obs) => current && obs.id === current.id;
            const renderedHtml = [...displayHistory].reverse().map(obs => {
                const cur = isCurrent(obs);
                return `<div class="station-item">
                    <div class="station-dot" style="background:${cur ? '#00e87a' : '#4f8ef7'}"></div>
                    <span class="station-name" style="${cur ? 'color:#00e87a;font-weight:600' : ''}">
                        ${cur ? '\u25b6 ' : ''}${obs.label || obs.id}
                    </span>
                    <span class="station-bearing">${obs.bearing_deg.toFixed(1)}&deg;</span>
                </div>`;
            }).join('');
            stList.innerHTML = renderedHtml;
        } else if (stList) {
            stList.innerHTML = '<p class="placeholder-text">Waiting for observations...</p>';
        }
    }

    // ── Core Data Pipeline (CHANGED: priorConfig injected) ────────
    let _lastData = null;

    const modeBadge = document.getElementById('mode-badge');

    function _processData(data) {
        _lastData = data;

        if (data?.source === 'udp_stream') {
            if (modeBadge) {
                modeBadge.textContent = 'LIVE TELEMETRY';
                modeBadge.className = 'badge badge-live';
                modeBadge.style.background = '#00b894';
                modeBadge.style.color = '#fff';
                modeBadge.style.border = 'none';
            }
        } else if (data?.source === 'waiting') {
            if (modeBadge) {
                modeBadge.textContent = 'WAITING';
                modeBadge.className = 'badge badge-waiting';
                modeBadge.style.background = '';
                modeBadge.style.color = '';
                modeBadge.style.border = '';
            }
        }

        let history = data?.observation_history ?? [];
        const minConf = parseFloat(elMinConf?.value ?? 0.5);

        let filtered = history.filter(obs => (obs.confidence ?? 1) >= minConf);

        if (elFilterAttitude?.checked) {
            filtered = filtered.filter(obs => {
                const roll = Math.abs(obs.roll_deg || 0);
                const pitch = Math.abs(obs.pitch_deg || 0);
                return roll <= 15.0 && pitch <= 15.0;
            });
        }

        if (elFilterTemporal?.checked) {
            filtered = filtered.slice(-30);
        }

        let aabb = null;
        if (typeof window.getMaskBounds === 'function') {
            aabb = window.getMaskBounds();
        }

        let polyBounds = null;
        if (typeof window.getPolyBounds === 'function') {
            polyBounds = window.getPolyBounds();
        }

        const config = {
            filterSpatial: document.getElementById('btn-draw-mask-toggle')?.checked ?? false,
            filterPoly: document.getElementById('btn-draw-poly-toggle')?.checked ?? false,
            filterAngular: elFilterAngular?.checked ?? true,
            aabb: aabb,
            polyBounds: polyBounds,
            // [NEW] Inject the operator's prior center into config so
            // Triangulation.solve() can pass it down to bayesianGrid().
            // If null, Bayesian falls back to legacy 15 km grid.
            priorConfig: _getPriorConfig(),
        };

        const algo = elAlgo?.value || 'ls_aoa';
        let result = filtered.length >= 2 ? Triangulation.solve(filtered, algo, config) : null;

        let validObs = Triangulation.filterStations(filtered, config);

        // Strict boundary pruning: drop result if it lands outside the rectangle mask
        if (result && aabb) {
            if (result.lat < aabb.minLat || result.lat > aabb.maxLat ||
                result.lon < aabb.minLon || result.lon > aabb.maxLon) {
                result = null;
            }
        }

        MapView.update(data, result, validObs);

        if (result) {
            if (algo === 'bayesian' && result.heatGrid) {
                MapView.setHeatGrid(result.heatGrid);
            } else {
                const avgConf   = validObs.reduce((s, o) => s + (o.confidence ?? 1), 0) / validObs.length;
                const intensity = Math.min(1.0, (validObs.length / 6) * avgConf);
                MapView.addHeatPoint(result.lat, result.lon, intensity);
            }
            const el = document.getElementById('hm-point-count');
            if (el) el.textContent = MapView.getHeatPointCount();

            if (typeof window.getSearchAreaSummary === 'function') {
                const sa = window.getSearchAreaSummary();
                if (sa && sa.isActive && sa.center && sa.isInside) {
                    const isInside = sa.isInside(result.lat, result.lon);
                    if (isInside) {
                        _addEstimationHit(result);
                    }
                }
            }
        }

        updateResultPanel(data, result, validObs);
        appendNewObservations(data);
    }

    DataFeed.onData(_processData);

    // ── Eager Map Init (unchanged) ────────────────────────────────
    requestAnimationFrame(() => {
        MapView.init('map');

        _allSettings.forEach(el => {
            if (el && el !== elPollInterval) {
                el.dispatchEvent(new Event('change'));
            }
        });

        console.log('[App] Maps initialised. Starting data feed...');
        DataFeed.start();
    });

})();