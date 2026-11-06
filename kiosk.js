/* Mode kiosque (écran tactile de Raspberry Pi, sans molette ni clavier).
   Activé en ouvrant la page avec ?kiosk (mémorisé dans ce navigateur), désactivé avec ?kiosk=0.
   Le tactile de ces écrans se comporte comme une souris : glisser le doigt ne fait pas défiler la page et le
   pointeur bouge de quelques pixels entre l'appui et le relâchement, ce qui fait rater les petites cibles.
   Ici : glisser pour défiler (hors carte), deux gros boutons ▲ ▼, et un appui à peine déplacé compte comme un clic. */
(function () {
  "use strict";
  var KEY = "fpv-kiosk";
  function get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function set(v) { try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch (e) {} }

  var m = /[?&]kiosk(?:=([^&#]*))?/.exec(location.search);
  if (m) set(m[1] === "0" || m[1] === "off" ? null : "1");
  if (get() !== "1") return;

  var root = document.documentElement;
  root.classList.add("kiosk");
  var css = document.createElement("style");
  css.textContent =
    ".kiosk,.kiosk body{-webkit-user-select:none;user-select:none}" +
    ".kiosk input,.kiosk textarea{-webkit-user-select:text;user-select:text}" +
    ".kiosk #gps{display:none}" +
    ".kb{position:fixed;right:.6rem;z-index:2000;width:3.5rem;height:3.5rem;border-radius:50%;padding:0;" +
    "border:1px solid var(--line,#ccc);background:var(--card2,#eee);color:var(--fg,#111);font:inherit;font-size:1.5rem;" +
    "line-height:1;opacity:.93;box-shadow:0 2px 10px #0004;cursor:pointer}" +
    ".kb:active{background:var(--ac-soft,#ddd)}" +
    ".kb-up{bottom:5rem}.kb-down{bottom:1rem}";
  document.head.appendChild(css);

  function scrollPage(dir) {
    window.scrollBy({ top: dir * Math.round(window.innerHeight * 0.8), behavior: "smooth" });
  }
  function button(cls, label, text, dir) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "kb " + cls; b.textContent = text;
    b.setAttribute("aria-label", label); b.title = label;
    b.addEventListener("click", function () { scrollPage(dir); });
    document.body.appendChild(b);
  }
  button("kb-up", "Défiler vers le haut", "▲", -1);
  button("kb-down", "Défiler vers le bas", "▼", 1);

  /* Glisser pour défiler, appui à peine déplacé = clic */
  var DRAG = 14;          /* pixels avant de considérer un glissement */
  var TAP = 18;           /* pixels de tolérance entre appui et relâchement pour un clic */
  var st = null, moved = false;
  var NOSCROLL = ".leaflet-container,input,select,textarea,.kb";
  var CLICKABLE = "a,button,summary,label,select,[role=button]";

  document.addEventListener("mousedown", function (e) {
    if (e.button !== 0) return;
    moved = false;
    st = { x: e.clientX, y: e.clientY, t: e.target, sx: window.pageXOffset, sy: window.pageYOffset,
           scroll: !(e.target.closest && e.target.closest(NOSCROLL)) };
  }, true);

  document.addEventListener("mousemove", function (e) {
    if (!st || !st.scroll) return;
    var dx = e.clientX - st.x, dy = e.clientY - st.y;
    if (!moved && Math.abs(dx) + Math.abs(dy) > DRAG) moved = true;
    if (moved) { window.scrollTo(st.sx - dx, st.sy - dy); e.preventDefault(); }
  }, true);

  document.addEventListener("mouseup", function (e) {
    var s = st; st = null;
    if (!s) return;
    if (moved) { setTimeout(function () { moved = false; }, 60); return; }
    var dist = Math.abs(e.clientX - s.x) + Math.abs(e.clientY - s.y);
    if (dist > TAP || e.target === s.t || !s.t.closest || !document.contains(s.t)) return;
    /* Le pointeur a bougé hors de la cible entre l'appui et le relâchement : le navigateur ne clique pas */
    var c = s.t.closest(CLICKABLE);
    if (c && !c.contains(e.target)) c.click();
  }, true);

  /* Un glissement ne doit pas cliquer ce qu'il survole au relâchement */
  document.addEventListener("click", function (e) {
    if (moved) { e.preventDefault(); e.stopPropagation(); }
  }, true);
})();
