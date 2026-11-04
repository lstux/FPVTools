// Head-up display drawn on a canvas over the video (or over a synthetic horizon when there is none).
// Pure drawing: app.js computes the values, Hud.draw() paints one frame.
//
// d = { pitch, roll, heading, speed, alt, altLabel, vs, homeBrg, homeDist, timeS, mode, armed,
//       volts, cellV, mah, lq, rssi, sats, warnings: [{text, level}], synthetic, cellLevel, lqLevel }
// Any value may be null (not received / stale): that part of the display is left out or dashed.
(function () {
  'use strict';

  const C = {
    sym: '#3ddc84',      // normal symbology
    own: '#ffd84a',      // own aircraft
    nav: '#ff5ad1',      // home / navigation
    tgt: '#4fd6ff',      // selected / target
    caution: '#ffb020',
    warning: '#ff4d4d',
    text: '#e4ebf2',
    halo: 'rgba(0,0,0,0.65)',
  };
  const LEVEL = { ok: C.sym, caution: C.caution, warning: C.warning, info: C.tgt };
  const D2R = Math.PI / 180;
  const num = (v) => typeof v === 'number' && Number.isFinite(v);
  const wrap360 = (a) => ((a % 360) + 360) % 360;
  const wrap180 = (a) => ((((a + 180) % 360) + 360) % 360) - 180;

  let g, w, h, u, cx, cy, fontNum, fontUi;

  function setFont(sizeU, bold, mono) {
    const px = Math.max(9, sizeU * u);
    g.font = `${bold ? 700 : 400} ${px.toFixed(1)}px ${mono === false ? fontUi : fontNum}`;
    return px;
  }

  function stroke(color, width, path) {
    g.lineJoin = 'round';
    g.lineCap = 'round';
    g.beginPath();
    path();
    g.strokeStyle = C.halo;
    g.lineWidth = width + 2.5;
    g.stroke();
    g.strokeStyle = color;
    g.lineWidth = width;
    g.stroke();
  }

  function text(str, x, y, color, align, base) {
    g.textAlign = align || 'center';
    g.textBaseline = base || 'middle';
    g.lineJoin = 'round';
    g.strokeStyle = C.halo;
    g.lineWidth = 3;
    g.strokeText(str, x, y);
    g.fillStyle = color;
    g.fillText(str, x, y);
  }

  // --------------------------------------------------------------------------------- horizon
  function synthetic(d) {
    const diag = Math.hypot(w, h);
    const ppd = h / 70;
    g.save();
    g.translate(cx, cy);
    g.rotate(-(d.roll || 0) * D2R);
    g.translate(0, (d.pitch || 0) * ppd);
    let gr = g.createLinearGradient(0, -diag, 0, 0);
    gr.addColorStop(0, '#0b223a');
    gr.addColorStop(1, '#3a6a98');
    g.fillStyle = gr;
    g.fillRect(-diag, -diag * 2, diag * 2, diag * 2);
    gr = g.createLinearGradient(0, 0, 0, diag);
    gr.addColorStop(0, '#5b4229');
    gr.addColorStop(1, '#22180f');
    g.fillStyle = gr;
    g.fillRect(-diag, 0, diag * 2, diag * 2);
    g.restore();
  }

  function ladder(d, compact) {
    const ppd = h / 70;
    const pitch = num(d.pitch) ? d.pitch : 0;
    const roll = num(d.roll) ? d.roll : 0;
    const color = num(d.pitch) ? C.sym : 'rgba(228,235,242,0.35)';
    g.save();
    // clip the ladder to the middle of the picture so it never runs into the tapes
    g.beginPath();
    g.rect(cx - w * 0.3, cy - h * 0.32, w * 0.6, h * 0.64);
    g.clip();
    g.translate(cx, cy);
    g.rotate(-roll * D2R);
    g.translate(0, pitch * ppd);

    // horizon, with a gap around the aircraft symbol
    const hl = w * 0.6;
    stroke(color, 1.6, () => { g.moveTo(-hl, 0); g.lineTo(-7 * u, 0); g.moveTo(7 * u, 0); g.lineTo(hl, 0); });
    if (!compact) setFont(2.6, false);
    for (let deg = -80; deg <= 80; deg += 5) {
      if (deg === 0) continue;
      const rel = deg - pitch;
      if (Math.abs(rel) > 32) continue;
      const y = -deg * ppd;
      const major = deg % 10 === 0;
      const half = (major ? 8 : 4) * u;
      const gap = 3 * u;
      const tick = (deg > 0 ? 1 : -1) * 1.4 * u;
      if (deg < 0) g.setLineDash([1.2 * u, 0.9 * u]);
      stroke(color, 1.3, () => {
        g.moveTo(-gap - half, y + (major ? tick : 0)); g.lineTo(-gap - half, y); g.lineTo(-gap, y);
        g.moveTo(gap, y); g.lineTo(gap + half, y); g.lineTo(gap + half, y + (major ? tick : 0));
      });
      g.setLineDash([]);
      if (major && !compact) {
        text(String(Math.abs(deg)), -gap - half - 2.6 * u, y, color);
        text(String(Math.abs(deg)), gap + half + 2.6 * u, y, color);
      }
    }
    g.restore();
  }

  function rollScale(d) {
    const R = Math.min(w * 0.5, h) * 0.34;
    const roll = num(d.roll) ? d.roll : 0;
    g.save();
    g.translate(cx, cy);
    stroke(C.sym, 1.3, () => { g.arc(0, 0, R, (-90 - 60) * D2R, (-90 + 60) * D2R); });
    for (const a of [-60, -45, -30, -20, -10, 10, 20, 30, 45, 60]) {
      const len = (Math.abs(a) === 30 || Math.abs(a) === 60 ? 2.4 : 1.4) * u;
      const s = Math.sin(a * D2R), c = -Math.cos(a * D2R);
      stroke(C.sym, 1.3, () => { g.moveTo(s * R, c * R); g.lineTo(s * (R + len), c * (R + len)); });
    }
    // fixed index at the top
    stroke(C.own, 1.5, () => { g.moveTo(0, -R - 0.2 * u); g.lineTo(-1.3 * u, -R - 2.4 * u); g.lineTo(1.3 * u, -R - 2.4 * u); g.closePath(); });
    // sky pointer, turns with the horizon
    g.rotate(-roll * D2R);
    if (num(d.roll)) stroke(C.sym, 1.5, () => { g.moveTo(0, -R + 0.3 * u); g.lineTo(-1.3 * u, -R + 2.5 * u); g.lineTo(1.3 * u, -R + 2.5 * u); g.closePath(); });
    g.restore();
  }

  function aircraft() {
    stroke(C.own, 2.6, () => {
      g.moveTo(cx - 15 * u, cy); g.lineTo(cx - 5.5 * u, cy); g.lineTo(cx - 5.5 * u, cy + 2.6 * u);
      g.moveTo(cx + 15 * u, cy); g.lineTo(cx + 5.5 * u, cy); g.lineTo(cx + 5.5 * u, cy + 2.6 * u);
      g.rect(cx - 0.6 * u, cy - 0.6 * u, 1.2 * u, 1.2 * u);
    });
  }

  // --------------------------------------------------------------------------------- tapes
  function headingTape(d) {
    const W = Math.min(w * 0.46, 70 * u);
    const x0 = cx - W / 2;
    const y = 4.2 * u;
    const span = 60;
    const ppd = W / span;
    const hdg = d.heading;
    g.save();
    g.beginPath();
    g.rect(x0 - 2 * u, 0, W + 4 * u, 12 * u);
    g.clip();
    setFont(2.5, true);
    if (num(hdg)) {
      const first = Math.ceil((hdg - span / 2) / 5) * 5;
      for (let a = first; a <= hdg + span / 2; a += 5) {
        const x = cx + (a - hdg) * ppd;
        const major = a % 10 === 0;
        stroke(C.sym, 1.3, () => { g.moveTo(x, y + 3.2 * u); g.lineTo(x, y + (major ? 1.2 : 2.2) * u); });
        if (a % 30 === 0) {
          const v = wrap360(a);
          const label = { 0: 'N', 90: 'E', 180: 'S', 270: 'W' }[v] || String(v / 10);
          text(label, x, y - 0.3 * u, C.sym);
        }
      }
      // home bearing caret
      if (num(d.homeBrg)) {
        let rel = wrap180(d.homeBrg - hdg);
        const clipped = Math.abs(rel) > span / 2 - 2;
        rel = Math.max(-span / 2 + 2, Math.min(span / 2 - 2, rel));
        const x = cx + rel * ppd;
        stroke(C.nav, 2, () => {
          if (clipped) { const s = Math.sign(rel); g.moveTo(x - s * 1.2 * u, y + 0.4 * u); g.lineTo(x + s * 0.4 * u, y + 1.9 * u); g.lineTo(x - s * 1.2 * u, y + 3.4 * u); }
          else { g.moveTo(x - 1.1 * u, y + 0.3 * u); g.lineTo(x, y + 2.2 * u); g.lineTo(x + 1.1 * u, y + 0.3 * u); }
        });
      }
    }
    g.restore();
    // current heading box
    const bw = 8 * u, bh = 4.2 * u, by = y + 3.6 * u;
    g.fillStyle = 'rgba(0,0,0,0.6)';
    g.fillRect(cx - bw / 2, by, bw, bh);
    stroke(C.sym, 1.3, () => { g.rect(cx - bw / 2, by, bw, bh); });
    setFont(3.0, true);
    text(num(hdg) ? String(Math.round(wrap360(hdg)) % 360).padStart(3, '0') : '---', cx, by + bh / 2 + 0.1 * u, C.sym);
  }

  function verticalTape(opts) {
    // opts: x (inner edge), side (-1 = left tape, +1 = right tape), value, span, minor, labelEvery, title, sub
    const H = opts.H;
    const ppv = H / opts.span;
    const dir = opts.side;
    const xIn = opts.x;
    const xOut = xIn + dir * 6 * u;
    g.save();
    g.beginPath();
    g.rect(Math.min(xIn, xOut) - 8 * u, cy - H, 16 * u + 6 * u, 2 * H);
    g.clip();
    stroke('rgba(61,220,132,0.55)', 1, () => { g.moveTo(xIn, cy - H); g.lineTo(xIn, cy + H); });
    setFont(2.5, false);
    if (num(opts.value)) {
      const v = opts.value;
      const first = Math.ceil((v - opts.span) / opts.minor) * opts.minor;
      for (let t = first; t <= v + opts.span; t += opts.minor) {
        if (opts.floor !== undefined && t < opts.floor) continue;
        const y = cy - (t - v) * ppv;
        const major = Math.round(t / opts.labelEvery) * opts.labelEvery === t;
        stroke(C.sym, 1.2, () => { g.moveTo(xIn, y); g.lineTo(xIn + dir * (major ? 1.8 : 1) * u, y); });
        if (major && Math.abs(y - cy) < H - 1.4 * u && Math.abs(y - cy) > 3.2 * u) text(String(t), xIn + dir * 3.2 * u, y, C.sym, dir < 0 ? 'right' : 'left');
      }
    }
    g.restore();
    // value box with a pointer towards the centre
    const bw = 9.5 * u, bh = 4.4 * u;
    const bx = dir < 0 ? xIn - bw - 1.2 * u : xIn + 1.2 * u;
    g.fillStyle = 'rgba(8,11,15,0.9)';
    g.fillRect(bx, cy - bh / 2, bw, bh);
    stroke(opts.color || C.sym, 1.4, () => {
      if (dir < 0) { g.moveTo(bx, cy - bh / 2); g.lineTo(bx + bw, cy - bh / 2); g.lineTo(bx + bw + 1.2 * u, cy); g.lineTo(bx + bw, cy + bh / 2); g.lineTo(bx, cy + bh / 2); g.closePath(); }
      else { g.moveTo(bx + bw, cy - bh / 2); g.lineTo(bx, cy - bh / 2); g.lineTo(bx - 1.2 * u, cy); g.lineTo(bx, cy + bh / 2); g.lineTo(bx + bw, cy + bh / 2); g.closePath(); }
    });
    setFont(3.1, true);
    text(num(opts.value) ? String(Math.round(opts.value)) : '---', bx + bw / 2, cy + 0.1 * u, opts.color || C.sym);
    setFont(2.2, false, false);
    text(opts.title, xIn + dir * 3 * u, cy - H - 2.2 * u, C.text);
    if (opts.sub) text(opts.sub, xIn + dir * 3 * u, cy + H + 2.4 * u, opts.subColor || C.sym);
  }

  function vario(d, x, H) {
    const max = 10;
    const vs = num(d.vs) ? Math.max(-max, Math.min(max, d.vs)) : null;
    stroke('rgba(61,220,132,0.55)', 1, () => {
      for (const t of [-10, -5, 0, 5, 10]) { const y = cy - (t / max) * H; g.moveTo(x, y); g.lineTo(x + (t === 0 ? 1.6 : 0.9) * u, y); }
    });
    if (vs !== null && Math.abs(vs) > 0.05) {
      const y = cy - (vs / max) * H;
      g.fillStyle = C.sym;
      g.fillRect(x - 0.5 * u, Math.min(cy, y), 1 * u, Math.abs(y - cy));
    }
  }

  // --------------------------------------------------------------------------------- home + info
  function homeArrow(d) {
    if (!num(d.homeBrg) || !num(d.heading)) return;
    const x = cx, y = 16 * u;
    const rel = wrap180(d.homeBrg - d.heading);
    g.save();
    g.translate(x, y);
    g.rotate(rel * D2R);
    stroke(C.nav, 2, () => {
      g.moveTo(0, -2.8 * u); g.lineTo(1.9 * u, 1.6 * u); g.lineTo(0, 0.6 * u); g.lineTo(-1.9 * u, 1.6 * u); g.closePath();
    });
    g.restore();
    setFont(2.6, true);
    if (num(d.homeDist)) text(fmtDist(d.homeDist), x + 4 * u, y, C.nav, 'left');
  }

  function fmtDist(m) {
    return m >= 1000 ? (m / 1000).toFixed(m >= 10000 ? 1 : 2) + ' km' : Math.round(m) + ' m';
  }

  function fmtTime(s) {
    s = Math.max(0, Math.floor(s || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  function corners(d) {
    const pad = 3 * u;
    const lh = 3.6 * u;
    setFont(2.8, true);
    // bottom left: battery and time
    let y = h - pad;
    if (num(d.mah)) { text(Math.round(d.mah) + ' mAh', pad, y, C.sym, 'left', 'alphabetic'); y -= lh; }
    if (num(d.volts)) {
      const s = d.volts.toFixed(1) + ' V' + (num(d.cellV) ? '  ' + d.cellV.toFixed(2) + ' V/cell' : '');
      text(s, pad, y, LEVEL[d.cellLevel] || C.sym, 'left', 'alphabetic');
      y -= lh;
    }
    const modeTxt = (d.mode || '') + (d.armed === true ? '  ' + fmtTime(d.timeS) : d.armed === false ? '  disarmed' : '');
    if (modeTxt.trim()) text(modeTxt.trim(), pad, y, d.armed === false ? C.text : C.sym, 'left', 'alphabetic');

    // top right: link and GPS
    y = pad + 2.2 * u;
    if (num(d.lq)) {
      text('LQ ' + d.lq + (num(d.rssi) ? '  ' + d.rssi + ' dBm' : ''), w - pad, y, LEVEL[d.lqLevel] || C.sym, 'right', 'alphabetic');
      y += lh;
    }
    if (num(d.sats)) text(d.sats + ' sats', w - pad, y, d.sats >= 6 ? C.sym : C.caution, 'right', 'alphabetic');
  }

  function warnings(d) {
    const list = d.warnings || [];
    if (!list.length) return;
    setFont(3.0, true);
    let y = cy + h * 0.17;
    const blinkOff = d.blink === false;
    for (const wn of list.slice(0, 3)) {
      const color = wn.level === 'warning' ? C.warning : C.caution;
      const tw = g.measureText(wn.text).width + 3 * u;
      const bh = 4.6 * u;
      g.fillStyle = wn.level === 'warning' ? 'rgba(90,0,0,0.72)' : 'rgba(0,0,0,0.65)';
      g.fillRect(cx - tw / 2, y - bh / 2, tw, bh);
      if (!(wn.level === 'warning' && blinkOff)) stroke(color, 1.6, () => { g.rect(cx - tw / 2, y - bh / 2, tw, bh); });
      text(wn.text, cx, y + 0.1 * u, color);
      y += bh + 1.2 * u;
    }
  }

  // --------------------------------------------------------------------------------- compact
  function compactInfo(d) {
    const pad = 2.5 * u;
    setFont(5, true);
    text(num(d.speed) ? String(Math.round(d.speed)) : '--', pad, pad, C.sym, 'left', 'top');
    text(num(d.alt) ? String(Math.round(d.alt)) : '--', w - pad, pad, C.sym, 'right', 'top');
    text(num(d.heading) ? String(Math.round(wrap360(d.heading)) % 360).padStart(3, '0') : '---', cx, pad, C.sym, 'center', 'top');
    const top = d.warnings && d.warnings[0];
    if (top) text(top.text, cx, h - pad, top.level === 'warning' ? C.warning : C.caution, 'center', 'alphabetic');
  }

  // --------------------------------------------------------------------------------- entry
  function draw(canvas, d) {
    const dpr = window.devicePixelRatio || 1;
    const cw = canvas.clientWidth, ch = canvas.clientHeight;
    if (!cw || !ch) return;
    if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
      canvas.width = Math.round(cw * dpr);
      canvas.height = Math.round(ch * dpr);
    }
    g = canvas.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, cw, ch);
    w = cw; h = ch;
    cx = w / 2; cy = h / 2;
    const compact = w < 420;
    u = compact ? Math.min(w / 100, h / 70) : Math.min(w / 170, h / 100);
    const fam = getComputedStyle(canvas);
    fontNum = fam.getPropertyValue('--num') || 'monospace';
    fontUi = fam.getPropertyValue('--ui') || 'sans-serif';

    if (d.synthetic) synthetic(d);
    ladder(d, compact);
    aircraft();
    if (compact) { compactInfo(d); return; }
    rollScale(d);
    headingTape(d);
    homeArrow(d);
    // the tapes keep clear of the map inset (bottom right) when the video is the main view:
    // slide both inwards (symmetrically) rather than letting the inset hide the altitude
    let H = h * 0.27;
    let right = w * 0.83;
    const r = d.reserve;
    if (r && r.x < right + 16 * u && r.y < cy + H + 5 * u) {
      const fit = r.y - cy - 5 * u;
      if (fit >= h * 0.16) H = fit;
      else right = Math.max(w * 0.62, r.x - 16 * u);
    }
    const left = w - right;
    verticalTape({ x: left, side: -1, value: d.speed, span: 30, minor: 5, labelEvery: 10, title: 'GS km/h', floor: 0, H });
    verticalTape({
      x: right, side: 1, value: d.alt, span: 50, minor: 10, labelEvery: 20, title: d.altLabel || 'ALT m',
      sub: num(d.vs) ? (d.vs >= 0 ? '+' : '') + d.vs.toFixed(1) + ' m/s' : null, H,
    });
    vario(d, right - 2.4 * u, H);
    corners(d);
    warnings(d);
  }

  window.Hud = { draw, fmtDist, fmtTime, wrap360, wrap180 };
})();
