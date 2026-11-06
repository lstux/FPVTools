(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const num = (v) => typeof v === 'number' && Number.isFinite(v);
  const set = (id, text) => { const el = $(id); if (el && el.textContent !== text) el.textContent = text; };
  const { fmtDist, fmtTime, wrap360, wrap180 } = window.Hud;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const STALE_S = { gps: 3, rf: 3, bat: 5, att: 2, trk: 3, baro: 3, vario: 3 };

  // ------------------------------------------------------------------------------ preferences
  const KIOSK = !!window.ESPTRACKER_KIOSK;
  const PREF_DEFAULTS = {
    video: null, localcam: '', mapstyle: 'night', altref: 'auto', cells: 'auto', lowcell: 3.5,
    windwarn: 25, windmax: 40, swapped: false, hudfps: KIOSK ? 30 : 60,
  };
  const prefs = Object.assign({}, PREF_DEFAULTS);
  try { Object.assign(prefs, JSON.parse(localStorage.getItem('esptracker.prefs') || '{}')); } catch (_) { /* private mode */ }
  const savePrefs = () => { try { localStorage.setItem('esptracker.prefs', JSON.stringify(prefs)); } catch (_) { /* ignore */ } };

  let cfg = {};
  let state = null;
  let map, droneMarker, homeMarker, trail, homeLine;
  let following = true;
  let placingHome = false;
  let firstFix = true;
  let trailGen = -1;
  let maxVolts = 0;
  let weather = null;
  const history = [];
  let historyPos = 0;

  const fresh = (sec, key) => sec && sec.age <= STALE_S[key];

  // ------------------------------------------------------------------------------ layout
  function applyLayout() {
    const vid = $('pane-video'), mp = $('pane-map');
    const videoMain = !prefs.swapped;
    vid.classList.toggle('main-pane', videoMain);
    vid.classList.toggle('pip-pane', !videoMain);
    mp.classList.toggle('main-pane', !videoMain);
    mp.classList.toggle('pip-pane', videoMain);
    $('app').classList.toggle('video-main', videoMain);
    if (map) setTimeout(() => map.invalidateSize(), 50);
  }

  function swapViews() {
    prefs.swapped = !prefs.swapped;
    savePrefs();
    applyLayout();
  }

  // the view to come back to in flight: video (or horizon) in front, no panel, map following the drone
  function homeView() {
    if (placingHome) setPlacingHome(false);
    openPanel(null);
    if (prefs.swapped) swapViews();
    setFollow(true);
    if (state && state.gps && map) map.panTo([state.gps.lat, state.gps.lon], { animate: false });
  }

  function openPanel(name) {
    const drawer = $('drawer');
    const same = !drawer.classList.contains('hidden') && drawer.dataset.panel === name;
    if (same || !name) {
      drawer.classList.add('hidden');
      $('app').classList.remove('drawer-open');
      drawer.dataset.panel = '';
      if (map) setTimeout(() => map.invalidateSize(), 50);
    } else {
      drawer.classList.remove('hidden');
      $('app').classList.add('drawer-open');
      drawer.dataset.panel = name;
      if (map) setTimeout(() => map.invalidateSize(), 50);
      document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('on', p.dataset.panel === name));
      const btn = document.querySelector(`.tabs button[data-panel="${name}"]`);
      set('drawer-title', btn ? btn.textContent : name);
      if (name === 'weather') loadWeather(false);
      if (name === 'display') refreshVideoInfo();
      if (name === 'console') btn.classList.remove('alert');
    }
    document.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.panel === drawer.dataset.panel));
  }

  // ------------------------------------------------------------------------------ map
  function droneIcon() {
    return L.divIcon({
      className: 'drone-icon',
      html: '<svg viewBox="0 0 28 28" width="28" height="28"><path d="M14 2 L24 25 L14 19 L4 25 Z" fill="#ffd84a" stroke="#000" stroke-width="1.5" stroke-linejoin="round"/></svg>',
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  function homeIcon() {
    return L.divIcon({ className: 'home-icon', html: '<div>H</div>', iconSize: [20, 20], iconAnchor: [10, 10] });
  }

  function initMap() {
    map = L.map('map', { zoomControl: true, attributionControl: true }).setView([48.8566, 2.3522], 13);
    const bases = {};
    const lt = cfg.local_tiles;
    if (lt) {
      bases['Offline tiles'] = L.tileLayer('/tiles/{z}/{x}/{y}', { minZoom: lt.minzoom, maxZoom: 20, maxNativeZoom: lt.maxzoom, attribution: 'offline tiles' });
    }
    bases['OpenStreetMap'] = L.tileLayer(cfg.tile_url, { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' });
    bases['No map'] = L.layerGroup();
    (lt ? bases['Offline tiles'] : bases['OpenStreetMap']).addTo(map);
    L.control.layers(bases, null, { position: 'topright' }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    if (lt && lt.center && lt.center.length >= 2) map.setView([lt.center[1], lt.center[0]], Math.min(lt.maxzoom, 14));

    trail = L.polyline([], { color: '#4fd6ff', weight: 3, opacity: 0.9 }).addTo(map);
    homeLine = L.polyline([], { color: '#ff5ad1', weight: 2, dashArray: '6 6' }).addTo(map);
    droneMarker = L.marker([0, 0], { icon: droneIcon(), zIndexOffset: 1000, interactive: false });
    homeMarker = L.marker([0, 0], { icon: homeIcon(), interactive: false });
    map.on('dragstart', () => setFollow(false));
    map.on('click', onMapClick);
    applyMapStyle();
  }

  function applyMapStyle() {
    $('map').classList.toggle('map-night', prefs.mapstyle === 'night');
    document.querySelectorAll('[data-mapstyle]').forEach((b) => b.classList.toggle('on', b.dataset.mapstyle === prefs.mapstyle));
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
    if (on && $('pane-map').classList.contains('pip-pane')) { prefs.swapped = true; applyLayout(); }
    $('maphint').classList.toggle('hidden', !on);
    $('btn-home-map').classList.toggle('on', on);
    $('map').style.cursor = on ? 'crosshair' : '';
  }

  // Altitude (sea level) for a typed / clicked home: the field, else the current home altitude,
  // else the drone's altitude (assumes it is still on the ground next to the tracker).
  function homeAltForManualHome() {
    const typed = parseFloat($('in-halt').value);
    if (num(typed)) return typed;
    if (state && state.trk && state.trk.home && num(state.trk.halt)) return state.trk.halt;
    if (state && state.gps && num(state.gps.alt)) return state.gps.alt;
    return 0;
  }

  // ------------------------------------------------------------------------------ commands
  async function sendCmd(line) {
    try {
      const r = await fetch('/api/cmd', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ line }) });
      if (!r.ok) {
        let detail = r.statusText;
        try { detail = (await r.json()).detail || detail; } catch (_) { /* keep statusText */ }
        appendConsole([{ t: Date.now() / 1000, kind: 'err', text: `${line.split(' ')[0]}: ${detail}` }]);
      }
    } catch (err) {
      appendConsole([{ t: Date.now() / 1000, kind: 'err', text: String(err) }]);
    }
  }

  function localError(text) { appendConsole([{ t: Date.now() / 1000, kind: 'err', text }]); }

  function wireControls() {
    document.querySelectorAll('.tabs button').forEach((b) => (b.onclick = () => openPanel(b.dataset.panel)));
    $('drawer-close').onclick = () => openPanel(null);
    document.querySelectorAll('[data-swap]').forEach((b) => (b.onclick = swapViews));
    // Keys: a keyboard, or the push buttons of the Raspberry Pi kiosk (GPIO keys: Back, Page Down, Home)
    const PANELS = ['tracker', 'weather', 'link', 'console', 'display'];
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' || e.key === 'BrowserBack') {
        e.preventDefault();
        if (placingHome) setPlacingHome(false); else openPanel(null);
        return;
      }
      if (e.key === 'BrowserHome') { e.preventDefault(); homeView(); return; }
      if (e.key === 'PageDown') { e.preventDefault(); swapViews(); return; }
      if (e.target.closest && e.target.closest('input, select, textarea')) return;
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (e.key === 's' || e.key === 'S') swapViews();
      else if (e.key === 'h' || e.key === 'H') homeView();
      else if (e.key >= '1' && e.key <= '5') openPanel(PANELS[Number(e.key) - 1]);
    });

    $('btn-follow').onclick = () => {
      setFollow(!following);
      if (following && state && state.gps) map.panTo([state.gps.lat, state.gps.lon], { animate: false });
    };
    $('btn-centerhome').onclick = () => {
      if (state && state.trk && state.trk.home) { setFollow(false); map.setView([state.trk.hlat, state.trk.hlon], Math.max(map.getZoom(), 15)); }
    };
    $('btn-fit').onclick = () => {
      if (trail.getLatLngs().length > 1) { setFollow(false); map.fitBounds(trail.getBounds().pad(0.2)); }
    };
    $('btn-clear').onclick = () => fetch('/api/track/clear', { method: 'POST' });

    $('btn-home-drone').onclick = () => sendCmd('HOME DRONE');
    $('btn-home-tgps').onclick = () => sendCmd('HOME GPS');
    $('btn-cal').onclick = () => sendCmd(state && state.sens && state.sens.cal === 'running' ? 'CAL MAG STOP' : 'CAL MAG START');
    $('btn-cal-clear').onclick = () => sendCmd('CAL MAG CLEAR');
    document.querySelectorAll('[data-north]').forEach((b) => (b.onclick = () => sendCmd(`SET auto_north ${b.dataset.north}`)));
    document.querySelectorAll('[data-altsrc]').forEach((b) => (b.onclick = () => sendCmd(`SET alt_src ${b.dataset.altsrc}`)));
    $('btn-decl').onclick = () => {
      const d = parseFloat($('in-decl').value), m = parseFloat($('in-mount').value);
      if (num(d)) sendCmd(`SET declination ${d}`);
      if (num(m)) sendCmd(`SET compass_mount ${m}`);
    };
    $('btn-home-clear').onclick = () => sendCmd('HOME CLEAR');
    $('btn-home-map').onclick = () => setPlacingHome(!placingHome);
    $('btn-home-geo').onclick = () => {
      if (!window.isSecureContext || !navigator.geolocation) { localError('Device location needs https or http://localhost'); return; }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const c = pos.coords;
          const typed = parseFloat($('in-halt').value);
          const alt = num(typed) ? typed : num(c.altitude) ? c.altitude : homeAltForManualHome();
          sendCmd(`HOME ${c.latitude.toFixed(7)} ${c.longitude.toFixed(7)} ${Math.round(alt)}`);
        },
        (err) => localError('Device location: ' + err.message),
        { enableHighAccuracy: true, timeout: 15000 },
      );
    };
    $('btn-halt-drone').onclick = () => { if (state && state.gps) $('in-halt').value = state.gps.alt; };
    $('btn-offset').onclick = () => { const v = parseFloat($('in-offset').value); if (num(v)) sendCmd(`SET offset ${v}`); };
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

    // display settings
    $('sel-video').onchange = () => { prefs.video = $('sel-video').value; savePrefs(); startVideo(); };
    $('sel-localcam').onchange = () => { prefs.localcam = $('sel-localcam').value; savePrefs(); startVideo(); };
    document.querySelectorAll('[data-mapstyle]').forEach((b) => (b.onclick = () => { prefs.mapstyle = b.dataset.mapstyle; savePrefs(); applyMapStyle(); }));
    $('sel-altref').value = prefs.altref;
    $('sel-altref').onchange = () => { prefs.altref = $('sel-altref').value; savePrefs(); };
    for (let n = 1; n <= 12; n++) $('sel-cells').add(new Option(n + 'S', String(n)));
    $('sel-cells').value = String(prefs.cells);
    $('sel-cells').onchange = () => { prefs.cells = $('sel-cells').value; savePrefs(); };
    const numPref = (id, key) => {
      $(id).value = prefs[key];
      $(id).onchange = () => { const v = parseFloat($(id).value); if (num(v)) { prefs[key] = v; savePrefs(); renderWeather(); } };
    };
    numPref('in-lowcell', 'lowcell');
    numPref('in-windwarn', 'windwarn');
    numPref('in-windmax', 'windmax');
    $('sel-hudfps').value = String(prefs.hudfps);
    $('sel-hudfps').onchange = () => { prefs.hudfps = Number($('sel-hudfps').value); savePrefs(); };
    $('btn-fullscreen').classList.toggle('hidden', KIOSK);
    $('btn-fullscreen').onclick = () => {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => {});
    };
    $('wx-refresh').onclick = () => loadWeather(true);
  }

  // ------------------------------------------------------------------------------ console
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
    // errors must be seen even with the drawer closed
    if (items.some((i) => i.kind === 'err')) document.querySelector('.tabs button[data-panel="console"]').classList.add('alert');
  }

  function applyTrack(tr) {
    if (!tr) return;
    if (tr.reset || tr.gen !== trailGen) { trail.setLatLngs([]); trailGen = tr.gen; }
    for (const p of tr.pts) trail.addLatLng([p[0], p[1]]);
  }

  // ------------------------------------------------------------------------------ derived values
  function cells(bat) {
    if (prefs.cells !== 'auto') return parseInt(prefs.cells, 10);
    if (!maxVolts) return null;
    return Math.max(1, Math.ceil(maxVolts / 4.35));
  }

  function derive(s) {
    const { gps, bat, rf, att, mode, trk, baro, vario, flight } = s;
    const d = {};
    const gpsOk = fresh(gps, 'gps');
    const hasFix = gpsOk && num(gps.lat) && !(gps.lat === 0 && gps.lon === 0);
    if (fresh(att, 'att')) { d.pitch = att.pitch; d.roll = att.roll; }
    // the nose direction: GPS course when moving (no compass drift), else the FC's yaw
    if (gpsOk && gps.gs > 10) d.heading = gps.hdg;
    else if (fresh(att, 'att') && num(att.yaw)) d.heading = wrap360(att.yaw);
    else if (gpsOk) d.heading = gps.hdg;
    d.speed = gpsOk ? gps.gs : null;
    d.sats = gpsOk ? gps.sats : null;

    // altitude
    const homeAlt = trk && trk.home && num(trk.halt) ? trk.halt : null;
    const pick = prefs.altref;
    const options = {
      home: hasFix && homeAlt !== null ? [gps.alt - homeAlt, 'HOME m', 'above home'] : null,
      baro: fresh(baro, 'baro') ? [baro.alt, 'BARO m', 'baro'] : null,
      msl: gpsOk ? [gps.alt, 'MSL m', 'GPS sea level'] : null,
    };
    const order = pick === 'auto' ? ['home', 'baro', 'msl'] : [pick];
    for (const k of order) { if (options[k]) { [d.alt, d.altLabel, d.altDesc] = options[k]; break; } }
    if (fresh(baro, 'baro') && num(baro.vs)) d.vs = baro.vs;
    else if (fresh(vario, 'vario')) d.vs = vario.vs;

    // home: tracker azimuth is tracker -> drone, home is the other way
    if (trk && trk.home && hasFix && num(trk.az)) {
      d.homeBrg = wrap360(trk.az + 180);
      d.homeDist = trk.dist;
    }

    d.mode = mode ? mode.m.replace(/\*$/, '') : null;
    d.armed = flight ? flight.armed : null;
    d.timeS = flight ? flight.time_s : 0;

    if (fresh(bat, 'bat')) {
      d.volts = bat.v;
      d.mah = bat.mah;
      const n = cells(bat);
      if (n && bat.v > 0.5) {
        d.cellV = bat.v / n;
        d.cellLevel = d.cellV < prefs.lowcell - 0.2 ? 'warning' : d.cellV < prefs.lowcell ? 'caution' : 'ok';
      }
    }
    if (fresh(rf, 'rf')) {
      d.lq = rf.lq;
      d.rssi = rf.rssi1;
      d.lqLevel = rf.lq < 25 ? 'warning' : rf.lq < 60 ? 'caution' : 'ok';
    }
    d.warnings = warnings(s, d);
    return d;
  }

  function warnings(s, d) {
    const out = [];
    const { gps, mode, rf } = s;
    if (mode && /!FS|FAILSAFE|^FS/i.test(mode.m) && mode.age < 5) out.push({ text: 'FAILSAFE', level: 'warning' });
    if (s.conn.connected && gps && gps.age > STALE_S.gps && (!rf || rf.age > STALE_S.rf)) out.push({ text: 'TELEMETRY LOST', level: 'warning' });
    if (d.lqLevel === 'warning') out.push({ text: 'LINK ' + d.lq + '%', level: 'warning' });
    else if (d.lqLevel === 'caution') out.push({ text: 'LINK ' + d.lq + '%', level: 'caution' });
    if (d.cellLevel === 'warning') out.push({ text: 'BATTERY ' + d.cellV.toFixed(2) + ' V', level: 'warning' });
    else if (d.cellLevel === 'caution') out.push({ text: 'BATTERY LOW', level: 'caution' });
    if (num(d.sats) && d.sats < 6) out.push({ text: 'GPS ' + d.sats + ' SATS', level: 'caution' });
    if (!s.conn.connected) out.push({ text: 'NO TRACKER', level: 'caution' });
    return out;
  }

  // ------------------------------------------------------------------------------ render (5-10 Hz)
  function ann(id, text, level, title) {
    const el = $(id);
    el.className = 'ann' + (level ? ' ' + level : '');
    const span = el.lastElementChild;
    if (span.textContent !== text) span.textContent = text;
    if (title) el.title = title;
  }

  function render() {
    const s = state;
    if (!s) return;
    const { gps, bat, rf, att, mode, trk, stat, hello, flight, baro, vario } = s;
    if (bat && num(bat.v) && bat.v > maxVolts) maxVolts = bat.v;
    const d = derive(s);
    hudTarget = d;

    // annunciators
    if (!s.conn.connected) ann('a-conn', 'offline', 'warning', s.conn.error || 'USB link to the tracker');
    else if (s.conn.last_rx_age === null || s.conn.last_rx_age > 3) ann('a-conn', 'silent', 'caution');
    else ann('a-conn', s.conn.source === 'simulator' ? 'sim' : 'OK', 'ok');
    ann('a-link', fresh(rf, 'rf') ? `${rf.lq}% ${rf.rssi1}` : '–', fresh(rf, 'rf') ? d.lqLevel : '');
    ann('a-gps', fresh(gps, 'gps') ? `${gps.sats} sats` : '–', fresh(gps, 'gps') ? (gps.sats >= 8 ? 'ok' : gps.sats >= 6 ? 'caution' : 'warning') : '');
    ann('a-bat', num(d.volts) ? `${d.volts.toFixed(1)}V` + (num(d.cellV) ? ` ${d.cellV.toFixed(2)}` : '') : '–', num(d.volts) ? d.cellLevel || 'ok' : '');
    const fs = d.warnings.some((w) => w.text === 'FAILSAFE');
    ann('a-mode', mode ? mode.m : '–', fs ? 'warning' : mode ? (d.armed ? 'ok' : 'info') : '');
    ann('a-time', fmtTime(d.timeS), d.armed ? 'ok' : '');

    // bottom readouts
    set('r-dist', trk && num(trk.dist) ? fmtDist(trk.dist) : '–');
    $('r-dist').className = 'nav';
    set('r-dist3d', trk && num(trk.dist3d) ? `3D ${fmtDist(trk.dist3d)}` : (trk && !trk.home ? 'no home set' : ''));
    set('r-rel', num(d.alt) ? `${Math.round(d.alt)} m` : '–');
    set('r-altref', d.altDesc || '');
    set('r-gs', num(d.speed) ? d.speed.toFixed(0) : '–');
    set('r-amps', fresh(bat, 'bat') ? `${bat.a.toFixed(1)} A` : '–');
    set('r-mah', fresh(bat, 'bat') ? `${bat.mah} mAh${num(bat.pct) && bat.pct > 0 ? `, ${bat.pct}%` : ''}` : '');
    set('r-azel', trk && num(trk.az) ? `${trk.az.toFixed(0)}° ${trk.el.toFixed(0)}°` : '–');
    $('r-azel').className = 'tgt';
    set('r-tstat', trackerStatus(trk));
    set('r-rssi', fresh(rf, 'rf') ? `${rf.rssi1} dBm` : '–');
    set('r-snr', fresh(rf, 'rf') ? `SNR ${rf.snr}, ${rf.txpwr ? rf.txpwr + ' mW' : '? mW'}` : '');

    // tracker panel
    set('v-tstat', trackerStatus(trk) || '–');
    const HSRC = { gps: 'tracker GPS', drone: 'drone', manual: 'typed / map' };
    set('v-home', trk && trk.home ? `${trk.hlat.toFixed(5)}, ${trk.hlon.toFixed(5)}, ${Math.round(trk.halt)} m${HSRC[trk.hsrc] ? ` (${HSRC[trk.hsrc]})` : ''}` : 'not set');
    set('v-azel', trk && num(trk.az) ? `${trk.az.toFixed(1)}° / ${trk.el.toFixed(1)}°` : '–');
    set('v-pantilt', trk ? `${trk.pan.toFixed(0)}° / ${trk.tilt.toFixed(0)}°${trk.flip ? ' (flipped)' : ''}` : '–');
    if (trk) { $('m-pan').style.left = `calc(${(trk.pan / 180) * 100}% - 2px)`; $('m-tilt').style.left = `calc(${(trk.tilt / 180) * 100}% - 2px)`; }
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

    renderTrackerSensors(s);

    // link panel
    set('v-lq', rf ? `${rf.lq} %` : '–');
    set('v-rssi', rf ? `${rf.rssi1} / ${rf.rssi2} dBm` : '–');
    set('v-snr', rf ? `${rf.snr} dB` : '–');
    set('v-txpwr', rf ? (rf.txpwr ? `${rf.txpwr} mW` : 'unknown') : '–');
    set('v-ant', rf ? `${rf.ant} / ${rf.rfmode}` : '–');
    set('v-dn', rf ? `${rf.drssi} dBm, LQ ${rf.dlq} %` : '–');
    set('v-ftime', fmtTime(flight.time_s));
    set('v-fdist', fmtDist(flight.max_dist_m));
    set('v-falt', num(flight.max_alt_rel_m) ? `${Math.round(flight.max_alt_rel_m)} m` : '–');
    set('v-fspd', `${flight.max_speed_kmh.toFixed(0)} km/h`);
    set('v-fpath', fmtDist(flight.path_m));
    set('v-latlon', gps ? `${gps.lat.toFixed(6)}, ${gps.lon.toFixed(6)}` : '–');
    set('v-alt', gps ? `${gps.alt} m` : '–');
    set('v-baro', baro ? `${baro.alt.toFixed(1)} m` + (num(baro.vs) ? `, ${baro.vs.toFixed(1)} m/s` : '') : vario ? `vario ${vario.vs.toFixed(1)} m/s` : '–');
    set('v-att', att ? `${att.pitch.toFixed(0)}° / ${att.roll.toFixed(0)}° / ${att.yaw.toFixed(0)}°` : '–');
    set('v-fw', hello ? `${hello.fw} (${hello.chip})` : '–');
    set('v-espnow', hello ? (hello.espnow ? 'listening' : hello.uid ? 'failed to start' : 'off: no UID, use BIND') : '–');
    set('v-uid', hello && hello.uid ? hello.uid : hello ? 'not set' : '–');
    set('v-pk', stat ? `${stat.espnow} ESP-NOW, ${stat.msp_ok} MSP, ${stat.crsf_ok} CRSF` : '–');
    set('v-err', stat ? `${stat.msp_bad} MSP, ${stat.crsf_bad} CRSF, ${stat.dropped} dropped` : '–');

    // map
    const hasFix = gps && num(gps.lat) && !(gps.lat === 0 && gps.lon === 0);
    if (hasFix) {
      if (!map.hasLayer(droneMarker)) droneMarker.addTo(map);
      droneMarker.setLatLng([gps.lat, gps.lon]);
      const svg = droneMarker.getElement() && droneMarker.getElement().firstChild;
      if (svg) svg.style.transform = `rotate(${num(d.heading) ? d.heading : gps.hdg}deg)`;
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
    maybeAutoWeather();
  }

  function fillOnce(id, value) {
    const el = $(id);
    if (value === undefined || value === null || document.activeElement === el || el.dataset.shown === String(value)) return;
    el.value = value;
    el.dataset.shown = String(value);
  }

  function renderTrackerSensors(s) {
    const { tgps, sens, cfg: c, trk } = s;
    const gpsOn = tgps && tgps.age < 5;
    const sensOn = sens && sens.age < 5 && (sens.imu || sens.mag || sens.baro);
    $('sens-none').classList.toggle('hidden', !!(gpsOn || sensOn));
    $('sens-block').classList.toggle('hidden', !(gpsOn || sensOn));
    $('btn-home-tgps').classList.toggle('hidden', !gpsOn);
    $('btn-home-tgps').disabled = !(gpsOn && tgps.fix);

    if (!gpsOn) set('v-tgps', 'not connected');
    else {
      const ah = tgps.ahome === 'averaging' ? `, averaging ${tgps.ahome_pct}%` : tgps.ahome === 'locked' ? ', home locked' : '';
      set('v-tgps', `${tgps.sats} sats, ${tgps.fix ? 'fix' : 'no fix'}, HDOP ${tgps.hdop.toFixed(1)}${ah}`);
      $('v-tgps').title = `${tgps.baud} baud, ${tgps.good} good / ${tgps.bad} bad sentences`;
    }
    $('v-tgps').className = gpsOn ? (tgps.fix ? 'ok-t' : 'caution-t') : '';

    const running = sensOn && sens.cal === 'running';
    if (sensOn && sens.mag) {
      const state_ = running ? `calibrating, ${sens.cal_cov}% of the turn` : sens.cal === 'ok' ? 'calibrated' : 'not calibrated';
      set('v-compass', `${num(sens.hdg) ? Math.round(sens.hdg) + '° true, ' : ''}${state_} (${sens.mag})`);
      $('v-compass').className = sens.cal === 'ok' ? 'ok-t' : 'caution-t';
    } else {
      set('v-compass', 'none');
      $('v-compass').className = '';
    }
    set('v-level', sensOn && num(sens.tilt) ? `${sens.tilt.toFixed(1)}° from level (${sens.imu})` : 'no accelerometer');
    $('v-level').className = sensOn && num(sens.tilt) ? (sens.tilt > 5 ? 'caution-t' : 'ok-t') : '';
    set('v-tbaro', sensOn && num(sens.hpa) ? `${sens.hpa.toFixed(1)} hPa, ${sens.temp.toFixed(1)} °C (${sens.baro})` : sensOn && sens.baro ? `${sens.baro}, no reading` : 'none');

    const hasMag = sensOn && !!sens.mag;
    $('row-cal').classList.toggle('hidden', !hasMag);
    $('row-north').classList.toggle('hidden', !hasMag);
    $('row-decl').classList.toggle('hidden', !hasMag);
    $('cal-hint').classList.toggle('hidden', !running);
    set('btn-cal', running ? 'Finish calibration' : 'Calibrate compass');
    $('btn-cal').classList.toggle('on', running);
    if (c) {
      document.querySelectorAll('[data-north]').forEach((b) => b.classList.toggle('on', String(c.auto_north) === b.dataset.north));
      document.querySelectorAll('[data-altsrc]').forEach((b) => b.classList.toggle('on', String(c.alt_src) === b.dataset.altsrc));
      fillOnce('in-decl', c.declination);
      fillOnce('in-mount', c.compass_mount);
    }
    // the typed azimuth is meaningless while the compass drives it
    const northDriven = sensOn && sens.north;
    $('in-offset').disabled = northDriven;
    $('btn-offset').disabled = northDriven;
    if (northDriven && trk && num(trk.offset)) { $('in-offset').value = trk.offset.toFixed(1); $('in-offset').dataset.shown = ''; }
    $('in-offset').title = northDriven ? 'Set by the compass (choose "Typed azimuth" to enter it by hand)' : '';
  }

  function trackerStatus(trk) {
    if (!trk) return '';
    if (trk.tracking) return trk.flip ? 'tracking, flipped' : 'tracking';
    if (!trk.home) return 'no home set';
    return trk.mode === 'manual' ? 'manual' : 'waiting for GPS';
  }

  // ------------------------------------------------------------------------------ HUD loop (60 Hz)
  let hudTarget = { warnings: [] };
  const hudNow = {};
  let lastFrame = performance.now();
  const SMOOTH = ['pitch', 'roll', 'heading', 'speed', 'alt', 'vs'];

  function hudLoop(t) {
    requestAnimationFrame(hudLoop);
    // frame rate cap: the canvas is redrawn at most `hudfps` times a second (keeps a Pi 3B free for the video)
    if (t - lastFrame < 1000 / (prefs.hudfps || 60) - 4) return;
    const dt = Math.min(0.25, (t - lastFrame) / 1000);
    lastFrame = t;
    const k = reducedMotion ? 1 : 1 - Math.exp(-dt / 0.12);
    for (const key of Object.keys(hudTarget)) if (!SMOOTH.includes(key)) hudNow[key] = hudTarget[key];
    for (const key of SMOOTH) {
      const target = hudTarget[key];
      if (!num(target)) { hudNow[key] = null; continue; }
      if (!num(hudNow[key])) { hudNow[key] = target; continue; }
      if (key === 'heading') hudNow[key] = wrap360(hudNow[key] + wrap180(target - hudNow[key]) * k);
      else if (key === 'roll') hudNow[key] += wrap180(target - hudNow[key]) * k;
      else hudNow[key] += (target - hudNow[key]) * k;
    }
    hudNow.synthetic = !videoShowing();
    hudNow.reserve = null;
    const mp = $('pane-map');
    if (mp.classList.contains('pip-pane') && mp.offsetParent) {
      const a = mp.getBoundingClientRect(), b = $('hud').getBoundingClientRect();
      hudNow.reserve = { x: a.left - b.left, y: a.top - b.top };
    }
    hudNow.blink = reducedMotion ? true : Math.floor(t / 450) % 2 === 0;
    Hud.draw($('hud'), hudNow);
  }

  // ------------------------------------------------------------------------------ video
  let localStream = null;
  let videoRetry = null;

  function videoShowing() {
    if (prefs.video === 'server') return $('vid-stream').dataset.ok === '1';
    if (prefs.video === 'local') return !!localStream;
    return false;
  }

  function videoNote(text) {
    $('vid-status').classList.toggle('hidden', !text);
    set('vid-status', text || '');
  }

  function stopVideo() {
    clearTimeout(videoRetry);
    const img = $('vid-stream');
    img.dataset.ok = '';
    img.removeAttribute('src');
    if (localStream) { localStream.getTracks().forEach((tr) => tr.stop()); localStream = null; }
    $('vid-local').srcObject = null;
    $('vid-local').classList.add('hidden');
  }

  async function startVideo() {
    stopVideo();
    $('sel-video').value = prefs.video;
    $('row-localcam').classList.toggle('hidden', prefs.video !== 'local');
    if (prefs.video === 'off' || document.hidden) { videoNote(''); return; }

    if (prefs.video === 'server') {
      if (!cfg.video) { videoNote('No capture dongle configured on the ground station (start it with --video auto)'); return; }
      const img = $('vid-stream');
      videoNote('Starting video…');
      img.onload = () => { img.dataset.ok = '1'; videoNote(''); };
      img.onerror = () => {
        img.dataset.ok = '';
        img.removeAttribute('src');
        fetch('/api/video').then((r) => r.json()).then((v) => videoNote('Video: ' + (v.error || 'no picture yet') + ', retrying')).catch(() => videoNote('Video: ground station unreachable'));
        videoRetry = setTimeout(startVideo, 3000);
      };
      img.src = '/video.mjpg?t=' + Date.now();
      return;
    }

    // camera on this device (capture dongle plugged into the computer running the browser)
    if (!window.isSecureContext || !navigator.mediaDevices) { videoNote('A camera on this device needs https or http://localhost'); return; }
    try {
      const want = { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 60 } };
      if (prefs.localcam) want.deviceId = { exact: prefs.localcam };
      localStream = await navigator.mediaDevices.getUserMedia({ video: want, audio: false });
      const v = $('vid-local');
      v.srcObject = localStream;
      v.classList.remove('hidden');
      videoNote('');
      await listLocalCameras();
    } catch (err) {
      localStream = null;
      videoNote('Camera: ' + (err.message || err.name));
      await listLocalCameras();
    }
  }

  async function listLocalCameras() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    const devs = (await navigator.mediaDevices.enumerateDevices()).filter((x) => x.kind === 'videoinput');
    const sel = $('sel-localcam');
    sel.innerHTML = '';
    sel.add(new Option('Default camera', ''));
    devs.forEach((x, i) => sel.add(new Option(x.label || `Camera ${i + 1}`, x.deviceId)));
    sel.value = prefs.localcam || '';
  }

  async function refreshVideoInfo() {
    try {
      const v = await (await fetch('/api/video')).json();
      const devs = (v.devices || []).map((x) => `${x.path} (${x.name})`).join(', ') || 'none found';
      const line = v.enabled
        ? `Ground station: ${v.device || v.spec}, ${v.size} at ${v.fps} fps, ${v.running ? `${v.measured_fps} fps received` : 'idle'}${v.error ? `. Problem: ${v.error}` : ''}. Capture devices: ${devs}.`
        : `Video capture is off on the ground station. Capture devices it can see: ${devs}.`;
      set('video-info', line);
    } catch (_) { set('video-info', ''); }
  }

  document.addEventListener('visibilitychange', () => {
    // a hidden tab stops pulling frames, so the ground station can stop capturing
    if (document.hidden) stopVideo(); else startVideo();
  });

  // ------------------------------------------------------------------------------ weather
  let wxLoading = false;
  let wxLastTry = 0;

  function maybeAutoWeather() {
    if (!cfg.weather || wxLoading) return;
    const age = weather ? Date.now() / 1000 - weather.fetchedLocal : Infinity;
    const havePos = state && ((state.trk && state.trk.home) || (state.gps && state.gps.sats >= 4));
    if (havePos && age > 600 && Date.now() - wxLastTry > 60000) loadWeather(false);
  }

  async function loadWeather(force) {
    if (!cfg.weather || wxLoading) return;
    wxLoading = true;
    wxLastTry = Date.now();
    try {
      const r = await fetch('/api/weather' + (force ? '?refresh=1' : ''));
      const body = await r.json();
      if (!r.ok) {
        $('wx-error').classList.toggle('hidden', r.status === 400);
        $('wx-empty').classList.toggle('hidden', r.status !== 400 || !!weather);
        set('wx-error', 'Forecast unavailable: ' + (body.detail || r.statusText));
      } else {
        weather = body;
        weather.fetchedLocal = Date.now() / 1000;
        $('wx-error').classList.toggle('hidden', !body.stale);
        if (body.stale) set('wx-error', `No internet (${body.error}). Showing the forecast saved ${ago(body.age_s)}${body.other_place ? ' for another place' : ''}.`);
      }
    } catch (err) {
      $('wx-error').classList.remove('hidden');
      set('wx-error', 'Forecast unavailable: ' + err);
    } finally {
      wxLoading = false;
      renderWeather();
    }
  }

  function ago(s) {
    if (s < 90) return 'just now';
    if (s < 5400) return `${Math.round(s / 60)} min ago`;
    if (s < 172800) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} days ago`;
  }

  const WMO = {
    0: 'clear', 1: 'mainly clear', 2: 'partly cloudy', 3: 'overcast', 45: 'fog', 48: 'freezing fog',
    51: 'light drizzle', 53: 'drizzle', 55: 'heavy drizzle', 56: 'freezing drizzle', 57: 'freezing drizzle',
    61: 'light rain', 63: 'rain', 65: 'heavy rain', 66: 'freezing rain', 67: 'freezing rain',
    71: 'light snow', 73: 'snow', 75: 'heavy snow', 77: 'snow grains', 80: 'showers', 81: 'showers', 82: 'violent showers',
    85: 'snow showers', 86: 'snow showers', 95: 'thunderstorm', 96: 'thunderstorm, hail', 99: 'thunderstorm, hail',
  };
  const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  const compass = (deg) => COMPASS[Math.round(wrap360(deg) / 22.5) % 16];
  const windLevel = (kmh) => (!num(kmh) ? '' : kmh >= prefs.windmax ? 'warning' : kmh >= prefs.windwarn ? 'caution' : 'ok');

  function localTime(t) {
    if (!num(t)) return '–';
    const off = weather && num(weather.utc_offset) ? weather.utc_offset : 0;
    const dd = new Date((t + off) * 1000);
    return String(dd.getUTCHours()).padStart(2, '0') + ':' + String(dd.getUTCMinutes()).padStart(2, '0');
  }

  function windAt(hour, agl) {
    if (!hour || !hour.wind.length) return null;
    return hour.wind.reduce((best, r) => (Math.abs(r.agl - agl) < Math.abs(best.agl - agl) ? r : best), hour.wind[0]);
  }

  function arrowSvg(dir) {
    // meteorological direction = where the wind comes FROM; the arrow shows where it blows to
    return `<svg viewBox="-10 -10 20 20" style="transform:rotate(${wrap360(dir + 180)}deg)"><path d="M0 -9 L5 -1 L1.5 -1 L1.5 9 L-1.5 9 L-1.5 -1 L-5 -1 Z" fill="currentColor"/></svg>`;
  }

  function renderWeather() {
    $('tab-weather').classList.toggle('hidden', !cfg.weather);
    $('ro-wind').classList.toggle('hidden', !cfg.weather);
    if (!weather || !weather.hours || !weather.hours.length) return;
    $('wx-empty').classList.add('hidden');
    $('wx-body').classList.remove('hidden');
    const h0 = weather.hours[0];
    const w10 = windAt(h0, 10);

    set('wx-w10', w10 ? w10.speed.toFixed(0) : '–');
    $('wx-w10').className = 'big ' + windLevel(w10 && w10.speed) + '-t';
    set('wx-gust', num(h0.gust) ? `gusts ${h0.gust.toFixed(0)} km/h` : 'gusts –');
    $('wx-gust').className = windLevel(h0.gust) + '-t';
    set('wx-dir', w10 && num(w10.dir) ? `from ${compass(w10.dir)} (${Math.round(w10.dir)}°), 10 m` : '–');
    if (w10 && num(w10.dir)) $('wx-arrow').setAttribute('transform', `rotate(${wrap360(w10.dir + 180)})`);
    set('wx-sky', num(h0.code) ? (WMO[h0.code] || `code ${h0.code}`) + (num(h0.cloud) ? `, ${Math.round(h0.cloud)}% cloud` : '') : '–');
    set('wx-vis', num(h0.vis) ? (h0.vis >= 10000 ? `${(h0.vis / 1000).toFixed(0)} km` : `${(h0.vis / 1000).toFixed(1)} km`) : '–');
    $('wx-vis').className = num(h0.vis) && h0.vis < 3000 ? 'warning-t' : num(h0.vis) && h0.vis < 5000 ? 'caution-t' : '';
    set('wx-base', num(h0.cloud_base) ? `${Math.round(h0.cloud_base / 50) * 50} m` + (num(h0.cloud_low) ? `, low cloud ${Math.round(h0.cloud_low)}%` : '') : '–');
    set('wx-temp', num(h0.temp) ? `${h0.temp.toFixed(1)} °C` + (num(h0.dew) ? `, dew point ${h0.dew.toFixed(1)}` : '') : '–');
    set('wx-rain', num(h0.pop) ? `${Math.round(h0.pop)}%` + (num(h0.precip) && h0.precip > 0 ? `, ${h0.precip.toFixed(1)} mm/h` : '') : '–');
    set('wx-cape', num(h0.cape) ? `${Math.round(h0.cape)} J/kg` + (h0.cape > 1000 ? ', storms possible' : h0.cape > 300 ? ', thermals' : '') : '–');
    $('wx-cape').className = num(h0.cape) && h0.cape > 1000 ? 'caution-t' : '';
    set('wx-frz', num(h0.freezing) ? `${Math.round(h0.freezing)} m` : '–');
    set('wx-sun', `${localTime(weather.sun.sunrise)} / ${localTime(weather.sun.sunset)}`);

    // wind profile, highest first like a sounding
    const prof = $('wx-profile');
    const rows = h0.wind.slice().reverse();
    const top = Math.max(prefs.windmax * 1.25, ...rows.map((r) => r.speed));
    prof.innerHTML = '';
    for (const r of rows) {
      const lvl = windLevel(r.speed);
      const cells = [
        ['h', r.agl >= 1000 ? `${(r.agl / 1000).toFixed(1)} km` : `${Math.round(r.agl)} m`],
        ['a ' + lvl + '-t', num(r.dir) ? arrowSvg(r.dir) : ''],
        ['bar', `<i class="bg-${lvl}" style="width:${Math.min(100, (r.speed / top) * 100).toFixed(0)}%"></i>`],
        ['v ' + lvl + '-t', `${r.speed.toFixed(0)} km/h ${num(r.dir) ? compass(r.dir) : ''}`],
      ];
      for (const [cls, html] of cells) {
        const el = document.createElement('div');
        el.className = cls;
        el.innerHTML = html;
        if (cls === 'h') el.title = r.src === 'height' ? 'model height level' : `pressure level ${r.src}`;
        prof.appendChild(el);
      }
    }

    // hourly table
    const hours = weather.hours.slice(0, 12);
    const row = (label, fn) => `<tr><th>${label}</th>${hours.map((h) => `<td${fn(h)[1] ? ` class="${fn(h)[1]}"` : ''}>${fn(h)[0]}</td>`).join('')}</tr>`;
    $('wx-hours').innerHTML =
      row('', (h) => [localTime(h.t), '']) +
      row('Wind 10 m', (h) => { const x = windAt(h, 10); return x ? [x.speed.toFixed(0), windLevel(x.speed) + '-t'] : ['–', '']; }) +
      row('Gusts', (h) => (num(h.gust) ? [h.gust.toFixed(0), windLevel(h.gust) + '-t'] : ['–', ''])) +
      row('Wind 120 m', (h) => { const x = windAt(h, 120); return x ? [x.speed.toFixed(0), windLevel(x.speed) + '-t'] : ['–', '']; }) +
      row('Rain %', (h) => (num(h.pop) ? [Math.round(h.pop), h.pop >= 50 ? 'caution-t' : ''] : ['–', ''])) +
      row('Vis km', (h) => (num(h.vis) ? [(h.vis / 1000).toFixed(0), h.vis < 5000 ? 'caution-t' : ''] : ['–', ''])) +
      row('Low cloud %', (h) => (num(h.cloud_low) ? [Math.round(h.cloud_low), ''] : ['–', '']));

    const place = weather.place === 'home' ? 'the tracker position' : weather.place === 'drone' ? 'the drone position' : 'the requested position';
    set('wx-meta', `For ${place} (${weather.lat.toFixed(2)}, ${weather.lon.toFixed(2)}, ground ${Math.round(weather.elevation || 0)} m), updated ${ago(weather.age_s + (Date.now() / 1000 - weather.fetchedLocal))}.`);

    // bottom readout: wind at long-range cruising height
    const w120 = windAt(h0, 120);
    set('r-wind', w120 ? `${w120.speed.toFixed(0)} ${num(w120.dir) ? compass(w120.dir) : ''}` : '–');
    $('r-wind').className = windLevel(w120 && w120.speed) + '-t';
    set('r-gust', num(h0.gust) ? `gusts ${h0.gust.toFixed(0)} km/h` : '');
  }

  // ------------------------------------------------------------------------------ websocket
  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      state = msg.state;
      applyTrack(msg.track);
      appendConsole(msg.console);
      render();
    };
    ws.onclose = () => {
      ann('a-conn', 'no server', 'warning', 'The ground station program is not reachable');
      setTimeout(connect, 1500);
    };
    ws.onerror = () => ws.close();
  }

  function tickClock() {
    const d = new Date();
    set('clock', String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'));
  }

  // ------------------------------------------------------------------------------ start
  fetch('/api/config')
    .then((r) => r.json())
    .then((c) => {
      cfg = c;
      if (prefs.video === null || (prefs.video === 'server' && !cfg.video)) prefs.video = cfg.video ? 'server' : 'off';
      applyLayout();
      initMap();
      wireControls();
      $('btn-home-geo').disabled = !window.isSecureContext;
      if (cfg.read_only) document.querySelectorAll('[data-panel="tracker"] button, #cmdform button').forEach((b) => (b.disabled = true));
      renderWeather();
      startVideo();
      tickClock();
      setInterval(tickClock, 5000);
      requestAnimationFrame(hudLoop);
      connect();
    });
})();
