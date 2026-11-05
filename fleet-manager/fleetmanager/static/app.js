"use strict";

// ----------------------------------------------------------------- helpers
const $ = (sel, root = document) => root.querySelector(sel);

// Tiny DOM builder. Text is always added as text nodes (FC output is never parsed as HTML).
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (_) { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.status === 204 ? null : r.json();
}
const send = (method, body) => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

let toastTimer;
function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = error ? "error" : "";
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, error ? 8000 : 4000);
}

const specsToText = (s) => Object.entries(s || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
function textToSpecs(text) {
  const out = {};
  for (const line of text.split("\n")) {
    const i = line.indexOf(":");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    else if (line.trim()) out[line.trim()] = "";
  }
  return out;
}
const fmtDate = (s) => (s ? s.replace("T", " ").replace("Z", " UTC") : "never");
const main = () => $("#main");

// ------------------------------------------------------------------ views
async function viewList() {
  const drones = await api("/api/drones");
  main().replaceChildren(
    drones.length
      ? h("div", { class: "grid" }, drones.map(droneCard))
      : h("section", {}, h("p", {}, "No drone yet. Plug a flight controller in (Betaflight/INAV Configurator closed) and click “Detect drone”.")),
  );
}

function droneCard(d) {
  const det = d.detected || {};
  const pic = h("div", { class: "pic" }, d.photo ? null : "no photo");
  if (d.photo) pic.style.backgroundImage = `url("/photos/${encodeURIComponent(d.photo)}")`;
  return h("a", { class: "card", href: `#/drone/${d.id}` }, pic,
    h("div", { class: "body" },
      h("h3", {}, d.name),
      h("div", { class: "muted" }, [det.firmware, det.version].filter(Boolean).join(" "), det.board_id ? ` · ${det.board_id}` : ""),
      h("div", { class: "muted" }, `last seen: ${fmtDate(d.last_seen)} · ${d.snapshot_count} snapshot(s)`)));
}

async function viewDrone(id) {
  const d = await api(`/api/drones/${id}`);
  const det = d.detected || {};

  const name = h("input", { type: "text", value: d.name });
  const notes = h("textarea", { rows: 3 }, d.notes);
  const specs = h("textarea", { rows: 4, placeholder: "frame: 5 inch\nbattery: 6S 1300 mAh\nweight: 620 g" }, specsToText(d.specs));
  const saveDrone = h("button", { class: "primary", onclick: async () => {
    try {
      await api(`/api/drones/${id}`, send("PATCH", { name: name.value, notes: notes.value, specs: textToSpecs(specs.value) }));
      toast("Saved");
    } catch (e) { toast(e.message, true); }
  } }, "Save");

  const fileInput = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", hidden: true, onchange: async (ev) => {
    const f = ev.target.files[0];
    if (!f) return;
    try {
      await api(`/api/drones/${id}/photo`, { method: "PUT", headers: { "Content-Type": f.type }, body: f });
      viewDrone(id);
    } catch (e) { toast(e.message, true); }
  } });
  const photo = h("div", { class: "photo" },
    d.photo ? h("img", { src: `/photos/${encodeURIComponent(d.photo)}`, alt: d.name }) : h("div", { class: "empty" }, "no photo"),
    h("div", { class: "actions" },
      h("button", { onclick: () => fileInput.click() }, d.photo ? "Change photo" : "Add photo"), fileInput,
      d.photo ? h("button", { class: "danger", onclick: async () => { await api(`/api/drones/${id}/photo`, { method: "DELETE" }); viewDrone(id); } }, "Remove") : null));

  const detected = Object.keys(det).length ? h("table", { class: "kv" }, detectedRows(det)) : h("p", { class: "muted" }, "Not detected yet.");

  const typeInput = h("input", { type: "text", placeholder: "new component type (e.g. esc, battery)" });
  const components = h("section", {}, h("h2", {}, "Components"),
    h("table", {},
      h("tr", {}, h("th", {}, "Type"), h("th", {}, "Model"), h("th", {}, "Specs (key: value per line)"), h("th", {}, "Seen by the FC"), h("th", {})),
      d.components.map((c) => componentRow(id, c))),
    h("div", { class: "actions" }, typeInput,
      h("button", { onclick: async () => {
        try { await api(`/api/drones/${id}/components`, send("POST", { type: typeInput.value })); viewDrone(id); }
        catch (e) { toast(e.message, true); }
      } }, "Add component")));

  const checks = [];
  const snaps = h("section", {}, h("h2", {}, "Configuration history"),
    d.snapshots.length ? h("table", {},
      h("tr", {}, h("th", {}), h("th", {}, "Date"), h("th", {}, "Firmware"), h("th", {}, "Board"), h("th", {})),
      d.snapshots.map((s) => {
        const cb = h("input", { type: "checkbox", value: s.id });
        checks.push(cb);
        return h("tr", {}, h("td", {}, cb), h("td", {}, fmtDate(s.taken_at)),
          h("td", {}, `${s.firmware || "?"} ${s.version || ""}`), h("td", {}, s.board || ""),
          h("td", {}, h("a", { href: `#/snapshot/${s.id}` }, "view")));
      })) : h("p", { class: "muted" }, "No snapshot yet (detect with “full config” ticked)."),
    d.snapshots.length > 1 ? h("div", { class: "actions" }, h("button", { onclick: () => {
      const ids = checks.filter((c) => c.checked).map((c) => Number(c.value)).sort((a, b) => a - b);
      if (ids.length !== 2) return toast("Tick exactly two snapshots to compare", true);
      location.hash = `#/diff/${ids[0]}/${ids[1]}`;
    } }, "Compare the two ticked")) : null);

  main().replaceChildren(
    h("p", {}, h("a", { href: "#/" }, "← all drones")),
    h("section", {}, h("div", { class: "row" }, photo,
      h("div", { class: "fields" },
        h("label", { class: "f" }, "Name", name),
        h("label", { class: "f" }, "Notes", notes),
        h("label", { class: "f" }, "Specs (key: value per line)", specs),
        h("div", { class: "actions" }, saveDrone,
          h("button", { class: "danger", onclick: async () => {
            if (!confirm(`Delete “${d.name}” with its components and history?`)) return;
            await api(`/api/drones/${id}`, { method: "DELETE" });
            location.hash = "#/";
          } }, "Delete drone"))))),
    components,
    h("section", {}, h("h2", {}, `Read from the flight controller · last seen ${fmtDate(d.last_seen)}`), detected,
      (det.warnings || []).map((w) => h("p", { class: "warn" }, w))),
    snaps);
}

function detectedRows(det) {
  const rows = [];
  const add = (k, v) => { if (v !== undefined && v !== null && v !== "") rows.push(h("tr", {}, h("td", {}, k), h("td", {}, String(v)))); };
  add("Firmware", [det.firmware, det.version].filter(Boolean).join(" "));
  add("Variant / MSP API", [det.variant, det.msp_api].filter(Boolean).join(" / "));
  add("Board", [det.board_id, det.board_name].filter(Boolean).join(" · "));
  add("Build", [det.build_date, det.build_time, det.git_revision].filter(Boolean).join(" "));
  add("Craft name", det.craft_name);
  add("FC unique id", det.uid);
  for (const e of det.escs || []) add(`ESC ${e.index}`, e.error ? `not read (${e.error})` : [e.firmware, e.version, e.mcu && `on ${e.mcu}`, e.name && `· ${e.name}`].filter(Boolean).join(" "));
  for (const [k, v] of Object.entries(det.sensors || {})) add(`Sensor ${k}`, v);
  for (const [k, v] of Object.entries(det.settings || {})) add(k, v);
  return rows;
}

function componentRow(droneId, c) {
  const model = h("input", { type: "text", value: c.model });
  const specs = h("textarea", { rows: 2 }, specsToText(c.specs));
  return h("tr", {}, h("td", { class: "type" }, c.type), h("td", {}, model), h("td", {}, specs),
    h("td", { class: "hint" }, c.hint),
    h("td", {}, h("div", { class: "actions" },
      h("button", { onclick: async () => {
        try { await api(`/api/components/${c.id}`, send("PATCH", { model: model.value, specs: textToSpecs(specs.value) })); toast("Saved"); }
        catch (e) { toast(e.message, true); }
      } }, "Save"),
      h("button", { class: "danger", onclick: async () => { await api(`/api/components/${c.id}`, { method: "DELETE" }); viewDrone(droneId); } }, "✕"))));
}

async function viewSnapshot(id) {
  const s = await api(`/api/snapshots/${id}`);
  main().replaceChildren(
    h("p", {}, h("a", { href: `#/drone/${s.drone_id}` }, "← drone")),
    h("section", {}, h("h2", {}, `Snapshot ${fmtDate(s.taken_at)} · ${s.firmware || ""} ${s.version || ""}`),
      h("pre", { class: "raw" }, s.diff_text),
      s.status_text ? [h("h2", {}, "status"), h("pre", { class: "raw" }, s.status_text)] : null));
}

async function viewDiff(a, b, full) {
  const d = await api(`/api/snapshots/diff?a=${a}&b=${b}&context=${full ? -1 : 3}`);
  const label = (s) => `#${s.id} · ${fmtDate(s.taken_at)} · ${s.firmware || ""} ${s.version || ""}`;
  const cls = (t) => (t === "eq" ? "" : t);
  const rows = d.rows.map((r) => r.t === "skip"
    ? h("tr", { class: "skip" }, h("td", { colspan: 4 }, `… ${r.n} unchanged line(s) …`))
    : h("tr", {},
      h("td", { class: "ln" }, r.ll ?? ""), h("td", { class: r.l == null ? "" : cls(r.t === "add" ? "" : r.t) }, r.l ?? ""),
      h("td", { class: "ln" }, r.rl ?? ""), h("td", { class: r.r == null ? "" : cls(r.t === "del" ? "" : r.t) }, r.r ?? "")));
  main().replaceChildren(
    h("p", {}, h("a", { href: `#/drone/${d.b.drone_id}` }, "← drone")),
    h("section", {}, h("h2", {}, "Compare snapshots"),
      h("p", { class: "muted" }, `${d.stats.chg} changed · ${d.stats.add} added · ${d.stats.del} removed`),
      d.identical ? h("p", {}, "The two configurations are identical.") : null,
      h("div", { class: "actions" }, h("button", { onclick: () => viewDiff(a, b, !full) }, full ? "Show changes only" : "Show full files")),
      h("table", { class: "diff" },
        h("tr", {}, h("th", { colspan: 2 }, label(d.a)), h("th", { colspan: 2 }, label(d.b))),
        rows)));
}

// ----------------------------------------------------------------- router
async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  try {
    if (parts[0] === "drone" && parts[1]) await viewDrone(Number(parts[1]));
    else if (parts[0] === "snapshot" && parts[1]) await viewSnapshot(Number(parts[1]));
    else if (parts[0] === "diff" && parts[2]) await viewDiff(Number(parts[1]), Number(parts[2]), false);
    else await viewList();
  } catch (e) {
    main().replaceChildren(h("section", {}, h("p", { class: "warn" }, e.message)));
  }
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------ detection bar
async function loadPorts() {
  const sel = $("#port");
  const keep = sel.value;
  let ports = [];
  try { ports = await api("/api/ports"); } catch (_) { /* leave only "auto" */ }
  sel.replaceChildren(h("option", { value: "auto" }, `auto (${ports.length} found)`),
    ports.map((p) => h("option", { value: p.device }, `${p.device} ${p.description}`)));
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
}

$("#port").addEventListener("focus", loadPorts);
$("#scan-btn").addEventListener("click", async () => {
  const btn = $("#scan-btn");
  btn.disabled = true;
  toast("Reading the flight controller… it reboots when the CLI is closed.");
  try {
    const r = await api("/api/scan", send("POST", { port: $("#port").value, cli: $("#cli").checked, esc: $("#esc").checked }));
    const msg = r.created ? "New drone: fill in its details."
      : r.changed ? "Known drone: configuration changed, new snapshot saved."
      : "Known drone: nothing changed.";
    location.hash = `#/drone/${r.drone_id}`;
    toast([msg, ...r.warnings].join(" "), r.warnings.length > 0);
    route();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
});

loadPorts();
route();
