import { h, replace } from "../dom.js";
import { icon } from "../icons.js";
import { api } from "../api.js";
import { store } from "../store.js";
import { toast } from "../toast.js";
import { bytes, number } from "../format.js";
import { createDialog } from "../dialog.js";
import { pageHeading, notice } from "./common.js";

export const title = "Settings";

const SECTIONS = [
  { id: "connections", label: "Connections", icon: "link", blurb: "Download clients, the Radarr and Sonarr libraries to check, and Prowlarr for searching." },
  { id: "target", label: "Target tracker", icon: "tower-broadcast", blurb: "The tracker you want everything seeding on, and how to search it." },
  { id: "paths", label: "Paths", icon: "folder", blurb: "How paths in qBittorrent, Radarr and Sonarr map to this container." },
  { id: "scanning", label: "Scanning", icon: "arrows-rotate", blurb: "How files are linked to torrents, and how often to scan." },
];
const INTERVALS = [[0, "Manual only"], [30, "30 minutes"], [60, "1 hour"], [180, "3 hours"], [360, "6 hours"], [720, "12 hours"], [1440, "24 hours"]];
const TYPES = {
  qbittorrent: { label: "qBittorrent", icon: "download", url: "http://qbittorrent:8080", name: "qBittorrent" },
  radarr: { label: "Radarr", icon: "film", url: "http://radarr:7878", name: "Movies" },
  sonarr: { label: "Sonarr", icon: "tv", url: "http://sonarr:8989", name: "TV" },
  prowlarr: { label: "Prowlarr", icon: "magnifying-glass", url: "http://prowlarr:9696", name: "Prowlarr" },
};
const GROUPS = [
  { title: "Download clients", hint: "Torrents and their trackers are read from every client. Add one per qBittorrent you run.", types: ["qbittorrent"], add: "qbittorrent" },
  { title: "Libraries", hint: "Radarr gives movies, Sonarr gives seasons.", types: ["radarr", "sonarr"], add: "radarr" },
  { title: "Search", hint: "Optional. Lets the Search button ask only the target tracker.", types: ["prowlarr"], add: "prowlarr" },
];
const MODES = [["auto", "Hardlink, then size (recommended)"], ["inode", "Hardlink only"], ["size", "File size only"]];

let uid = 0;
function field(label, hint, control, id) {
  return h("div", { class: "field" },
    h("label", { class: "label", for: id }, label, hint ? h("span", { class: "label__hint" }, hint) : null), control);
}
function textInput(value, onInput, extra = {}) {
  const id = `f${++uid}`;
  const el = h("input", { class: "input input--full", id, value: value ?? "", autocomplete: "off", spellcheck: "false", oninput: (e) => onInput(e.target.value), ...extra });
  return { el, id };
}
function selectInput(options, value, onChange) {
  const id = `f${++uid}`;
  const el = h("select", { class: "select select--full", id, onchange: (e) => onChange(e.target.value) },
    options.map(([v, l]) => h("option", { value: v, selected: String(v) === String(value) }, l)));
  return { el, id };
}
function toggle(label, description, on, onChange) {
  let state = on;
  const el = h("button", { type: "button", role: "switch", "aria-checked": String(state), class: "switch",
    onclick: () => { state = !state; el.setAttribute("aria-checked", String(state)); onChange(state); } },
    h("span", { class: "switch__text" }, h("span", { class: "switch__label" }, label), h("span", { class: "switch__desc" }, description)),
    h("span", { class: "switch__track" }, h("span", { class: "switch__knob" })));
  return el;
}
const btn = (cls, label, onclick, ic, extra = {}) => h("button", { type: "button", class: `btn ${cls}`, onclick, ...extra }, ic ? icon(ic) : null, label);
const card = (...kids) => h("div", { class: "card" }, kids);

export function mount(container) {
  const query = new URLSearchParams(location.search);
  const asked = query.get("section") === "qbittorrent" ? "connections" : query.get("section");   // old address
  let section = SECTIONS.some((s) => s.id === asked) ? asked : "connections";
  let server = null;
  let draft = {};
  let mappings = [];
  let indexers = [];
  let stopped = false;

  const navEl = h("nav", { class: "settings-nav", "aria-label": "Settings sections" });
  const headEl = h("div", { class: "panel__head settings__head" });
  const bodyEl = h("div", { class: "settings__body" });
  const footEl = h("div", { class: "settings__foot" });
  const bannerEl = h("div", { class: "banners" });
  container.append(h("div", { class: "page" }, pageHeading("Settings"), bannerEl,
    h("div", { class: "settings" }, navEl,
      h("section", { class: "panel settings__panel", "aria-labelledby": "settings-title" }, headEl, bodyEl, footEl))));

  const sameMappings = () => JSON.stringify(mappings) === JSON.stringify(server.path_mappings);
  const dirtyKeys = () => Object.keys(draft).filter((k) => String(draft[k]) !== String(server.settings[k]));
  const sameIndexers = () => JSON.stringify(indexers) === JSON.stringify(server.target_indexers);
  const dirty = () => dirtyKeys().length > 0 || !sameMappings() || !sameIndexers();
  function setDraft(key, value) { draft[key] = value; paintFoot(); }

  function paintNav() {
    replace(navEl, SECTIONS.map((s) => h("a", { class: "settings-nav__item", href: `/settings?section=${s.id}`, "aria-current": s.id === section ? "page" : null,
      onclick: (e) => { e.preventDefault(); section = s.id; history.replaceState({}, "", `/settings?section=${s.id}`); paintSection(); } },
      icon(s.icon), s.label)));
  }
  let saveMsg = "";
  function paintFoot() {
    if (section === "connections") { replace(footEl); footEl.hidden = true; return; }
    footEl.hidden = false;
    const d = dirty();
    replace(footEl,
      h("span", { class: "settings__saved", role: "status" }, saveMsg ? [icon("check"), saveMsg] : null),
      h("div", { class: "dialog__actions" },
        btn("btn--tertiary", "Discard", discard, null, { disabled: !d }),
        btn("btn--primary", "Save changes", save, null, { disabled: !d })));
  }
  function reset() { draft = { ...server.settings }; mappings = structuredClone(server.path_mappings); indexers = [...server.target_indexers]; }
  function discard() { reset(); saveMsg = ""; paintSection(); }
  async function save() {
    const payload = {};
    for (const k of dirtyKeys()) payload[k] = draft[k];
    if (!sameMappings()) payload.path_mappings = mappings.filter((m) => m.remote || m.local);
    if (!sameIndexers()) payload.target_indexers = indexers;
    try {
      server = await api.put("/settings", payload);
      reset(); replace(bannerEl);
      saveMsg = "Changes saved";
      store.set("overview", await api.get("/overview"));
      paintSection();
      setTimeout(() => { saveMsg = ""; if (!stopped) paintFoot(); }, 2500);
    } catch (e) { replace(bannerEl, notice("danger", e.message)); window.scrollTo(0, 0); }
  }

  function paintSection() {
    const def = SECTIONS.find((s) => s.id === section);
    paintNav();
    replace(headEl, h("div", {}, h("h2", { id: "settings-title", class: "panel__title" }, def.label), h("p", { class: "settings__blurb" }, def.blurb)));
    replace(bodyEl, ({ connections, target, paths, scanning }[section])());
    paintFoot();
  }

  /* ── Connections ─────────────────────────────────────────────────── */
  function connections() {
    const wrap = h("div", { class: "stack" });
    const render = () => replace(wrap, GROUPS.map((g) => group(g, render)));
    render();
    return wrap;
  }
  function group(g, rerender) {
    const items = server.connections.filter((c) => g.types.includes(c.type));
    const addHolder = h("div", {});
    const onlyOne = g.add === "prowlarr" && items.length > 0;
    const add = onlyOne ? null : btn(items.length ? "btn--secondary btn--sm" : "btn--primary btn--sm", `Add ${g.add === "radarr" ? "Radarr or Sonarr" : TYPES[g.add].label}`, () => {
      add.hidden = true;
      addHolder.replaceChildren(connectionForm(null, g, rerender, () => { replace(addHolder); add.hidden = false; }));
      addHolder.querySelector("input")?.focus();
    }, "plus");
    return h("section", { class: "stack stack--tight conn-group", "aria-label": g.title },
      h("div", { class: "split" }, h("div", {}, h("div", { class: "card__title" }, g.title), h("div", { class: "hint" }, g.hint)), add),
      addHolder,
      items.map((c) => connectionCard(c, g, rerender)),
      !items.length && g.add === "qbittorrent" ? h("p", { class: "hint tone-warning" }, "Add at least one qBittorrent, or nothing will count as seeding.") : null);
  }
  function connectionCard(c, g, rerender) {
    const holder = h("div", {});
    const failed = (store.get("overview")?.errors || []).find((e) => e.source === c.id);
    const t = TYPES[c.type];
    const edit = btn("btn--tertiary btn--sm", "Edit", () => {
      edit.hidden = true;
      holder.replaceChildren(connectionForm(c, g, rerender, () => { replace(holder); edit.hidden = false; }));
    }, "pen");
    return card(
      h("div", { class: "split" },
        h("div", { class: "row-gap" }, h("div", { class: "file__icon", title: t.label }, icon(t.icon)),
          h("div", {}, h("div", { class: "card__title" }, c.name, c.name !== t.label ? h("span", { class: "hint" }, t.label) : null),
            h("div", { class: "hint mono" }, c.url))),
        h("div", { class: "row-gap" },
          failed ? h("span", { class: "status status--danger", title: failed.message }, "Last scan failed") : null,
          edit,
          btn("btn--tertiary btn--sm btn--danger", "Remove", () => removeConnection(c, rerender), "trash"))),
      failed ? h("p", { class: "hint tone-danger" }, failed.message) : null, holder);
  }
  function connectionForm(existing, g, rerender, cancel) {
    const type0 = existing?.type || g.add;
    const f = { type: type0, name: existing?.name || "", url: existing?.url || "", link_url: existing?.link_url || "",
      api_key: "", username: existing?.username || "", password: "" };
    const err = h("div", {});
    const fieldsEl = h("div", { class: "grid2" });
    const typeChoices = g.types.length > 1 && !existing ? selectInput(g.types.map((x) => [x, TYPES[x].label]), f.type, (v) => { f.type = v; paintFields(); }) : null;
    function paintFields() {
      const t = TYPES[f.type];
      const name = textInput(f.name, (v) => { f.name = v; }, { placeholder: t.name });
      const url = textInput(f.url, (v) => { f.url = v; }, { placeholder: t.url });
      const link = textInput(f.link_url, (v) => { f.link_url = v; }, { placeholder: "Optional, e.g. http://192.168.1.10:7878" });
      const parts = [field("Name", null, name.el, name.id),
        typeChoices ? field("Type", null, typeChoices.el, typeChoices.id) : h("div", {}),
        field(f.type === "qbittorrent" ? "Web UI URL" : "Base URL", "As this container reaches it", url.el, url.id)];
      if (f.type === "qbittorrent") {
        const user = textInput(f.username, (v) => { f.username = v; }, { placeholder: "Blank if auth is bypassed" });
        const pass = textInput("", (v) => { f.password = v; }, { type: "password", placeholder: existing?.has_password ? "Saved. Leave blank to keep it." : "Password" });
        parts.push(h("div", {}), field("Username", null, user.el, user.id), field("Password", null, pass.el, pass.id));
      } else {
        const key = textInput("", (v) => { f.api_key = v; }, { type: "password", placeholder: existing ? "Leave blank to keep the saved key" : "API key" });
        parts.push(field("API key", null, key.el, key.id));
        if (f.type !== "prowlarr") parts.push(field("Browser URL", "For Open links, if the base URL is a Docker name", link.el, link.id));
      }
      replace(fieldsEl, parts);
    }
    paintFields();
    const go = btn("btn--primary", "Test and save", async () => {
      go.disabled = true; replace(err);
      try {
        const r = await api.post("/connections/test", { ...f, ...(existing ? { id: existing.id } : {}) });
        toast(r.message, "success");
        server = await api.get("/settings");
        store.set("overview", await api.get("/overview"));
        rerender();
      } catch (e) { replace(err, notice("danger", e.message)); go.disabled = false; }
    });
    const note = f.type === "qbittorrent" ? "Only torrent, tracker and file lists are read. Nothing is paused, removed or added."
      : f.type === "prowlarr" ? "Used only when Search with is set to Prowlarr." : null;
    return h("form", { class: "subform", onsubmit: (e) => { e.preventDefault(); go.click(); } },
      fieldsEl, err, note ? h("p", { class: "hint" }, note) : null,
      h("div", { class: "dialog__actions" }, btn("btn--tertiary", "Cancel", cancel), go));
  }
  function removeConnection(c, rerender) {
    const d = createDialog({ title: `Remove ${c.name}?`, size: "sm", role: "alertdialog", tone: "danger" });
    const err = h("div", {});
    d.body.append(h("p", { class: "hint hint--lead" }, c.type === "qbittorrent" ? "Its torrents stop counting after the next scan. Nothing in qBittorrent is touched."
      : c.type === "prowlarr" ? "Search falls back to needing Radarr/Sonarr. Nothing in Prowlarr is touched."
      : "Its titles disappear from Seedshift after the next scan. Nothing in Radarr or Sonarr is touched."), err);
    d.footer.append(h("span", {}), h("div", { class: "dialog__actions" }, btn("btn--tertiary", "Cancel", d.close),
      btn("btn--danger-solid", "Remove", async () => {
        try {
          server = await api.put("/settings", { connections: server.connections.filter((x) => x.id !== c.id).map(({ id }) => ({ id })) });
          store.set("overview", await api.get("/overview"));
          d.close(); rerender(); toast(`Removed ${c.name}.`, "info");
        } catch (e) { replace(err, notice("danger", e.message)); }
      })));
  }

  /* ── Target tracker ──────────────────────────────────────────────── */
  function target() {
    const hosts = textInput(draft.target_trackers, (v) => { setDraft("target_trackers", v); }, { placeholder: "tracker.example.org" });
    const hasProwlarr = server.connections.some((c) => c.type === "prowlarr");
    const via = selectInput([["prowlarr", "Prowlarr (target only)"], ["arr", "Radarr / Sonarr (all indexers)"]], draft.search_via, (v) => { setDraft("search_via", v); paintVia(); });
    const viaHint = h("p", { class: "hint" });
    function paintVia() {
      replace(viaHint, draft.search_via === "prowlarr"
        ? [hasProwlarr ? null : h("span", { class: "tone-warning" }, "Add Prowlarr in Connections first. "),
           "Only the target gets a search. Grab pushes the release to Radarr/Sonarr, which applies your profile, category and tags. Results can differ from searching through the Arr."]
        : "Uses the Arr's own interactive search, so every indexer it has gets a hit. Results can differ from searching through Prowlarr. Grab works like the Arr's Grab button, including for releases it rejects.");
    }
    paintVia();

    const known = h("div", { class: "chips" });
    api.get("/trackers").then((r) => {
      if (stopped) return;
      const chosen = String(draft.target_trackers || "").split(/[,\s]+/).filter(Boolean);
      const pickable = r.trackers.filter((t) => t.host !== "(no tracker)" && !chosen.includes(t.host));
      replace(known, pickable.map((t) =>
        h("button", { type: "button", class: "chip chip--pick mono", title: `${number(t.count)} torrents · ${bytes(t.size)}`, onclick: (e) => {
          const chip = e.currentTarget;
          const list = String(draft.target_trackers || "").split(/[,\s]+/).filter(Boolean);
          if (!list.includes(t.host)) { list.push(t.host); hosts.el.value = list.join(", "); setDraft("target_trackers", hosts.el.value); }
          chip.remove();
        } }, icon("plus"), t.host, h("span", { class: "muted" }, bytes(t.size)))));
      if (!r.trackers.length) replace(known, h("span", { class: "hint" }, "Run a scan to list the trackers your torrents use."));
    }).catch(() => {});

    const ixEl = h("div", { class: "chips" }, h("span", { class: "hint" }, "Loading indexers…"));
    const ixNote = h("p", { class: "hint" });
    let ixList = [];
    function paintIndexers() {
      const on = new Set(indexers.map((n) => n.toLowerCase()));
      const guessing = !indexers.length && ixList.some((x) => x.suggested);
      replace(ixEl, ixList.length ? ixList.map((x) => {
        const active = on.has(x.name.toLowerCase()) || (guessing && x.suggested);
        return h("button", { type: "button", class: `chip chip--pick${active ? " chip--on" : ""}`, "aria-pressed": String(active),
          title: `In ${x.sources.join(", ")}`,
          onclick: () => {
            const base = guessing ? ixList.filter((y) => y.suggested).map((y) => y.name) : [...indexers];
            const i = base.findIndex((n) => n.toLowerCase() === x.name.toLowerCase());
            if (i >= 0) base.splice(i, 1); else base.push(x.name);
            indexers = base; paintIndexers(); paintFoot();
          } }, icon(active ? "check" : "plus"), x.name, x.suggested ? h("span", { class: "muted" }, "matches target") : null);
      }) : h("span", { class: "hint" }, "No torrent indexers found. Connect Radarr, Sonarr or Prowlarr first."));
      replace(ixNote, guessing ? "Picked automatically because the site address matches the target. Click to choose yourself."
        : indexers.length ? "Search results are limited to these." : "Choose which indexer is the target tracker, so the Search button can filter to it.");
    }
    api.get("/indexers").then((r) => { if (stopped) return; ixList = r.indexers; paintIndexers(); })
      .catch((e) => replace(ixEl, h("span", { class: "hint tone-danger" }, e.message)));

    return h("div", { class: "stack" },
      field("Target tracker", "Announce host. Several hosts of the same site can be comma-separated; subdomains count too", hosts.el, hosts.id),
      h("div", {}, h("div", { class: "label" }, "Trackers seen in the last scan"), known),
      h("div", { class: "divider" }),
      h("div", {}, h("div", { class: "label" }, "Target indexer"), ixEl, ixNote),
      h("div", {}, field("Search with", null, via.el, via.id), viaHint),
    );
  }

  /* ── Paths ───────────────────────────────────────────────────────── */
  function paths() {
    const list = h("div", { class: "stack stack--tight" });
    const render = () => replace(list, mappings.length ? mappings.map((m, i) => {
      const remote = textInput(m.remote, (v) => { m.remote = v; paintFoot(); }, { placeholder: "/downloads", "aria-label": "Path in the other app" });
      const local = textInput(m.local, (v) => { m.local = v; paintFoot(); }, { placeholder: "/data/torrents", "aria-label": "Path in this container" });
      return h("div", { class: "mapping" }, remote.el, icon("arrow-right", "icon tone-neutral"), local.el,
        btn("btn--tertiary btn--sm btn--square btn--danger", "", () => { mappings.splice(i, 1); render(); paintFoot(); }, "trash", { "aria-label": "Remove mapping" }));
    }) : h("p", { class: "hint" }, "No mappings. Paths are used as they are."));
    render();
    const d = store.get("overview")?.diagnostics || {};
    const health = d.library_files ? card(h("div", { class: "card__title" }, icon("folder", "icon tone-accent"), "Last scan"),
      h("p", { class: "hint" }, `${number(d.library_files_on_disk)} of ${number(d.library_files)} library files and ${number(d.torrents_on_disk)} of ${number(d.torrents_total)} torrents were visible in this container.`),
      d.library_files_on_disk < d.library_files && d.example_missing_path ? h("p", { class: "hint" }, "Not found, for example: ", h("span", { class: "mono" }, d.example_missing_path)) : null) : null;
    return h("div", { class: "stack" },
      h("p", { class: "hint hint--lead" }, "If qBittorrent, Radarr, Sonarr and Seedshift all mount the share at the same path (", h("span", { class: "mono" }, "/data"), " in the usual hardlink setup), you need nothing here. Otherwise map each app's path to where the same folder is mounted in this container."),
      list,
      h("div", {}, btn("btn--secondary btn--sm", "Add mapping", () => { mappings.push({ remote: "", local: "" }); render(); paintFoot(); list.querySelector(".mapping:last-child input")?.focus(); }, "plus")),
      health);
  }

  /* ── Scanning ────────────────────────────────────────────────────── */
  function scanning() {
    const mode = selectInput(MODES, draft.match_mode, (v) => setDraft("match_mode", v));
    const iv = selectInput(INTERVALS, draft.scan_interval_minutes, (v) => setDraft("scan_interval_minutes", v));
    const min = textInput(draft.min_match_size_mb, (v) => setDraft("min_match_size_mb", v.trim()), { inputmode: "numeric" });
    return h("div", { class: "stack" },
      h("div", { class: "grid2" }, field("Matching", "How library files are linked to torrents", mode.el, mode.id), field("Automatic scan", null, iv.el, iv.id)),
      h("div", { class: "grid2" }, field("Size match minimum (MB)", "Smaller files are only matched by hardlink", min.el, min.id)),
      toggle("Include specials", "Count Sonarr season 0 as its own season.", draft.include_specials === "on", (v) => setDraft("include_specials", v ? "on" : "off")),
      h("p", { class: "hint" }, "Hardlinked files share an inode with the torrent's copy, so that link is exact. Size matching catches files that were copied instead, or a library this container can't see. A scan only reads; it never changes files, torrents or your Arrs."));
  }

  api.get("/settings").then((s) => { if (stopped) return; server = s; reset(); paintSection(); })
    .catch((e) => replace(bannerEl, notice("danger", e.message)));
  paintNav();
  return () => { stopped = true; };
}
