(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const num = (v) => typeof v === 'number' && Number.isFinite(v);
  const fmt = (v, digits, unit) => (num(v) ? v.toFixed(digits) + (unit || '') : '–');
  const set = (id, text) => { const el = $(id); if (el && el.textContent !== text) el.textContent = text; };

  const STALE_S = { gps: 3, rf: 3, bat: 5, att: 3, trk: 3 };

  let cfg = {};
  let state = null;
  let map, droneMarker, homeMarker, trail, homeLine;
  let following = true;
  let placingHome = false;
  let firstFix = true;
  let trailGen = -1;
  let ws = null;
  const history = [];
  let historyPos = 0;

  // ------------------------------------------------------------------------------------ map

  function droneIcon() {
    return L.divIcon({
      className: 'drone-icon',
      html: '<svg viewBox="0 0 28 28" width="28" height="28"><path d="M14 2 L24 25 L14 19 L4 25 Z" fill="#3fb6ff" stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>',
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  function homeIcon() {
    return L.divIcon({ className: 'home-icon', html: '<div></div>', iconSize: [18, 18], iconAnchor: [9, 9] });
  }

  function initMap() {
    map = L.map('map', { zoomControl: true }).setView([48.8566, 2.3522], 13);

    const bases = {};
    const lt = cfg.local_tiles;
    if (lt) {
      bases['Local tiles'] = L.tileLayer('/tiles/{z}/{x}/{y}', {
        minZoom: lt.minzoom,
        maxZoom: 20,
        maxNativeZoom: lt.maxzoom,
        attribution: 'offline tiles',
      });
    }
    bases['OpenStreetMap'] = L.tileLayer(cfg.tile_url, { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' });
    bases['No map'] = L.layerGroup();
    (lt ? bases['Local tiles'] : bases['OpenStreetMap']).addTo(map);
    L.control.layers(bases, null, { position: 'topright' }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);

    if (lt && lt.center && lt.center.length >= 2) map.setView([lt.center[1], lt.center[0]], Math.min(lt.maxzoom, 14));

    trail = L.polyline([], { color: '#3fb6ff', weight: 3, opacity: 0.85 }).addTo(map);
    homeLine = L.polyline([], { color: '#f5b73d', weight: 2, dashArray: '6 6' }).addTo(map);
    droneMarker = L.marker([0, 0], { icon: droneIcon(), zIndexOffset: 1000, interactive: false });
    homeMarker = L.marker([0, 0], { icon: homeIcon(), interactive: false });

    map.on('dragstart', () => setFollow(false));
    map.on('click', onMapClick);
  }

  function setFollow(on) {
    following = on;
    $('btn-follow').classList.toggle('on', on);
  }

  function onMapClick(e) {
    if (!placingHome) return;
    setPlacingHome(false);
    sendCmd(`HOME ${e.latlng.lat.toFixed(7)} ${e.latlng.lng.toFixed(7)} ${homeAltForManualHome()}`);
  }

  function setPlacingHome(on) {
    placingHome = on;
    $('maphint').classList.toggle('hidden', !on);
    $('btn-home-map').classList.toggle('on', on);
    $('map').style.cursor = on ? 'crosshair' : '';
  }

  // Altitude (MSL) to use when the home position is typed/clicked rather than taken from the drone:
  // the field, else the current home altitude, else the drone's altitude (assumes it is still on the ground).
  function homeAltForManualHome() {
    const typed = parseFloat($('in-halt').value);
    if (num(typed)) return typed;
    if (state && state.trk && state.trk.home && num(state.trk.halt)) return state.trk.halt;
    if (state && state.gps && num(state.gps.alt)) return state.gps.alt;
    return 0;
  }

  // ------------------------------------------------------------------------------- commands

  async function sendCmd(line) {
    try {
      const r = await fetch('/api/cmd', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ line }),
      });
      if (!r.ok) {
        let detail = r.statusText;
        try { detail = (await r.json()).detail || detail; } catch (_) { /* keep statusText */ }
        appendConsole([{ t: Date.now() / 1000, kind: 'err', text: `${line.split(' ')[0]}: ${detail}` }]);
      }
    } catch (err) {
      appendConsole([{ t: Date.now() / 1000, kind: 'err', text: String(err) }]);
    }
  }

  function wireControls() {
    $('btn-follow').onclick = () => {
      setFollow(!following);
      if (following && state && state.gps) map.panTo([state.gps.lat, state.gps.lon], { animate: false });
    };
    $('btn-centerhome').onclick = () => {
      if (state && state.trk && state.trk.home) { setFollow(false); map.setView([state.trk.hlat, state.trk.hlon], Math.max(map.getZoom(), 15)); }
    };
    $('btn-fit').onclick = () => {
      const pts = trail.getLatLngs();
      if (pts.length > 1) { setFollow(false); map.fitBounds(trail.getBounds().pad(0.2)); }
    };
    $('btn-clear').onclick = () => fetch('/api/track/clear', { method: 'POST' });

    $('btn-home-drone').onclick = () => sendCmd('HOME DRONE');
    $('btn-home-clear').onclick = () => sendCmd('HOME CLEAR');
    $('btn-home-map').onclick = () => setPlacingHome(!placingHome);
    $('btn-home-geo').onclick = () => {
      if (!window.isSecureContext || !navigator.geolocation) {
        appendConsole([{ t: Date.now() / 1000, kind: 'err', text: 'browser geolocation needs https or http://localhost' }]);
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const c = pos.coords;
          const typed = parseFloat($('in-halt').value);
          const alt = num(typed) ? typed : num(c.altitude) ? c.altitude : homeAltForManualHome();
          sendCmd(`HOME ${c.latitude.toFixed(7)} ${c.longitude.toFixed(7)} ${Math.round(alt)}`);
        },
        (err) => appendConsole([{ t: Date.now() / 1000, kind: 'err', text: 'geolocation: ' + err.message }]),
        { enableHighAccuracy: true, timeout: 15000 },
      );
    };
    $('btn-halt-drone').onclick = () => { if (state && state.gps) $('in-halt').value = state.gps.alt; };
    $('btn-offset').onclick = () => {
      const v = parseFloat($('in-offset').value);
      if (num(v)) sendCmd(`SET offset ${v}`);
    };
    $('btn-auto').onclick = () => sendCmd('MODE AUTO');
    $('btn-manual').onclick = () => sendCmd('MODE MANUAL');
    $('btn-save').onclick = () => sendCmd('SAVE');

    let lastAim = 0;
    const aim = () => {
      const now = Date.now();
      if (now - lastAim < 100) return;
      lastAim = now;
      sendCmd(`AIM ${$('sl-pan').value} ${$('sl-tilt').value}`);
    };
    $('sl-pan').oninput = aim;
    $('sl-tilt').oninput = aim;
    $('sl-pan').onchange = () => { lastAim = 0; aim(); };
    $('sl-tilt').onchange = () => { lastAim = 0; aim(); };

    $('cmdform').onsubmit = (e) => {
      e.preventDefault();
      const line = $('cmdline').value.trim();
      if (!line) return;
      history.push(line);
      historyPos = history.length;
      $('cmdline').value = '';
      sendCmd(line);
    };
    $('cmdline').onkeydown = (e) => {
      if (e.key === 'ArrowUp' && historyPos > 0) { $('cmdline').value = history[--historyPos]; e.preventDefault(); }
      if (e.key === 'ArrowDown' && historyPos < history.length) { $('cmdline').value = history[++historyPos] || ''; e.preventDefault(); }
    };
  }

  // -------------------------------------------------------------------------------- console

  function appendConsole(items) {
    if (!items || !items.length) return;
    const box = $('console');
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
    for (const it of items) {
      const d = document.createElement('div');
      d.className = it.kind;
      const t = new Date(it.t * 1000).toTimeString().slice(0, 8);
      const prefix = it.kind === 'tx' ? '> ' : it.kind === 'err' ? '! ' : it.kind === 'ack' ? '✓ ' : '  ';
      d.textContent = `${t} ${prefix}${it.text}`;
      box.appendChild(d);
    }
    while (box.childElementCount > 300) box.removeChild(box.firstChild);
    if (atBottom) box.scrollTop = box.scrollHeight;
  }

  // ---------------------------------------------------------------------------------- track

  function applyTrack(tr) {
    if (!tr) return;
    if (tr.reset || tr.gen !== trailGen) {
      trail.setLatLngs([]);
      trailGen = tr.gen;
    }
    for (const p of tr.pts) trail.addLatLng([p[0], p[1]]);
  }

  // --------------------------------------------------------------------------------- render

  function setStale(cardId, section, limit) {
    $(cardId).classList.toggle('stale', !section || section.age > limit);
  }

  function pill(id, text, cls) {
    const el = $(id);
    el.textContent = text;
    el.className = 'pill' + (cls ? ' ' + cls : '');
  }

  function render() {
    const s = state;
    if (!s) return;
    const { gps, bat, rf, att, mode, trk, stat, hello, flight } = s;

    // header
    if (!s.conn.connected) pill('pill-conn', 'no tracker', 'bad');
    else if (s.conn.last_rx_age === null || s.conn.last_rx_age > 3) pill('pill-conn', 'tracker silent', 'warn');
    else pill('pill-conn', 'tracker OK', 'good');
    $('pill-conn').title = s.conn.error || 'USB link to the tracker';
    set('pill-src', s.conn.source || cfg.source || '');

    if (rf && rf.age <= STALE_S.rf) pill('pill-rf', `LQ ${rf.lq}%  ${rf.rssi1} dBm`, rf.lq >= 80 ? 'good' : rf.lq >= 50 ? 'warn' : 'bad');
    else pill('pill-rf', 'LQ –', '');
    pill('pill-mode', mode ? mode.m : '–', '');
    if (gps && gps.age <= STALE_S.gps) pill('pill-sats', `GPS ${gps.sats}`, gps.sats >= 10 ? 'good' : gps.sats >= 6 ? 'warn' : 'bad');
    else pill('pill-sats', 'GPS –', '');

    // position
    setStale('card-pos', gps, STALE_S.gps);
    set('gps-age', gps ? `${gps.age.toFixed(1)} s ago` : 'no data');
    set('v-lat', gps ? gps.lat.toFixed(6) : '–');
    set('v-lon', gps ? gps.lon.toFixed(6) : '–');
    set('v-alt', gps ? `${gps.alt} m` : '–');
    set('v-gs', gps ? `${gps.gs.toFixed(0)} km/h` : '–');
    set('v-hdg', gps ? `${gps.hdg.toFixed(0)}°` : '–');
    set('v-sats', gps ? String(gps.sats) : '–');

    // geometry
    setStale('card-geo', trk, STALE_S.trk);
    set('v-dist', trk && num(trk.dist) ? fmtDist(trk.dist) : '–');
    set('v-dist3d', trk && num(trk.dist3d) ? fmtDist(trk.dist3d) : '–');
    set('v-az', trk && num(trk.az) ? `${trk.az.toFixed(0)}°` : '–');
    set('v-el', trk && num(trk.el) ? `${trk.el.toFixed(0)}°` : '–');
    set('v-rel', gps && trk && trk.home && num(trk.halt) ? `${Math.round(gps.alt - trk.halt)} m` : '–');

    // radio link
    setStale('card-rf', rf, STALE_S.rf);
    set('rf-age', rf ? `${rf.age.toFixed(1)} s ago` : 'no data');
    set('v-lq', rf ? `${rf.lq} %` : '–');
    set('v-rssi', rf ? `${rf.rssi1} / ${rf.rssi2} dBm` : '–');
    set('v-snr', rf ? `${rf.snr} dB` : '–');
    set('v-txpwr', rf ? (rf.txpwr ? `${rf.txpwr} mW` : '?') : '–');
    set('v-ant', rf ? `${rf.ant} / ${rf.rfmode}` : '–');
    set('v-dn', rf ? `${rf.drssi} dBm, LQ ${rf.dlq} %` : '–');

    // battery
    setStale('card-bat', bat, STALE_S.bat);
    set('bat-age', bat ? `${bat.age.toFixed(1)} s ago` : 'no data');
    set('v-bv', bat ? `${bat.v.toFixed(1)} V` : '–');
    set('v-ba', bat ? `${bat.a.toFixed(1)} A` : '–');
    set('v-bmah', bat ? `${bat.mah} mAh` : '–');
    set('v-bpct', bat ? `${bat.pct} %` : '–');

    // attitude
    setStale('card-att', att, STALE_S.att);
    set('att-age', att ? `${att.age.toFixed(1)} s ago` : 'no data');
    set('v-pitch', att ? `${att.pitch.toFixed(0)}°` : '–');
    set('v-roll', att ? `${att.roll.toFixed(0)}°` : '–');
    set('v-yaw', att ? `${att.yaw.toFixed(0)}°` : '–');
    drawHorizon(att ? att.pitch : 0, att ? att.roll : 0);

    // tracker
    setStale('card-trk', trk, STALE_S.trk);
    set('trk-age', trk ? `${trk.age.toFixed(1)} s ago` : 'no data');
    set('v-tmode', trk ? trk.mode : '–');
    set('v-tstat', !trk ? '–' : trk.tracking ? 'tracking' + (trk.flip ? ' (over the top)' : '') : trk.home ? (trk.mode === 'manual' ? 'manual' : 'waiting for GPS') : 'no home set');
    set('v-pan', trk ? `${trk.pan.toFixed(0)}°` : '–');
    set('v-tilt', trk ? `${trk.tilt.toFixed(0)}°` : '–');
    if (trk) { $('m-pan').value = trk.pan; $('m-tilt').value = trk.tilt; }
    set('v-home', trk && trk.home ? `${trk.hlat.toFixed(5)}, ${trk.hlon.toFixed(5)} @ ${Math.round(trk.halt)} m` : 'not set');
    const manual = trk && trk.mode === 'manual';
    $('btn-auto').classList.toggle('on', !!trk && !manual);
    $('btn-manual').classList.toggle('on', !!manual);
    $('manual-sliders').classList.toggle('hidden', !manual);
    if (manual && document.activeElement !== $('sl-pan')) $('sl-pan').value = Math.round(trk.tpan);
    if (manual && document.activeElement !== $('sl-tilt')) $('sl-tilt').value = Math.round(trk.ttilt);
    const c = s.cfg;
    if (c && document.activeElement !== $('in-offset') && $('in-offset').dataset.shown !== String(c.offset)) {
      $('in-offset').value = c.offset;
      $('in-offset').dataset.shown = String(c.offset);
    }

    // flight stats
    set('v-fdist', fmtDist(flight.max_dist_m));
    set('v-falt', num(flight.max_alt_rel_m) ? `${Math.round(flight.max_alt_rel_m)} m` : '–');
    set('v-fspd', `${flight.max_speed_kmh.toFixed(0)} km/h`);
    set('v-fpath', fmtDist(flight.path_m));

    // device
    set('v-fw', hello ? `${hello.fw} (${hello.chip})` : '–');
    set('v-espnow', hello ? (hello.espnow ? 'listening' : (hello.uid ? 'failed to start' : 'off - no UID, use BIND')) : '–');
    set('v-uid', hello && hello.uid ? hello.uid : (hello ? 'not set' : '–'));
    set('v-pk', stat ? `${stat.espnow} ESP-NOW, ${stat.msp_ok} MSP, ${stat.crsf_ok} CRSF` : '–');
    set('v-err', stat ? `${stat.msp_bad} MSP, ${stat.crsf_bad} CRSF, ${stat.dropped} dropped` : '–');

    // map overlays
    const hasFix = gps && num(gps.lat) && num(gps.lon) && !(gps.lat === 0 && gps.lon === 0);
    if (hasFix) {
      if (!map.hasLayer(droneMarker)) droneMarker.addTo(map);
      droneMarker.setLatLng([gps.lat, gps.lon]);
      const svg = droneMarker.getElement() && droneMarker.getElement().firstChild;
      if (svg) svg.style.transform = `rotate(${gps.hdg}deg)`;
      if (firstFix) { firstFix = false; map.setView([gps.lat, gps.lon], 16); }
      else if (following) map.panTo([gps.lat, gps.lon], { animate: false });
    }
    if (trk && trk.home) {
      if (!map.hasLayer(homeMarker)) homeMarker.addTo(map);
      homeMarker.setLatLng([trk.hlat, trk.hlon]);
      homeLine.setLatLngs(hasFix ? [[trk.hlat, trk.hlon], [gps.lat, gps.lon]] : []);
    } else {
      if (map.hasLayer(homeMarker)) map.removeLayer(homeMarker);
      homeLine.setLatLngs([]);
    }
  }

  function fmtDist(m) {
    if (!num(m)) return '–';
    return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
  }

  function drawHorizon(pitch, roll) {
    const cv = $('horizon');
    const g = cv.getContext('2d');
    const w = cv.width, h = cv.height;
    g.clearRect(0, 0, w, h);
    g.save();
    g.beginPath();
    g.arc(w / 2, h / 2, w / 2 - 1, 0, Math.PI * 2);
    g.clip();
    g.translate(w / 2, h / 2);
    g.rotate((-roll * Math.PI) / 180);
    g.translate(0, pitch * (h / 90));
    g.fillStyle = '#2b6cb0';
    g.fillRect(-w * 2, -h * 3, w * 4, h * 3);
    g.fillStyle = '#8a5a2b';
    g.fillRect(-w * 2, 0, w * 4, h * 3);
    g.strokeStyle = '#fff';
    g.lineWidth = 2;
    g.beginPath();
    g.moveTo(-w, 0);
    g.lineTo(w, 0);
    g.stroke();
    g.restore();
    g.strokeStyle = '#ffd24a';
    g.lineWidth = 3;
    g.beginPath();
    g.moveTo(w / 2 - 28, h / 2); g.lineTo(w / 2 - 8, h / 2); g.lineTo(w / 2, h / 2 + 8);
    g.lineTo(w / 2 + 8, h / 2); g.lineTo(w / 2 + 28, h / 2);
    g.stroke();
  }

  // ------------------------------------------------------------------------------ websocket

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      state = msg.state;
      applyTrack(msg.track);
      appendConsole(msg.console);
      render();
    };
    ws.onclose = () => {
      pill('pill-conn', 'server offline', 'bad');
      setTimeout(connect, 1500);
    };
    ws.onerror = () => ws.close();
  }

  // ----------------------------------------------------------------------------------- start

  fetch('/api/config')
    .then((r) => r.json())
    .then((c) => {
      cfg = c;
      initMap();
      wireControls();
      drawHorizon(0, 0);
      $('btn-home-geo').disabled = !window.isSecureContext;
      if (cfg.read_only) document.querySelectorAll('#card-trk button, #cmdform button').forEach((b) => (b.disabled = true));
      connect();
    });
})();
