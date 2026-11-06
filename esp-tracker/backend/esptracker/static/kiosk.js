/* Kiosk mode, for the touch screen of a Raspberry Pi running the ground station full screen (same convention as
   the kiosk.js of the FPVTools pages): open the page once with ?kiosk (remembered by this browser), ?kiosk=0 turns
   it off. Loaded in <head> so that the class is there before anything is drawn.

   The resistive touch screens of these Pis behave like a mouse: dragging a finger does not scroll, and the pointer
   moves a few pixels between press and release, which makes small targets miss. Here: bigger targets, drag to
   scroll the side panel, a press released a few pixels off its target still clicks it, no full-screen button
   (the kiosk already is), and a lower HUD frame rate by default (the Pi 3B also decodes the video). */
(function () {
  'use strict';
  var KEY = 'esptracker-kiosk';
  function get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function set(v) { try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch (e) { /* private mode */ } }

  var m = /[?&]kiosk(?:=([^&#]*))?/.exec(location.search);
  if (m) set(m[1] === '0' || m[1] === 'off' ? null : '1');
  var on = get() === '1' || (m && m[1] !== '0' && m[1] !== 'off');
  window.ESPTRACKER_KIOSK = !!on;
  if (!on) return;
  document.documentElement.classList.add('kiosk');

  /* Drag to scroll (side panel and console only), a press barely moved = a click */
  var DRAG = 14;  /* pixels before a press becomes a drag */
  var TAP = 18;   /* tolerance between press and release for a click */
  var SCROLLERS = '#drawer, #console, .wx-hours-wrap';
  var NODRAG = 'input, select, textarea, .leaflet-container';
  var CLICKABLE = 'a, button, summary, label, select, [role=button]';
  var st = null, moved = false;

  document.addEventListener('mousedown', function (e) {
    if (e.button !== 0) return;
    moved = false;
    var sc = e.target.closest && !e.target.closest(NODRAG) ? e.target.closest(SCROLLERS) : null;
    st = { x: e.clientX, y: e.clientY, t: e.target, sc: sc, top: sc ? sc.scrollTop : 0, left: sc ? sc.scrollLeft : 0 };
  }, true);

  document.addEventListener('mousemove', function (e) {
    if (!st || !st.sc) return;
    var dx = e.clientX - st.x, dy = e.clientY - st.y;
    if (!moved && Math.abs(dx) + Math.abs(dy) > DRAG) moved = true;
    if (moved) {
      st.sc.scrollTop = st.top - dy;
      st.sc.scrollLeft = st.left - dx;
      e.preventDefault();
    }
  }, true);

  document.addEventListener('mouseup', function (e) {
    var s = st; st = null;
    if (!s) return;
    if (moved) { setTimeout(function () { moved = false; }, 60); return; }
    var dist = Math.abs(e.clientX - s.x) + Math.abs(e.clientY - s.y);
    if (dist > TAP || e.target === s.t || !s.t.closest || !document.contains(s.t)) return;
    /* the pointer slid off the target between press and release: the browser would not click */
    var c = s.t.closest(CLICKABLE);
    if (c && !c.contains(e.target)) c.click();
  }, true);

  /* a drag must not click what it ends on */
  document.addEventListener('click', function (e) {
    if (moved) { e.preventDefault(); e.stopPropagation(); }
  }, true);
})();
