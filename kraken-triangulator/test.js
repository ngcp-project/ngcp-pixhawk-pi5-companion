const fs = require('fs');

// Load the raw data
const rawData = JSON.parse(fs.readFileSync('./data/bearings_20260313_154333.json', 'utf8'));
const allObs = rawData.waypoint_sequence;

// Simulate the frontend filtering
let validObs = allObs.filter(obs => (obs.confidence || 1) >= 0.5);
validObs = validObs.slice(-30); // temporal filter

// Paste strictly the definitions from triangulation.js
const DEG2RAD = Math.PI / 180;
const RAD2DEG = 180 / Math.PI;
const EARTH_R  = 6371000;

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

function lsAoA(stations) {
    if (!stations || stations.length < 2) return null;
    const refLat = stations.reduce((s, st) => s + st.lat, 0) / stations.length;
    const refLon = stations.reduce((s, st) => s + st.lon, 0) / stations.length;
    let AtWA = [[0,0],[0,0]], AtWb = [0, 0];
    for (const st of stations) {
        const w = st.confidence ?? 1.0;
        const { E, N } = latLonToENU(st.lat, st.lon, refLat, refLon);
        const theta = (90 - st.bearing_deg) * DEG2RAD;
        const sinT = Math.sin(theta);
        const cosT = Math.cos(theta);
        const a = sinT, b = -cosT, c = sinT * E - cosT * N;
        AtWA[0][0] += w * a * a;
        AtWA[0][1] += w * a * b;
        AtWA[1][0] += w * b * a;
        AtWA[1][1] += w * b * b;
        AtWb[0]    += w * a * c;
        AtWb[1]    += w * b * c;
    }
    const det = AtWA[0][0] * AtWA[1][1] - AtWA[0][1] * AtWA[1][0];
    if (Math.abs(det) < 1e-10) return null;
    const x = (AtWb[0] * AtWA[1][1] - AtWb[1] * AtWA[0][1]) / det;
    const y = (AtWA[0][0] * AtWb[1] - AtWA[1][0] * AtWb[0]) / det;
    let totalResidual = 0;
    for (const st of stations) {
        const { E, N } = latLonToENU(st.lat, st.lon, refLat, refLon);
        const theta = (90 - st.bearing_deg) * DEG2RAD;
        const sinT = Math.sin(theta);
        const cosT = Math.cos(theta);
        totalResidual += Math.abs(sinT * (x - E) - cosT * (y - N));
    }
    return {
        lat: enuToLatLon(x, y, refLat, refLon).lat,
        lon: enuToLatLon(x, y, refLat, refLon).lon,
        residual_m: totalResidual / stations.length,
        stationsUsed: stations.length,
    };
}

function bayesianGrid(stations) {
    if (!stations || stations.length < 2) return null;

    const lsResult = lsAoA(stations);
    let refLat = lsResult ? lsResult.lat : stations.reduce((s, st) => s + st.lat, 0) / stations.length;
    let refLon = lsResult ? lsResult.lon : stations.reduce((s, st) => s + st.lon, 0) / stations.length;

    const GRID_SIZE_M = 15000;
    const STEP_M = 100;
    const HALF = GRID_SIZE_M / 2;
    const SIGMA = 5.0;

    let maxScore = -Infinity;
    let bestE = 0, bestN = 0;
    let heatPoints = [];

    const enuStations = stations.map(st => ({
        ...st,
        enu: latLonToENU(st.lat, st.lon, refLat, refLon)
    }));

    for (let y = -HALF; y <= HALF; y += STEP_M) {
        for (let x = -HALF; x <= HALF; x += STEP_M) {
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

    const visualGrid = heatPoints
        .map(pt => {
            pt.prob = Math.exp(pt.score - maxScore);
            return pt;
        })
        .filter(pt => pt.prob > 0.1)
        .map(pt => {
            const ll = enuToLatLon(pt.x, pt.y, refLat, refLon);
            return [ll.lat, ll.lon, pt.prob];
        });

    const resultLatLon = enuToLatLon(bestE, bestN, refLat, refLon);
    return {
        lat: resultLatLon.lat,
        lon: resultLatLon.lon,
        heatGrid: visualGrid
    };
}

try {
    console.log("Running lsAoA...");
    const base = lsAoA(validObs);
    console.log("Success! lsAoA Result:", base ? "Valid" : "Null");
    
    console.log("Running bayesianGrid...");
    const res = bayesianGrid(validObs);
    console.log("Success! Grid size:", res.heatGrid.length);
} catch(e) {
    console.error("FATAL ERROR IN MATH:", e);
}
