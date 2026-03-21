/**
 * heatmap.js — Bearing Accumulation Heatmap
 * ==========================================
 * Uses Leaflet.heat to accumulate historical triangulation result points
 * and display a probability density map of where the signal source
 * has been estimated to be over time.
 *
 * Fix: exposes invalidateSize() so main.js can call it when the tab
 * becomes visible — resolving Leaflet's black-screen bug on hidden containers.
 */

const HeatmapView = (() => {
    let _map       = null;
    let _heatLayer = null;
    let _points    = []; // [[lat, lon, intensity], ...]

    let _radius  = 30;
    let _blur    = 20;
    let _opacity = 0.7;

    function init(elementId) {
        _map = L.map(elementId, {
            center: [34.057, -117.821],
            zoom: 15,
        });
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap',
            maxZoom: 19,
        }).addTo(_map);

        _heatLayer = L.heatLayer([], {
            radius: _radius,
            blur: _blur,
            maxZoom: 17,
            max: 1.0,
            minOpacity: 0.25,
            gradient: { 0.2: '#00d4ff', 0.5: '#9b59ff', 0.8: '#ff4d6a', 1.0: '#ff0000' },
        }).addTo(_map);
    }

    /**
     * Must be called when the heatmap tab becomes visible.
     * Leaflet can't measure container size when display:none, so tiles
     * don't load until we explicitly tell it the size changed.
     */
    function invalidateSize() {
        if (_map) {
            _map.invalidateSize({ animate: false });
        }
    }

    function addPoint(lat, lon, intensity = 1.0) {
        _points.push([lat, lon, intensity]);
        if (_heatLayer) {
            _heatLayer.setLatLngs(_points);
        }
    }

    function clear() {
        _points = [];
        if (_heatLayer) _heatLayer.setLatLngs([]);
        const el = document.getElementById('hm-point-count');
        if (el) el.textContent = '0';
    }

    function setRadius(r) {
        _radius = r;
        if (_heatLayer) _heatLayer.setOptions({ radius: r });
    }
    function setBlur(b) {
        _blur = b;
        if (_heatLayer) _heatLayer.setOptions({ blur: b });
    }
    function setOpacity(o) {
        _opacity = o;
        if (_heatLayer) _heatLayer.setOptions({ minOpacity: o * 0.3 });
    }

    function getPointCount() { return _points.length; }

    function syncMapTo(lat, lon) {
        if (_map) _map.panTo([lat, lon], { animate: true });
    }

    return { init, invalidateSize, addPoint, clear, setRadius, setBlur, setOpacity, getPointCount, syncMapTo };
})();
