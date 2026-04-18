/**
 * data_feed.js — Bearing Data Poller
 * ====================================
 * Polls GET /api/bearings at a configurable interval.
 * Notifies registered listeners with fresh data.
 *
 * Usage:
 *   DataFeed.onData(callback);
 *   DataFeed.start();
 *   DataFeed.stop();
 */

const DataFeed = (() => {
    const HEALTH_ENDPOINT  = '/api/health';
    const BEARING_ENDPOINT = '/api/bearings';

    let _interval  = null;
    let _pollMs    = 2000;
    let _listeners = [];
    let _errorCount = 0;
    let _currentMode = 'mock';

    function _notifyListeners(data) {
        _listeners.forEach(fn => {
            try { fn(data); }
            catch (e) { console.error('[DataFeed] Listener error:', e); }
        });
    }

    async function _fetch() {
        try {
            const resp = await fetch(BEARING_ENDPOINT, { cache: 'no-store' });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            _errorCount = 0;
            const mode = data.source === 'udp_stream' ? 'live'
                       : data.source === 'replay' ? 'replay'
                       : 'mock';
            _currentMode = mode;
            _setHealthStatus(true, mode);
            _notifyListeners(data);
        } catch (err) {
            _errorCount++;
            _setHealthStatus(false, _currentMode || 'mock');
            if (_errorCount <= 3) {
                console.warn(`[DataFeed] Fetch error (${_errorCount}):`, err.message);
            }
        }
    }

    function _setHealthStatus(online, mode) {
        const dot  = document.getElementById('health-dot');
        const badge = document.getElementById('mode-badge');
        if (!dot || !badge) return;
        dot.className  = 'health-dot ' + (online ? 'online' : 'offline');
        if (mode === 'live') {
            badge.className = 'badge badge-live';
            badge.textContent = 'LIVE DATA';
        } else if (mode === 'replay') {
            badge.className = 'badge badge-mock';
            badge.textContent = 'REPLAY';
        } else {
            badge.className = 'badge badge-mock';
            badge.textContent = 'MOCK DATA';
        }
    }

    return {
        onData(callback) {
            _listeners.push(callback);
        },

        setPollInterval(ms) {
            _pollMs = Math.max(500, ms);
            if (_interval) {
                this.stop();
                this.start();
            }
        },

        start() {
            if (_interval) return;
            _fetch(); // immediate first fetch
            _interval = setInterval(_fetch, _pollMs);
            console.log(`[DataFeed] Started — polling every ${_pollMs}ms`);
        },

        stop() {
            if (_interval) {
                clearInterval(_interval);
                _interval = null;
                console.log('[DataFeed] Stopped.');
            }
        },
    };
})();
