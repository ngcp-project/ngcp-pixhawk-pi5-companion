document.addEventListener('DOMContentLoaded', () => {
    const statusIndicator = document.getElementById('status-indicator');
    const updateRateHz = 5; 
    const fetchIntervalMs = 1000 / updateRateHz;

    let lastDataTime = 0;

    async function fetchTelemetry() {
        try {
            const response = await fetch('/telemetry.json');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            
            const data = await response.json();
            
            // If empty object, translator hasn't written data yet
            if (Object.keys(data).length === 0) {
                setStatus('offline');
                return;
            }

            updateUI(data);

            // Check if data is stale (older than 2 seconds)
            const currentTime = new Date().getTime();
            if (currentTime - data.last_updated > 2000) {
                setStatus('stale');
            } else {
                setStatus('online');
            }

        } catch (error) {
            console.error("Failed to fetch telemetry:", error);
            setStatus('offline');
        }
    }

    function setStatus(state) {
        statusIndicator.className = 'status ' + state;
        if (state === 'online') statusIndicator.textContent = 'ONLINE';
        if (state === 'stale') statusIndicator.textContent = 'STALE DATA';
        if (state === 'offline') statusIndicator.textContent = 'OFFLINE';
    }

    function updateUI(data) {
        document.getElementById('val-pitch').textContent = data.pitch ? data.pitch.toFixed(1) + '°' : '0.0°';
        document.getElementById('val-roll').textContent = data.roll ? data.roll.toFixed(1) + '°' : '0.0°';
        document.getElementById('val-yaw').textContent = data.yaw ? data.yaw.toFixed(1) + '°' : '0.0°';

        document.getElementById('val-lat').textContent = data.lat ? data.lat.toFixed(6) : '0.000000';
        document.getElementById('val-lon').textContent = data.lon ? data.lon.toFixed(6) : '0.000000';
        document.getElementById('val-alt').textContent = data.alt ? data.alt.toFixed(1) : '0.0';
        document.getElementById('val-speed').textContent = data.speed ? data.speed.toFixed(1) : '0.0';

        document.getElementById('val-battery').textContent = data.battery ? data.battery.toFixed(2) : '0.00';
        
        if (data.last_updated) {
            const date = new Date(data.last_updated);
            document.getElementById('val-updated').textContent = date.toLocaleTimeString() + '.' + date.getMilliseconds().toString().padStart(3, '0');
        }

        if (data.hex_payload) {
            document.getElementById('val-hex').textContent = data.hex_payload;
        }

        if (data.latest_command) {
            const timestamp = new Date(data.latest_command.timestamp * 1000).toLocaleTimeString();
            const cmdText = `[${timestamp}] ${data.latest_command.command}: ${data.latest_command.action}`;
            const cmdEl = document.getElementById('val-cmd');
            
            // Only update and flash if it's a new command
            if (cmdEl.textContent !== cmdText) {
                cmdEl.textContent = cmdText;
                
                // Trigger CSS flash animation
                const panel = document.getElementById('panel-commands');
                panel.classList.remove('flash-red');
                void panel.offsetWidth; // force reflow
                panel.classList.add('flash-red');
            }
        }
    }

    // ── Port Monitor ─────────────────────────────────────────────────────────
    async function fetchPorts() {
        try {
            const response = await fetch('/ports');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            renderPorts(data.clients || {});
        } catch (err) {
            const list = document.getElementById('port-list');
            list.innerHTML = `<div class="port-row port-placeholder">
                <span class="port-status-dot"></span>
                <span class="port-name">Hub offline — no active ports</span>
            </div>`;
        }
    }

    function renderPorts(clients) {
        const list = document.getElementById('port-list');

        if (Object.keys(clients).length === 0) {
            list.innerHTML = `<div class="port-row port-placeholder">
                <span class="port-status-dot"></span>
                <span class="port-name">No clients registered with hub</span>
            </div>`;
            return;
        }

        list.innerHTML = Object.entries(clients)
            .sort(([a], [b]) => parseInt(a) - parseInt(b))
            .map(([port, info]) => {
                let stateClass, stateLabel;
                if (info.alive === null || info.alive === undefined) {
                    stateClass = 'pending'; stateLabel = 'Pending';
                } else if (info.alive) {
                    stateClass = 'alive';   stateLabel = 'Active';
                } else {
                    stateClass = 'dead';    stateLabel = 'Silent';
                }

                const frames = (info.frames_sent !== undefined)
                    ? `${info.frames_sent.toLocaleString()} frames`
                    : '';

                return `<div class="port-row ${stateClass}">
                    <span class="port-status-dot"></span>
                    <span class="port-badge">${port}</span>
                    <span class="port-name">${info.name || 'unknown'}</span>
                    <span class="port-frames">${frames}</span>
                    <span class="port-state-label">${stateLabel}</span>
                </div>`;
            }).join('');
    }

    // Start polling loops
    setInterval(fetchTelemetry, fetchIntervalMs);
    setInterval(fetchPorts, 2000);
    fetchPorts(); // immediate first call
});
