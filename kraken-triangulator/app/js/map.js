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

    let _tileLayer      = null;
    let _lineLengthKm   = 2;
    let _showUncertainty = true;

    const OBS_COLOR     = '#4f8ef7';  // Blue-ish — historical observations
    const CURRENT_COLOR = '#00e87a';  // Green — current position
    const RESULT_COLOR  = '#ff4d6a';  // Red — triangulated result

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

    function _destFromBearing(lat, lon, bearingDeg, distKm) {
        const R = 6371;
        const d = distKm / R;
        const brng = bearingDeg * Math.PI / 180;
        const lat1 = lat * Math.PI / 180;
        const lon1 = lon * Math.PI / 180;
        const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng));
        const lon2 = lon1 + Math.atan2(Math.sin(brng) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));
        return [lat2 * 180 / Math.PI, lon2 * 180 / Math.PI];
    }

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
                background:${CURRENT_COLOR};
                border:3px solid rgba(255,255,255,0.9);
                box-shadow:0 0 14px ${CURRENT_COLOR}, 0 0 4px rgba(0,0,0,0.5);
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
    }

    /**
     * update(data, result)
     * data: { observation_history[], current_observation, frequency_hz, doa_method }
     * result: { lat, lon, residual_m, stationsUsed } | null
     */
    function update(data, result) {
        if (!_map) return;
        const history = data?.observation_history ?? [];
        const current = data?.current_observation ?? null;

        _pathLayer.clearLayers();
        _obsLayer.clearLayers();
        _currentLayer.clearLayers();
        _resultLayer.clearLayers();

        if (history.length === 0) return;

        const bounds = [];

        // ── Route polyline ──────────────────────────────────────────
        if (history.length >= 2) {
            const pathCoords = history.map(o => [o.lat, o.lon]);
            L.polyline(pathCoords, {
                color: OBS_COLOR,
                weight: 2,
                opacity: 0.45,
                dashArray: '6 4',
            }).addTo(_pathLayer);
        }

        // ── Historical observation dots + bearing lines ──────────────
        history.forEach((obs, i) => {
            const isCurrent = current && obs.id === current.id;
            if (isCurrent) return; // drawn separately below

            bounds.push([obs.lat, obs.lon]);

            // Small dot
            const dot = L.marker([obs.lat, obs.lon], { icon: _obsIcon(OBS_COLOR, 9) });
            dot.bindPopup(`
                <b style="color:${OBS_COLOR}">Observation ${i + 1}</b><br>
                ${obs.label || obs.id}<br>
                Bearing: <b>${obs.bearing_deg.toFixed(1)}°</b><br>
                Confidence: ${((obs.confidence ?? 0) * 100).toFixed(0)}%<br>
                ${obs.timestamp_utc ? `Time: ${new Date(obs.timestamp_utc).toLocaleTimeString()}` : ''}
            `);
            _obsLayer.addLayer(dot);

            // Faint bearing line
            const ep = _destFromBearing(obs.lat, obs.lon, obs.bearing_deg, _lineLengthKm);
            L.polyline([[obs.lat, obs.lon], ep], {
                color: OBS_COLOR,
                weight: 1.5,
                opacity: 0.35,
                dashArray: '5 5',
            }).addTo(_obsLayer);
        });

        // ── Current position marker + bearing line ───────────────────
        if (current) {
            bounds.push([current.lat, current.lon]);

            const cur = L.marker([current.lat, current.lon], { icon: _currentIcon() });
            cur.bindPopup(`
                <b style="color:${CURRENT_COLOR}">Current Position</b><br>
                ${current.label || current.id}<br>
                Bearing: <b>${current.bearing_deg.toFixed(1)}°</b><br>
                Confidence: ${((current.confidence ?? 0) * 100).toFixed(0)}%
            `);
            _currentLayer.addLayer(cur);

            // Bright solid bearing line from current position
            const ep = _destFromBearing(current.lat, current.lon, current.bearing_deg, _lineLengthKm);
            L.polyline([[current.lat, current.lon], ep], {
                color: CURRENT_COLOR,
                weight: 2.5,
                opacity: 0.9,
            }).addTo(_currentLayer);
        }

        // ── Triangulation result ─────────────────────────────────────
        if (result) {
            bounds.push([result.lat, result.lon]);

            const resMarker = L.marker([result.lat, result.lon], { icon: _resultIcon() });
            resMarker.bindPopup(`
                <b style="color:${RESULT_COLOR}">Estimated Source</b><br>
                Lat: ${result.lat.toFixed(6)}<br>
                Lon: ${result.lon.toFixed(6)}<br>
                Residual: ${result.residual_m.toFixed(1)} m<br>
                From ${result.stationsUsed} obs.
            `);
            _resultLayer.addLayer(resMarker);

            if (_showUncertainty && result.residual_m > 0) {
                _resultLayer.addLayer(L.circle([result.lat, result.lon], {
                    radius: Math.min(result.residual_m * 3, 600),
                    color: RESULT_COLOR,
                    fillColor: RESULT_COLOR,
                    fillOpacity: 0.07,
                    weight: 1,
                    dashArray: '4 3',
                }));
            }
        }

        if (bounds.length > 1) {
            _map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
        }
    }

    function setLineLength(km) { _lineLengthKm = km; }
    function setShowUncertainty(val) { _showUncertainty = val; }
    function invalidateSize() { if (_map) _map.invalidateSize(); }

    return { init, update, setTile, setLineLength, setShowUncertainty, invalidateSize };
})();
