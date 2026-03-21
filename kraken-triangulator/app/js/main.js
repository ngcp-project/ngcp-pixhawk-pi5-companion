/**
 * main.js — App Orchestrator (Single Mobile KrakenSDR Model)
 * ===========================================================
 * Wires tab routing, settings, playback controls, bearing log, and the
 * full data pipeline:
 *   DataFeed -> Triangulation.solve(observation_history) -> MapView + HeatmapView
 *
 * Data schema: { observation_history[], current_observation, frequency_hz,
 *                doa_method, playback: { index, total, speed, paused } }
 *
 * Timestamp note:
 *   "LAST RECEIVED" shows the laptop system clock at the moment the poll
 *   response arrived — NOT the timestamp in the mock data (which is
 *   fictional). The server assigns real system-clock timestamps to each
 *   observation the moment it is first revealed.
 */

(function () {

    // ── Tab Routing ────────────────────────────────────────────────
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanels  = document.querySelectorAll('.tab-panel');

    function switchTab(targetId) {
        tabButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.tab === targetId));
        tabPanels.forEach(panel => {
            panel.classList.toggle('active', panel.id === `panel-${targetId}`);
        });
        // Fix: call invalidateSize so Leaflet redraws after hidden→visible
        if (targetId === 'heatmap') requestAnimationFrame(() => HeatmapView.invalidateSize());
        if (targetId === 'map')     requestAnimationFrame(() => MapView.invalidateSize());
    }

    tabButtons.forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
    switchTab('map');

    // ── Settings Wiring ────────────────────────────────────────────
    const elPollInterval = document.getElementById('setting-poll-interval');
    const elTile         = document.getElementById('setting-tile');
    const elUncertainty  = document.getElementById('setting-uncertainty');
    const elLineLength   = document.getElementById('setting-line-length');
    const elAlgo         = document.getElementById('setting-algo');
    const elMinConf      = document.getElementById('setting-min-conf');

    elPollInterval?.addEventListener('change', () =>
        DataFeed.setPollInterval(parseInt(elPollInterval.value, 10) || 2000));
    elTile?.addEventListener('change', () => MapView.setTile(elTile.value));
    elUncertainty?.addEventListener('change', () => MapView.setShowUncertainty(elUncertainty.checked));
    elLineLength?.addEventListener('change', () => {
        MapView.setLineLength(parseFloat(elLineLength.value) || 2);
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

    document.getElementById('btn-collapse-obs')?.addEventListener('click', () => {
        const card = document.getElementById('station-list-card');
        if (card) card.classList.toggle('obs-collapsed');
    });

    // ── Heatmap Controls ───────────────────────────────────────────
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
    wireSlider('hm-radius',  'hm-radius-val',  null, HeatmapView.setRadius);
    wireSlider('hm-blur',    'hm-blur-val',    null, HeatmapView.setBlur);
    wireSlider('hm-opacity', 'hm-opacity-val', 0.1,  HeatmapView.setOpacity);
    document.getElementById('hm-clear-btn')?.addEventListener('click', HeatmapView.clear);

    // ── Playback Controls ──────────────────────────────────────────
    const pbBar       = document.getElementById('playback-bar');
    const pbPlayPause = document.getElementById('pb-playpause');
    const pbRewind    = document.getElementById('pb-rewind');
    const pbForward   = document.getElementById('pb-forward');
    const pbReset     = document.getElementById('pb-reset');
    const pbScrubber  = document.getElementById('pb-scrubber');
    const pbPosLabel  = document.getElementById('pb-pos-label');
    const pbSpeed     = document.getElementById('pb-speed');

    let _pbPaused = false;

    async function _pbCommand(action, value) {
        const body = { action };
        if (value !== undefined) body.value = value;
        try {
            const resp = await fetch('/api/playback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            // Immediately process the new state returned by the server
            if (data?.observation_history) _processData(data);
            _updatePlaybackUI(data?.playback);
        } catch (e) {
            console.warn('[Playback] Command failed:', e);
        }
    }

    function _updatePlaybackUI(pb) {
        if (!pb) return;
        _pbPaused = pb.paused;
        // Play/Pause icon: paused = show play triangle, playing = show pause bars
        pbPlayPause.innerHTML = pb.paused ? '&#9654;' : '&#9646;&#9646;';
        pbPlayPause.classList.toggle('paused', !pb.paused);
        pbPlayPause.title = pb.paused ? 'Play' : 'Pause';
        // Scrubber
        pbScrubber.max   = pb.total || 6;
        pbScrubber.value = pb.index || 1;
        if (pbPosLabel) pbPosLabel.textContent = `${pb.index} / ${pb.total}`;
        // Speed
        if (pbSpeed && pb.speed !== undefined) {
            pbSpeed.value = pb.speed;
        }
    }

    pbPlayPause?.addEventListener('click', () =>
        _pbCommand(_pbPaused ? 'play' : 'pause'));
    pbRewind?.addEventListener('click',  () => _pbCommand('rewind'));
    pbForward?.addEventListener('click', () => _pbCommand('forward'));
    pbReset?.addEventListener('click',   () => _pbCommand('reset'));

    pbScrubber?.addEventListener('change', () =>
        _pbCommand('seek', parseInt(pbScrubber.value, 10)));

    pbSpeed?.addEventListener('change', () =>
        _pbCommand('set_speed', parseFloat(pbSpeed.value)));

    // ── Bearing Log ───────────────────────────────────────────────
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
            // Use server-assigned system-clock time (received_at)
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

    // ── Sidebar Result Panel ───────────────────────────────────────
    function updateResultPanel(data, result, displayHistory) {
        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val ?? '—';
        };

        const current = data?.current_observation;

        if (result) {
            set('res-lat',      result.lat.toFixed(6) + '\u00b0');
            set('res-lon',      result.lon.toFixed(6) + '\u00b0');
            set('res-error',    result.residual_m.toFixed(1) + ' m');
            set('res-stations', `${result.stationsUsed} / ${displayHistory.length}`);
        } else {
            ['res-lat','res-lon','res-error','res-stations'].forEach(id => set(id, '—'));
        }

        const freqMHz = data?.frequency_hz ? (data.frequency_hz / 1e6).toFixed(4) + ' MHz' : '—';
        set('res-freq', freqMHz);
        set('res-doa',  data?.doa_method ?? '—');

        // LAST RECEIVED = laptop system clock when this poll was processed
        set('res-timestamp', new Date().toLocaleTimeString());

        // Observation list
        const stList = document.getElementById('station-list');
        if (stList && displayHistory.length > 0) {
            const isCurrent = (obs) => current && obs.id === current.id;
            // Use reverse to show newest observations at the top of the list for better UX
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

    // ── Core Data Pipeline ─────────────────────────────────────────
    let _lastData = null;

    function _processData(data) {
        _lastData = data;

        // Show/hide playback bar
        if (data?.source === 'mock' && pbBar) pbBar.style.display = 'flex';

        // Sync playback UI from embedded state
        if (data?.playback) _updatePlaybackUI(data.playback);

        let history = data?.observation_history ?? [];
        const minConf = parseFloat(elMinConf?.value ?? 0.5);
        
        let validObs = history.filter(obs => (obs.confidence ?? 1) >= minConf);
        
        if (elFilterAttitude?.checked) {
            validObs = validObs.filter(obs => {
                const roll = Math.abs(obs.roll_deg || 0);
                const pitch = Math.abs(obs.pitch_deg || 0);
                return roll <= 15.0 && pitch <= 15.0;
            });
        }
        
        if (elFilterTemporal?.checked) {
            validObs = validObs.slice(-30);
        }
        
        const config = {
            filterSpatial: elFilterSpatial?.checked ?? true,
            filterAngular: elFilterAngular?.checked ?? true
        };

        const algo   = elAlgo?.value || 'ls_aoa';
        const result = validObs.length >= 2 ? Triangulation.solve(validObs, algo, config) : null;

        MapView.update(data, result);

        if (result) {
            const avgConf   = validObs.reduce((s, o) => s + (o.confidence ?? 1), 0) / validObs.length;
            const intensity = Math.min(1.0, (validObs.length / 6) * avgConf);
            HeatmapView.addPoint(result.lat, result.lon, intensity);
            const el = document.getElementById('hm-point-count');
            if (el) el.textContent = HeatmapView.getPointCount();
        }

        updateResultPanel(data, result, validObs);
        appendNewObservations(data);
    }

    DataFeed.onData(_processData);

    // ── Eager Map Init ─────────────────────────────────────────────
    requestAnimationFrame(() => {
        MapView.init('map');
        HeatmapView.init('heatmap-map');
        console.log('[App] Maps initialised. Starting data feed...');
        DataFeed.start();
    });

})();
