"use strict";

// ------------------------------------------------------------------ helpers
const $ = (sel, root = document) => root.querySelector(sel);

// Tiny DOM builder. Text is always added as text nodes: nothing read from an FC is parsed as HTML.
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}
const svg = (markup) => { const t = document.createElement("template"); t.innerHTML = markup.trim(); return t.content.firstChild; };

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (_) { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.status === 204 ? null : r.json();
}
const send = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

let osdTimer;
function osd(msg, kind = "") {
  const el = $("#osd");
  el.textContent = msg;
  el.className = kind;
  el.hidden = false;
  clearTimeout(osdTimer);
  osdTimer = setTimeout(() => { el.hidden = true; }, kind === "error" ? 9000 : 3500);
}

const led = (state, label) => h("span", { class: "led", "data-state": state, role: label ? "img" : null, "aria-label": label || null, "aria-hidden": label ? null : "true" });

const specsToText = (s) => Object.entries(s || {}).map(([k, v]) => (v ? `${k}: ${v}` : k)).join("\n");
function textToSpecs(text) {
  const out = {};
  for (const line of text.split("\n")) {
    const i = line.indexOf(":");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    else if (line.trim()) out[line.trim()] = "";
  }
  return out;
}

const DAY = 86400e3;
const parseDate = (s) => (s ? new Date(s) : null);
function ago(s) {
  const d = parseDate(s);
  if (!d) return "never plugged in";
  const dt = Date.now() - d.getTime();
  if (dt < 60e3) return "just now";
  if (dt < 3600e3) return `${Math.round(dt / 60e3)} min ago`;
  if (dt < DAY) return `${Math.round(dt / 3600e3)} h ago`;
  if (dt < 60 * DAY) return `${Math.round(dt / DAY)} days ago`;
  return d.toLocaleDateString();
}
const fmtDate = (s) => { const d = parseDate(s); return d ? d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—"; };
const fresh = (s) => { const d = parseDate(s); return d && Date.now() - d.getTime() < 30 * DAY; };

// Component types as silkscreen designators.
const REFS = {
  motor: "MOT", esc: "ESC", propeller: "PROP", camera: "CAM", vtx: "VTX", antenna: "ANT",
  receiver: "RX", gps: "GPS", compass: "MAG", optical_flow: "FLOW", gyro: "GYRO",
  accelerometer: "ACC", barometer: "BARO",
};
const ref = (type) => REFS[type] || type.slice(0, 4).toUpperCase();
const human = (type) => type.replace(/_/g, " ");

const QUAD = `<svg viewBox="0 0 64 64" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="2.5">
  <path d="M18 18 L46 46 M46 18 L18 46"/><circle cx="14" cy="14" r="10"/><circle cx="50" cy="14" r="10"/>
  <circle cx="14" cy="50" r="10"/><circle cx="50" cy="50" r="10"/><rect x="25" y="25" width="14" height="14"/></g></svg>`;

const main = () => $("#main");
function render(...nodes) {
  main().replaceChildren(...nodes.flat(Infinity).filter(Boolean));
  main().focus({ preventScroll: true });
}

// ---------------------------------------------------------------- hangar
async function viewHangar() {
  const drones = await api("/api/drones");
  document.title = "Fleet manager";
  if (!drones.length) {
    render(
      h("div", { class: "page-head" }, h("h1", {}, "Empty bench")),
      h("section", { class: "board empty-bench" },
        h("h2", {}, "Plug your first drone in"),
        h("p", { class: "dim" }, "The flight controller tells us its firmware, board, sensors, receiver and VTX. You fill in the rest: motors, props, camera, antenna, a photo."),
        h("ol", {},
          h("li", {}, h("b", {}, "Close Betaflight or INAV Configurator"), ", only one program can use the USB port."),
          h("li", {}, h("b", {}, "Connect the flight controller"), " with a USB cable."),
          h("li", {}, "For the ESC firmware too, ", h("b", {}, "take the props off and connect the battery"), ", then switch ESCs on."),
          h("li", {}, "Press ", h("b", {}, "Detect drone"), ".")),
        h("p", {}, h("button", { class: "btn ghost", onclick: createManual }, "Add a drone by hand"))));
    return;
  }
  const todo = drones.reduce((n, d) => n + (d.todo_count || 0), 0);
  render(
    h("div", { class: "page-head" },
      h("h1", {}, drones.length === 1 ? "1 drone on the bench" : `${drones.length} drones on the bench`),
      h("p", {}, todo ? `${todo} components still to fill in` : "Every component is filled in", "  ",
        h("button", { class: "btn ghost", onclick: createManual, style: "margin-left:12px" }, "Add by hand"))),
    h("div", { class: "hangar" }, drones.map(droneCard)));
}

async function createManual() {
  const name = prompt("Name of the drone");
  if (!name || !name.trim()) return;
  try {
    const r = await api("/api/drones", send("POST", { name }));
    location.hash = `#/drone/${r.id}`;
  } catch (e) { osd(e.message, "error"); }
}

function cardChips(det) {
  const chips = [];
  const s = det.settings || {};
  if (s.serialrx_provider) chips.push(["RX", s.serialrx_provider]);
  if (det.escs && det.escs.length) {
    const first = det.escs.find((e) => !e.error);
    chips.push(["ESC", first ? `${det.escs.length}× ${first.firmware} ${first.version || ""}`.trim() : `${det.escs.length}× ?`]);
  }
  if (det.vtx && det.vtx.freq_mhz) chips.push(["VTX", `${det.vtx.freq_mhz}`]);
  if ((det.sensor_flags || {}).gps) chips.push(["GPS", s.gps_provider || "yes"]);
  if ((det.sensors || {}).gyro) chips.push(["IMU", det.sensors.gyro]);
  return chips.slice(0, 4).map(([k, v]) => h("span", { class: "chip" }, h("b", {}, k), h("span", {}, v)));
}

function photoBox(d, cls = "card-photo") {
  const box = h("div", { class: cls }, d.photo ? null : svg(QUAD));
  if (d.photo) box.style.backgroundImage = `url("/photos/${encodeURIComponent(d.photo)}")`;
  return box;
}

function droneCard(d) {
  const det = d.detected || {};
  const state = !d.last_seen ? "stale" : fresh(d.last_seen) ? "ok" : "stale";
  const fw = [det.firmware, det.version].filter(Boolean).join(" ");
  return h("a", { class: "board drone-card", href: `#/drone/${d.id}` },
    photoBox(d),
    h("div", {},
      h("div", { class: "card-top" }, led(state, state === "ok" ? "Plugged in recently" : "Not plugged in recently"), h("h2", { class: "card-name" }, d.name)),
      h("div", { class: "card-fw" }, fw ? `${fw}${det.board_name || det.board_id ? " on " + (det.board_name || det.board_id) : ""}` : "Never read from a flight controller"),
      h("div", { class: "card-chips" }, cardChips(det)),
      h("div", { class: "card-foot" },
        h("span", {}, ago(d.last_seen)),
        d.todo_count
          ? h("span", { class: "todo" }, `${d.todo_count} of ${d.component_count} to fill in`)
          : h("span", {}, `${d.snapshot_count} config${d.snapshot_count === 1 ? "" : "s"} saved`))));
}

// ----------------------------------------------------------- drone sheet
async function viewDrone(id, { powerUp = false } = {}) {
  const d = await api(`/api/drones/${id}`);
  const det = d.detected || {};
  document.title = `${d.name} · Fleet manager`;

  const savedNote = h("span", { class: "saved-note", "aria-live": "polite" });
  const markSaved = () => { savedNote.textContent = `Saved ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`; };
  const saveDrone = async (fields) => {
    try { await api(`/api/drones/${id}`, send("PATCH", fields)); markSaved(); }
    catch (e) { osd(e.message, "error"); }
  };

  const name = h("input", { type: "text", class: "name-input", value: d.name, "aria-label": "Drone name",
    onchange: (ev) => saveDrone({ name: ev.target.value }) });
  const notes = h("textarea", { rows: 4, placeholder: "Crashes, repairs, what to try next…",
    onchange: (ev) => saveDrone({ notes: ev.target.value }) }, d.notes);
  const specs = h("textarea", { rows: 4, placeholder: "frame: 7 inch\nbattery: 6S2P Li-ion 4000 mAh\nweight: 780 g",
    onchange: (ev) => saveDrone({ specs: textToSpecs(ev.target.value) }) }, specsToText(d.specs));

  const fileInput = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", hidden: true, onchange: async (ev) => {
    const f = ev.target.files[0];
    if (!f) return;
    try {
      await api(`/api/drones/${id}/photo`, { method: "PUT", headers: { "Content-Type": f.type }, body: f });
      viewDrone(id);
    } catch (e) { osd(e.message, "error"); }
  } });

  const fw = [det.firmware, det.version].filter(Boolean).join(" ");
  const head = h("section", { class: "board sheet-head" + (powerUp ? " power-up" : "") },
    h("div", { class: "sheet-photo" },
      d.photo ? h("img", { src: `/photos/${encodeURIComponent(d.photo)}`, alt: `Photo of ${d.name}` }) : photoBox(d),
      h("div", { class: "actions" },
        h("button", { class: "btn ghost", onclick: () => fileInput.click() }, d.photo ? "Replace photo" : "Add a photo"), fileInput,
        d.photo ? h("button", { class: "btn ghost danger", onclick: async () => { await api(`/api/drones/${id}/photo`, { method: "DELETE" }); viewDrone(id); } }, "Remove") : null)),
    h("div", {},
      name,
      h("div", { class: "readout" },
        h("span", {}, led(fresh(d.last_seen) ? "ok" : "stale"), ago(d.last_seen)),
        fw ? h("span", {}, h("strong", {}, fw)) : h("span", {}, "never read from an FC"),
        det.board_name || det.board_id ? h("span", {}, "board ", h("strong", {}, det.board_name || det.board_id)) : null,
        det.craft_name ? h("span", {}, "craft name ", h("strong", {}, det.craft_name)) : null),
      h("div", { class: "sheet-fields" },
        h("label", { class: "field" }, "Notes", notes),
        h("label", { class: "field" }, "Specs, one “key: value” per line", specs)),
      h("div", { class: "sheet-tools" },
        savedNote,
        h("button", { class: "btn ghost danger", onclick: async () => {
          if (!confirm(`Delete ${d.name}, its components and its whole configuration history?`)) return;
          await api(`/api/drones/${id}`, { method: "DELETE" });
          osd(`${d.name} deleted`);
          location.hash = "#/";
        } }, "Delete drone"))));

  render(
    h("a", { class: "back", href: "#/" }, "‹ All drones"),
    head,
    h("div", { class: "columns" },
      bomPanel(id, d, markSaved),
      h("div", {}, fcPanel(d), historyPanel(d))));
}

function bomPanel(droneId, d, markSaved) {
  const todo = d.components.filter((c) => !c.model).length;
  const typeInput = h("input", { type: "text", placeholder: "Another part: frame, battery, buzzer…", "aria-label": "New component type" });
  const add = async () => {
    if (!typeInput.value.trim()) return typeInput.focus();
    try { await api(`/api/drones/${droneId}/components`, send("POST", { type: typeInput.value.trim().toLowerCase() })); viewDrone(droneId); }
    catch (e) { osd(e.message, "error"); }
  };
  typeInput.addEventListener("keydown", (ev) => { if (ev.key === "Enter") add(); });
  return h("section", { class: "board panel" },
    h("h2", {}, "Parts"),
    h("p", { class: "dim" }, todo ? `${todo} still to fill in. Green lines are what the flight controller reported.` : "Everything is filled in. Green lines are what the flight controller reported."),
    h("table", { class: "bom" }, h("tbody", {}, d.components.map((c) => bomRow(droneId, c, markSaved)))),
    h("div", { class: "add-row" }, typeInput, h("button", { class: "btn ghost", onclick: add }, "Add part")));
}

function bomRow(droneId, c, markSaved) {
  const save = async (fields) => {
    try { await api(`/api/components/${c.id}`, send("PATCH", fields)); markSaved(); stateLed.dataset.state = model.value.trim() ? "ok" : "todo"; }
    catch (e) { osd(e.message, "error"); }
  };
  const stateLed = led(c.model ? "ok" : "todo");
  const model = h("input", { type: "text", value: c.model, placeholder: "Model", "aria-label": `${human(c.type)} model`,
    onchange: (ev) => save({ model: ev.target.value }) });
  const specLines = Object.keys(c.specs || {}).length;
  const specs = h("textarea", { rows: Math.max(1, specLines), placeholder: "key: value", "aria-label": `${human(c.type)} specs`,
    onchange: (ev) => save({ specs: textToSpecs(ev.target.value) }) }, specsToText(c.specs));
  return h("tr", {},
    h("td", { class: "designator" }, h("span", { class: "ref", title: human(c.type) }, stateLed, ref(c.type)),
      h("div", { class: "dim", style: "font-size:12px;margin-top:4px" }, human(c.type))),
    h("td", { class: "model-cell" }, model, c.hint ? h("div", { class: "from-fc" }, led("ok"), c.hint) : null),
    h("td", { class: "specs-cell" }, specs),
    h("td", { class: "remove" }, h("button", { class: "icon-btn", title: `Remove ${human(c.type)}`, "aria-label": `Remove ${human(c.type)}`, onclick: async () => {
      await api(`/api/components/${c.id}`, { method: "DELETE" });
      viewDrone(droneId);
    } }, "×")));
}

function fcPanel(d) {
  const det = d.detected || {};
  if (!Object.keys(det).length) {
    return h("section", { class: "board panel" }, h("h2", {}, "Flight controller"),
      h("p", { class: "dim" }, "Not read yet. Plug this drone in and press Detect drone."));
  }
  const rows = [];
  const add = (k, v) => { if (v !== undefined && v !== null && v !== "") rows.push(h("dt", {}, k), h("dd", {}, String(v))); };
  add("Firmware", [det.firmware, det.version].filter(Boolean).join(" "));
  add("Board", [det.board_name, det.board_id && `(${det.board_id})`].filter(Boolean).join(" "));
  add("Build", [det.build_date, det.git_revision].filter(Boolean).join(" · "));
  add("MSP API", det.msp_api);
  for (const [k, v] of Object.entries(det.sensors || {})) add(k === "acc" ? "Accelerometer" : k === "baro" ? "Barometer" : k === "mag" ? "Compass" : k[0].toUpperCase() + k.slice(1), v);
  const s = det.settings || {};
  add("Receiver", s.serialrx_provider);
  add("Motor protocol", [s.motor_pwm_protocol, s.dshot_bidir === "ON" && "bidirectional"].filter(Boolean).join(", "));
  add("Motor poles", s.motor_poles);
  add("GPS", s.gps_provider);
  if (det.vtx) add("VTX", `${det.vtx.freq_mhz} MHz, power ${det.vtx.power}${det.vtx.pit_mode ? ", pit mode" : ""}`);
  add("Blackbox", s.blackbox_device);
  add("FC id", det.uid);

  const escs = det.escs || [];
  return h("section", { class: "board panel" },
    h("h2", {}, "Flight controller"),
    h("p", { class: "dim" }, `Read ${ago(d.last_seen)}${det.port ? ` on ${det.port}` : ""}.`),
    h("dl", { class: "kv" }, rows),
    escs.length ? [
      h("h2", { style: "margin-top:24px" }, "ESCs"),
      h("p", { class: "dim" }, `Read ${ago(det.escs_read_at)}.`),
      h("div", { class: "escs" }, escs.map((e) => h("div", { class: "esc" },
        h("div", { class: "esc-head" }, `M${e.index}`, led(e.error ? "error" : "ok", e.error ? "Not read" : "Read")),
        e.error ? h("div", { class: "esc-meta" }, e.error) : [
          h("div", { class: "esc-fw" }, `${e.firmware} ${e.version || ""}`),
          h("div", { class: "esc-meta" }, [e.mcu, e.layout].filter(Boolean).join(" · ")),
        ]))),
    ] : null,
    det.warnings && det.warnings.length ? h("ul", { class: "warnings" }, det.warnings.map((w) => h("li", {}, led("todo"), w))) : null);
}

function historyPanel(d) {
  const snaps = d.snapshots;
  if (!snaps.length) {
    return h("section", { class: "board panel" }, h("h2", {}, "Configuration history"),
      h("p", { class: "dim" }, "No configuration saved yet. Detect with the Config switch on to save the first one."));
  }
  const picked = [];
  const compare = h("button", { class: "btn", disabled: true, onclick: () => {
    const [a, b] = [...picked].sort((x, y) => x - y);
    location.hash = `#/diff/${a}/${b}`;
  } }, "Compare");
  const hint = h("span", { class: "dim", style: "font-size:14px" }, "Pick two vias to compare.");
  const vias = new Map();
  const toggle = (sid) => {
    const i = picked.indexOf(sid);
    if (i >= 0) picked.splice(i, 1);
    else { picked.push(sid); if (picked.length > 2) picked.shift(); }
    for (const [k, b] of vias) b.setAttribute("aria-pressed", picked.includes(k) ? "true" : "false");
    compare.disabled = picked.length !== 2;
    hint.textContent = picked.length === 2 ? "Ready." : picked.length === 1 ? "Pick one more." : "Pick two vias to compare.";
  };
  const items = snaps.map((s, i) => {
    const via = h("button", { class: "via", "aria-pressed": "false", "aria-label": `Select the configuration of ${fmtDate(s.taken_at)}`, onclick: () => toggle(s.id) });
    vias.set(s.id, via);
    return h("li", {}, via,
      h("div", { class: "snap-main" },
        h("span", { class: "snap-date" }, fmtDate(s.taken_at), i === 0 ? h("span", { class: "dim", style: "font-weight:400" }, "  current") : null),
        h("span", { class: "snap-meta" }, `${s.firmware || "?"} ${s.version || ""}`)),
      h("a", { href: `#/snapshot/${s.id}` }, "Open"));
  });
  if (snaps.length > 1) { toggle(snaps[1].id); toggle(snaps[0].id); }
  return h("section", { class: "board panel" },
    h("h2", {}, "Configuration history"),
    h("p", { class: "dim" }, snaps.length === 1 ? "One configuration saved. A new one is saved each time it changes." : `${snaps.length} configurations, newest first. A new one is saved each time it changes.`),
    h("ol", { class: "history" }, items),
    snaps.length > 1 ? h("div", { class: "history-bar" }, compare, hint) : null);
}

// -------------------------------------------------------- snapshot & diff
async function viewSnapshot(id) {
  const s = await api(`/api/snapshots/${id}`);
  render(
    h("a", { class: "back", href: `#/drone/${s.drone_id}` }, "‹ Back to the drone"),
    h("div", { class: "page-head" }, h("h1", {}, fmtDate(s.taken_at)), h("p", {}, `${s.firmware || ""} ${s.version || ""} · ${s.craft_name || ""}`)),
    h("section", { class: "board panel" }, h("h2", {}, "diff all"), h("pre", { class: "dump" }, s.diff_text)),
    s.status_text ? h("section", { class: "board panel" }, h("h2", {}, "status"), h("pre", { class: "dump" }, s.status_text)) : null);
}

async function viewDiff(a, b, full = false) {
  const d = await api(`/api/snapshots/diff?a=${a}&b=${b}&context=${full ? -1 : 3}`);
  const label = (s) => `#${s.id}  ${fmtDate(s.taken_at)}  ${s.firmware || ""} ${s.version || ""}`;
  const cell = (t, side) => (t === "chg" ? "chg" : t === "add" && side === "r" ? "add" : t === "del" && side === "l" ? "del" : "");
  const rows = d.rows.map((r) => r.t === "skip"
    ? h("tr", { class: "skip" }, h("td", { colspan: 4 }, `${r.n} unchanged line${r.n === 1 ? "" : "s"}`))
    : h("tr", {},
      h("td", { class: "ln" }, r.ll ?? ""), h("td", { class: r.l == null ? "" : cell(r.t, "l") }, r.l ?? ""),
      h("td", { class: "ln" }, r.rl ?? ""), h("td", { class: r.r == null ? "" : cell(r.t, "r") }, r.r ?? "")));
  render(
    h("a", { class: "back", href: `#/drone/${d.b.drone_id}` }, "‹ Back to the drone"),
    h("div", { class: "page-head" }, h("h1", {}, "What changed"),
      h("button", { class: "btn ghost", onclick: () => viewDiff(a, b, !full) }, full ? "Show changes only" : "Show whole files")),
    h("div", { class: "diff-stats" },
      d.identical ? h("span", {}, led("ok"), "Same configuration") : [
        h("span", {}, led("todo"), `${d.stats.chg} changed`),
        h("span", {}, led("ok"), `${d.stats.add} added`),
        h("span", {}, led("error"), `${d.stats.del} removed`),
      ]),
    h("section", { class: "board panel" },
      h("div", { class: "diff-head" }, h("div", {}, label(d.a)), h("div", {}, label(d.b))),
      h("div", { class: "diff-scroll" }, h("table", { class: "diff" },
        h("colgroup", {}, h("col", { class: "ln" }), h("col"), h("col", { class: "ln" }), h("col")),
        h("tbody", {}, rows)))));
}

// ------------------------------------------------------------------ router
async function route(opts = {}) {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  try {
    if (parts[0] === "drone" && parts[1]) await viewDrone(Number(parts[1]), opts);
    else if (parts[0] === "snapshot" && parts[1]) await viewSnapshot(Number(parts[1]));
    else if (parts[0] === "diff" && parts[2]) await viewDiff(Number(parts[1]), Number(parts[2]));
    else await viewHangar();
  } catch (e) {
    render(h("section", { class: "board panel" }, h("h2", {}, "Could not load this page"), h("p", {}, e.message), h("a", { href: "#/" }, "Back to all drones")));
  }
}
window.addEventListener("hashchange", () => route());

// ------------------------------------------------------- detection bar
async function loadPorts() {
  const sel = $("#port");
  const keep = sel.value;
  let ports = [];
  try { ports = await api("/api/ports"); } catch (_) { /* leave only "auto" */ }
  sel.replaceChildren(h("option", { value: "auto" }, ports.length === 1 ? `auto: ${ports[0].device}` : `auto (${ports.length} found)`),
    ports.map((p) => h("option", { value: p.device }, `${p.device}  ${p.description}`)));
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
}

$("#port").addEventListener("focus", loadPorts);
$("#scan-btn").addEventListener("click", async () => {
  const btn = $("#scan-btn");
  const light = btn.querySelector(".led");
  const label = btn.querySelector(".pad-label");
  const withEsc = $("#esc").checked;
  btn.disabled = true;
  light.dataset.state = "busy";
  label.textContent = "Reading…";
  osd(withEsc ? "Reading FC and ESCs. Props off." : $("#cli").checked ? "Reading the FC. It reboots at the end." : "Reading the FC.");
  try {
    const r = await api("/api/scan", send("POST", { port: $("#port").value, cli: $("#cli").checked, esc: withEsc }));
    light.dataset.state = r.warnings.length ? "todo" : "ok";
    const msg = r.created ? "New drone. Fill in its parts." : r.changed ? "Configuration changed, saved." : "Known drone, nothing changed.";
    osd([msg, ...r.warnings].join("  "), r.warnings.length ? "error" : "ok");
    const target = `#/drone/${r.drone_id}`;
    if (location.hash !== target) history.pushState(null, "", target);
    await route({ powerUp: true });
  } catch (e) {
    light.dataset.state = "error";
    osd(e.message, "error");
  } finally {
    btn.disabled = false;
    label.textContent = "Detect drone";
  }
});

(async () => {
  try {
    const info = await api("/api/info");
    if (info.simulated) $(".connector .silk").textContent = "J1 sim";
  } catch (_) { /* older server */ }
  loadPorts();
  route();
})();
