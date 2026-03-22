/**
 * map.js — Leaflet GPS Map Module (Single Mobile KrakenSDR)
 * ===========================================================
 * Renders the KrakenSDR route and bearing observations:
 *  - Polyline path of all observation positions visited
 *  - Small dot markers at each historical observation + bearing line
 *  - Pulsing marker at the CURRENT (latest) position
 *  - Bearing line from current position (brighter/thicker)
 *  - Triangulation result marker + uncertainty circle
 */

const MapView = (() => {
    let _map            = null;
    let _pathLayer      = null;   // The driven route polyline
    let _obsLayer       = null;   // Historical observation dots + bearing lines
    let _currentLayer   = null;   // Current position marker + bearing line
    let _resultLayer    = null;   // Triangulated result + uncertainty circle
    let _customLayer    = null;   // User-placed custom markers
    let _heatLayer      = null;   // Triangulated result heatmap
    let _tileLayer      = null;
    let _lineLengthKm   = 2;
    let _showUncertainty = true;
    let _firstLoad       = true;  // Prevent permanent zoom-lock

    const OBS_COLOR     = '#4f8ef7';  // Blue-ish — historical observations
    const PATH_COLOR   = '#3498db';
    const RESULT_COLOR = '#00ff00';
    const BEARING_COLOR = '#3498db'; // Kraken uses blue for bearings
    const HEADING_COLOR = '#e74c3c'; // Kraken uses red for vehicle heading

    let _heatPoints = [];
    let _heatRadius = 30;
    let _heatBlur = 20;
    let _heatOpacity = 0.7;

    let _drawnObsIds = new Set();
    let _resultCrosshair = null;
    let _resultCenterDot = null;
    let _customMarkers = [];
    let _customPolyline = null;

    window.saveCustomMarkerName = function(id, newName) {
        const obj = _customMarkers.find(o => o.id === id);
        if (obj && newName.trim() !== '') {
            obj.name = newName.trim();
        }
    };

    window.toggleCustomMarkerLock = function(id) {
        const obj = _customMarkers.find(o => o.id === id);
        if (!obj) return;
        obj.locked = !obj.locked;
        if (obj.locked) {
            obj.marker.dragging.disable();
        } else {
            obj.marker.dragging.enable();
        }
        MapView.refreshCustomMarkers();
    };

    window.removeCustomMarker = function(id) {
        const obj = _customMarkers.find(o => o.id === id);
        if (!obj) return;
        obj.marker.remove();
        _customMarkers = _customMarkers.filter(o => o.id !== id);
        MapView.refreshCustomMarkers();
    };

    const TILE_CONFIGS = {
        osm: {
            url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a>',
        },
        topo: {
            url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
            attribution: '© OpenTopoMap',
        },
        satellite: {
            url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attribution: '© Esri',
        },
    };

    // Helpers for geographic math
    const TriangulationHelpers = {
        projectPoint(lat, lon, bearing, distance) {
            const rad = Math.PI / 180;
            const R = 6371000;
            const d = distance / R;
            const brng = bearing * rad;
            const lat1 = lat * rad;
            const lon1 = lon * rad;

            let lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng));
            let lon2 = lon1 + Math.atan2(Math.sin(brng) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));

            return { lat: lat2 / rad, lon: lon2 / rad };
        },

        // Creates points for a regular polygon (like an octagon)
        createPolygon(lat, lon, radiusMeters, sides) {
            const points = [];
            for (let i = 0; i <= sides; i++) {
                const angle = (360 / sides) * i;
                const pt = this.projectPoint(lat, lon, angle, radiusMeters);
                points.push([pt.lat, pt.lon]);
            }
            return points;
        }
    };

    function _obsIcon(color, size = 10) {
        return L.divIcon({
            className: '',
            html: `<div style="
                width:${size}px;height:${size}px;border-radius:50%;
                background:${color};
                border:2px solid rgba(255,255,255,0.7);
                box-shadow:0 0 6px ${color};
            "></div>`,
            iconSize: [size, size],
            iconAnchor: [size/2, size/2],
        });
    }

    function _currentIcon() {
        return L.divIcon({
            className: '',
            html: `<div style="
                width:16px;height:16px;border-radius:50%;
                background:${OBS_COLOR};
                border:3px solid rgba(255,255,255,0.9);
                box-shadow:0 0 14px ${OBS_COLOR}, 0 0 4px rgba(0,0,0,0.5);
                animation: none;
            "></div>`,
            iconSize: [16, 16],
            iconAnchor: [8, 8],
        });
    }

    function _resultIcon() {
        return L.divIcon({
            className: '',
            html: `<div style="
                width:18px;height:18px;border-radius:50%;
                background:${RESULT_COLOR};
                border:3px solid rgba(255,255,255,0.9);
                box-shadow:0 0 14px ${RESULT_COLOR}, 0 0 4px rgba(0,0,0,0.6);
            "></div>`,
            iconSize: [18, 18],
            iconAnchor: [9, 9],
        });
    }

    function setTile(key) {
        const cfg = TILE_CONFIGS[key] || TILE_CONFIGS.osm;
        if (_tileLayer) _map.removeLayer(_tileLayer);
        _tileLayer = L.tileLayer(cfg.url, { attribution: cfg.attribution, maxZoom: 19 });
        _tileLayer.addTo(_map);
    }

    function init(elementId) {
        _map = L.map(elementId, {
            center: [34.057, -117.821],
            zoom: 15,
            zoomControl: true,
        });
        setTile('osm');
        _pathLayer    = L.layerGroup().addTo(_map);
        _obsLayer     = L.layerGroup().addTo(_map);
        _currentLayer = L.layerGroup().addTo(_map);
        _resultLayer  = L.layerGroup().addTo(_map);
        _customLayer  = L.layerGroup().addTo(_map);

        _heatLayer = L.heatLayer([], {
            radius: _heatRadius,
            blur: _heatBlur,
            maxZoom: 17,
            max: 1.0,
            minOpacity: _heatOpacity * 0.3,
            gradient: { 0.2: '#00d4ff', 0.5: '#9b59ff', 0.8: '#ff4d6a', 1.0: '#ff0000' },
        }).addTo(_map);

        // Right-click / Long-press to place custom markers
        _map.on('contextmenu', (e) => {
            const markerId = Date.now();
            const marker = L.marker(e.latlng, { draggable: true }).addTo(_customLayer);
            
            const obj = { 
                id: markerId, 
                marker: marker, 
                name: `Custom Marker ${_customMarkers.length + 1}`,
                locked: false 
            };
            _customMarkers.push(obj);

            marker.bindPopup('', { autoClose: false, closeOnClick: false }).openPopup();

            marker.on('drag', _refreshCustomMarkers);
            marker.on('contextmenu', (me) => {
                L.DomEvent.stopPropagation(me); // prevent map from receiving the generic right-click
                _customMarkers = _customMarkers.filter(o => o.id !== markerId);
                marker.remove();
                _refreshCustomMarkers();
            });

            _refreshCustomMarkers();
        });
    }

    function _refreshCustomMarkers() {
        const unit = document.getElementById('setting-units')?.value || 'metric';

        // 1. Update Polyline
        const latlngs = _customMarkers.map(o => o.marker.getLatLng());
        if (_customPolyline) _customLayer.removeLayer(_customPolyline);
        if (latlngs.length > 1) {
            _customPolyline = L.polyline(latlngs, { color: '#f39c12', dashArray: '5 5', weight: 2 }).addTo(_customLayer);
        } else {
            _customPolyline = null;
        }

        // 2. Update Popups
        for (let i = 0; i < _customMarkers.length; i++) {
            const obj = _customMarkers[i];
            const pos = obj.marker.getLatLng();
            let distHtml = '';

            if (i > 0) {
                const prevPos = _customMarkers[i-1].marker.getLatLng();
                const distM = pos.distanceTo(prevPos);
                if (unit === 'imperial') {
                    const distFt = distM * 3.28084;
                    const distMi = distFt / 5280;
                    distHtml = distMi > 0.5 ? `${distMi.toFixed(2)} mi from prev` : `${distFt.toFixed(0)} ft from prev`;
                } else {
                    distHtml = distM > 1000 ? `${(distM/1000).toFixed(2)} km from prev` : `${distM.toFixed(0)} m from prev`;
                }
            }

            obj.marker.setPopupContent(`
                <div style="min-width: 160px; text-align: center; font-family: sans-serif;">
                    <input type="text" value="${obj.name}" 
                           onblur="window.saveCustomMarkerName(${obj.id}, this.value)"
                           onkeydown="if(event.key==='Enter'){this.blur();}" 
                           style="width: 100%; box-sizing: border-box; text-align: center; font-weight: bold; color: #f39c12; background: rgba(0,0,0,0.2); border: 1px solid #444; border-radius: 3px; padding: 2px; margin-bottom: 6px; outline: none;"
                           title="Click to rename marker"
                    >
                    
                    <div style="font-size: 11px; color: #ccc; margin-bottom: 4px;">
                        Lat: ${pos.lat.toFixed(6)}<br>
                        Lon: ${pos.lng.toFixed(6)}
                    </div>
                    
                    ${distHtml ? `<div style="color: #2ecc71; font-weight: bold; margin-bottom: 4px;">${distHtml}</div>` : ''}
                    
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; border-top: 1px solid #444; padding-top: 6px;">
                        <label style="font-size: 11px; color: #aaa; cursor: pointer; display: flex; align-items: center; gap: 4px;" title="Lock marker position">
                            <input type="checkbox" ${obj.locked ? 'checked' : ''} onclick="window.toggleCustomMarkerLock(${obj.id})"> 
                            Lock
                        </label>
                        <i style="color: #e74c3c; font-size: 10px; font-style: normal; font-weight: bold; cursor: pointer;" onclick="window.removeCustomMarker(${obj.id})" title="Remove Marker">DELETE</i>
                    </div>
                </div>
            `);
        }
    }

    /**
     * update(data, result)
     * data: { observation_history[], current_observation, frequency_hz, doa_method }
     * result: { lat, lon, residual_m, stationsUsed } | null
     */
    function update(data, result, validObs = null) {
        if (!_map) return;
        const history = data?.observation_history ?? [];
        const current = data?.current_observation ?? null;

        const validArray = validObs || history;
        const validSet = new Set(validArray.map(o => o.id));

        // Clear only the layers that change every tick
        _currentLayer.clearLayers();

        // If history length decreased (e.g., timeline scrubbed back or reset)
        // OR validArray decreased (e.g., user slid Min Confidence to the right)
        // clear all historical observation dots to force a repaint of the exact valid subset.
        if (history.length === 0 || validArray.length < _drawnObsIds.size) {
            _obsLayer.clearLayers();
            _drawnObsIds.clear();
        }

        if (history.length === 0) return;

        const bounds = [];

        // ── Historical Path & Observation Log ──────────────────────────
        const latlngs = [];
        const freqMHz = data?.frequency_hz ? (data.frequency_hz / 1e6).toFixed(4) : '—';
        const _showLines = true; // Always show lines for now

        history.forEach((obs, index) => {
            latlngs.push([obs.lat, obs.lon]);
            
            // Do not draw map dots or blue bearing lines for observations that were mathematically excluded by the UI Settings filters.
            if (!validSet.has(obs.id)) return;

            // Only draw observations that haven't been drawn yet
            if (_drawnObsIds.has(obs.id)) return;
            _drawnObsIds.add(obs.id);

            // KrakenSDR confidence-based path colors
            const conf = obs.confidence ?? 0;
            let dotColor = '#e74c3c'; // Red
            if (conf >= 0.7) dotColor = '#2ecc71'; // Green
            else if (conf >= 0.4) dotColor = '#f1c40f'; // Yellow

            const cMarker = L.circleMarker([obs.lat, obs.lon], {
                radius: 4, fillColor: dotColor, color: '#000', weight: 1, fillOpacity: 1
            });
            
            // Informational Popup
            cMarker.bindPopup(`
                <b>Log Number: ${index + 1}</b><br>
                RDF Bearing: ${obs.bearing_deg.toFixed(1)}&deg;<br>
                Vehicle Heading: ${(obs.heading_used_deg || 0).toFixed(1)}&deg;<br>
                Confidence: ${(conf * 100).toFixed(0)}%<br>
                Frequency: ${freqMHz} MHz
            `, { autoClose: false, closeOnClick: false });
            _obsLayer.addLayer(cMarker);

            // Short blue bearing vector for history
            if (_showLines) {
                const vec = TriangulationHelpers.projectPoint(obs.lat, obs.lon, obs.bearing_deg, Math.min(600, _lineLengthKm * 100));
                _obsLayer.addLayer(L.polyline([
                    [obs.lat, obs.lon], [vec.lat, vec.lon]
                ], { color: BEARING_COLOR, weight: 1, opacity: 0.6 }));
            }
        });

        // The actual connected path line (we redraw this strictly from the unfiltered `history` array 
        // to ensure the vehicle polyline doesn't look like teleportation between high-confidence waypoints)
        _pathLayer.clearLayers();
        if (latlngs.length > 1) {
            _pathLayer.addLayer(L.polyline(latlngs, { color: '#888', weight: 2, dashArray: '5, 5', opacity: 0.5 }));
        }

        // ── Current Observation point ──────────────────────────────────
        if (current) {
            bounds.push([current.lat, current.lon]);
            
            // Red Vehicle Heading Line
            const headVec = TriangulationHelpers.projectPoint(
                current.lat, current.lon, current.heading_used_deg || 0, _lineLengthKm * 50
            );
            _currentLayer.addLayer(L.polyline([
                [current.lat, current.lon], [headVec.lat, headVec.lon]
            ], { color: HEADING_COLOR, weight: 3 }));

            // The main long bearing line to estimated tx
            if (_showLines) {
                const brngVec = TriangulationHelpers.projectPoint(
                    current.lat, current.lon, current.bearing_deg, _lineLengthKm * 1000
                );
                _currentLayer.addLayer(L.polyline([
                    [current.lat, current.lon], [brngVec.lat, brngVec.lon]
                ], { color: BEARING_COLOR, weight: 2 }));
            }
            
            // Current dot
            _currentLayer.addLayer(L.circleMarker([current.lat, current.lon], {
                color: '#fff', fillColor: '#3498db', fillOpacity: 1, radius: 6, weight: 2
            }));
        }

        // ── Triangulation result ─────────────────────────────────────
        if (result) {
            bounds.push([result.lat, result.lon]);

            // Green Octagon for Estimated Source (KrakenSDR style)
            const octagonPoints = TriangulationHelpers.createPolygon(
                result.lat, result.lon, Math.max(result.residual_m, 100), 8
            );
            
            if (!_resultCrosshair) {
                _resultCrosshair = L.polygon(octagonPoints, {
                    color: RESULT_COLOR,
                    weight: 4,
                    fill: false
                }).addTo(_resultLayer);

                // Small dot in center
                _resultCenterDot = L.circleMarker([result.lat, result.lon], {
                    color: RESULT_COLOR, fillColor: RESULT_COLOR, fillOpacity: 1, radius: 3, weight: 1
                }).addTo(_resultLayer);

                _resultCrosshair.bindPopup('', { autoClose: false, closeOnClick: false });
            } else {
                _resultCrosshair.setLatLngs(octagonPoints);
                _resultCenterDot.setLatLng([result.lat, result.lon]);
            }

            _resultCrosshair.setPopupContent(`
                <b style="color:${RESULT_COLOR}">Estimated Source</b><br>
                Lat: ${result.lat.toFixed(6)}<br>
                Lon: ${result.lon.toFixed(6)}<br>
                Uncertainty Radius: ${result.residual_m.toFixed(1)} m<br>
                From ${result.stationsUsed} obs.
            `);
        } else {
            if (_resultCrosshair) {
                _resultLayer.clearLayers();
                _resultCrosshair = null;
                _resultCenterDot = null;
            }
        }

        // Only snap to the bounds on the very first load to allow user complete zoom/pan freedom.
        if (bounds.length > 1 && _firstLoad) {
            _map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
            _firstLoad = false;
        }
    }

    function setLineLength(km) { _lineLengthKm = km; }
    function setShowUncertainty(val) { _showUncertainty = val; }
    function invalidateSize() { if (_map) _map.invalidateSize(); }

    function addHeatPoint(lat, lon, intensity = 1.0) {
        _heatPoints.push([lat, lon, intensity]);
        if (_heatLayer) _heatLayer.setLatLngs(_heatPoints);
    }
    function clearHeat() {
        _heatPoints = [];
        if (_heatLayer) _heatLayer.setLatLngs([]);
    }
    function setHeatGrid(pointsArray) {
        _heatPoints = pointsArray;
        if (_heatLayer) _heatLayer.setLatLngs(_heatPoints);
    }
    function setHeatRadius(r) {
        _heatRadius = r;
        if (_heatLayer) _heatLayer.setOptions({ radius: r });
    }
    function setHeatBlur(b) {
        _heatBlur = b;
        if (_heatLayer) _heatLayer.setOptions({ blur: b });
    }
    function setHeatOpacity(o) {
        _heatOpacity = o;
        if (_heatLayer) _heatLayer.setOptions({ minOpacity: o * 0.3 });
    }
    function getHeatPointCount() { return _heatPoints.length; }

    return { 
        init, update, setTile, setLineLength, setShowUncertainty, invalidateSize,
        addHeatPoint, clearHeat, setHeatGrid, setHeatRadius, setHeatBlur, setHeatOpacity, getHeatPointCount
    };
})();
