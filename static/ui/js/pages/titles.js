import { h, replace } from "../dom.js";
import { icon } from "../icons.js";
import { api } from "../api.js";
import { number, bytes, plural, timeAgo } from "../format.js";
import { store } from "../store.js";
import { toast } from "../toast.js";
import { createDialog } from "../dialog.js";
import { pageHeading, notice, scanButton, STATUS } from "./common.js";
import { openSearch } from "../search-dialog.js";

export const title = "Titles";

const PER_PAGE = [10, 25, 50, 100, 250];
const VIEWS = [
  { value: "need", label: "Not on target" },
  { value: "missing", label: "Seeding elsewhere" },
  { value: "not_seeding", label: "Not seeding at all" },
  { value: "target_stopped", label: "Stopped on target" },
  { value: "partial", label: "Partly on target", series: true },
  { value: "on_target", label: "On target" },
  { value: "all", label: "All titles" },
  { value: "ignored", label: "Ignored" },
];
const SORTS = [["size", "Largest first"], ["title", "Title A–Z"], ["year", "Newest first"]];

export function mount(container) {
  const query = new URLSearchParams(location.search);
  // All view state lives in the URL, so filters survive reload, back/forward and links from Overview.
  const state = {
    type: query.get("type") === "series" ? "series" : "movie",
    q: query.get("q") || "",
    connection: query.get("connection") || "",
    status: VIEWS.some((v) => v.value === query.get("status")) ? query.get("status") : "need",
    sort: SORTS.some(([v]) => v === query.get("sort")) ? query.get("sort") : "size",
    airing: query.get("airing") === "show",
    per_page: PER_PAGE.includes(+query.get("per_page")) ? +query.get("per_page") : 25,
    page: Math.max(1, parseInt(query.get("page") || "1", 10) || 1),
  };
  let data = null;
  let seq = 0;
  let typing = null;
  let stopped = false;

  function url(extra = {}) {
    const s = { ...state, ...extra };
    const p = new URLSearchParams();
    if (s.type === "series") p.set("type", "series");
    if (s.q) p.set("q", s.q);
    if (s.connection) p.set("connection", s.connection);
    if (s.status !== "need") p.set("status", s.status);
    if (s.sort !== "size") p.set("sort", s.sort);
    if (s.airing) p.set("airing", "show");
    if (s.per_page !== 25) p.set("per_page", s.per_page);
    if (s.page > 1) p.set("page", s.page);
    const qs = p.toString();
    return "/titles" + (qs ? `?${qs}` : "");
  }
  function change(patch) {
    Object.assign(state, { page: 1 }, patch);
    history.replaceState({}, "", url());
    load();
  }
  function go(page) { state.page = page; history.pushState({}, "", url()); load(); window.scrollTo(0, 0); }

  /* ── Static frame ─────────────────────────────────────────────────── */
  const bannersEl = h("div", { class: "banners" });
  const scanBtn = scanButton("btn--secondary");
  const tabsEl = h("div", { class: "tabs", role: "group", "aria-label": "Library type" });
  const searchEl = h("input", {
    type: "search", class: "input", placeholder: "Search titles", "aria-label": "Search titles", value: state.q, autocomplete: "off",
    oninput: (e) => { clearTimeout(typing); typing = setTimeout(() => change({ q: e.target.value.trim() }), 250); },
  });
  const connEl = h("select", { class: "select", "aria-label": "Filter by connection", onchange: (e) => change({ connection: e.target.value }) });
  const viewEl = h("select", { class: "select", "aria-label": "Filter by status", onchange: (e) => change({ status: e.target.value }) });
  const sortEl = h("select", { class: "select", "aria-label": "Sort", onchange: (e) => change({ sort: e.target.value }) },
    SORTS.map(([v, l]) => h("option", { value: v }, l)));
  const airingEl = h("label", { class: "checkline" },
    h("input", { type: "checkbox", checked: state.airing, onchange: (e) => change({ airing: e.target.checked }) }), "Include airing seasons");
  const summaryEl = h("div", { class: "titles-summary hint" });
  const listEl = h("ul", { class: "trailer-list" });
  const footEl = h("div", { class: "trailer-foot" });
  const headEl = h("div", { class: "trailer-head", "aria-hidden": "true" });

  container.append(h("div", { class: "page" }, pageHeading("Titles", scanBtn), bannersEl,
    h("section", { class: "panel trailers", "aria-label": "Library" },
      h("div", { class: "trailers__bar" }, tabsEl,
        h("div", { class: "trailers__filters" }, h("label", { class: "search" }, icon("magnifying-glass"), searchEl), connEl, viewEl, sortEl, airingEl)),
      summaryEl, headEl, listEl, footEl)));
  sortEl.value = state.sort;

  function renderTabs() {
    const t = store.get("overview")?.totals;
    replace(tabsEl, [["movie", "Movies", "film", t?.movies.need], ["series", "Shows", "tv", t?.seasons.need]].map(([value, label, ic, count]) =>
      h("button", { type: "button", class: "tab", "aria-pressed": String(state.type === value), onclick: () => {
        if (state.type !== value) change({ type: value, connection: "", status: state.status === "partial" ? "need" : state.status });
      } }, icon(ic), label, count != null ? h("span", { class: "tab__count mono", title: "Not on target" }, number(count)) : null)));
    airingEl.hidden = state.type !== "series";
    replace(headEl, h("span", {}, state.type === "series" ? "Season" : "Movie"), h("span", {}, "Seeding on"), h("span", {}, "Actions"));
  }

  function renderFilters() {
    const f = data.filters;
    replace(connEl, h("option", { value: "" }, "All connections"), f.connections.map((c) => h("option", { value: c.id }, c.name)));
    connEl.value = state.connection;
    connEl.hidden = f.connections.length < 2;
    replace(viewEl, VIEWS.filter((v) => !v.series || state.type === "series").map((v) => h("option", { value: v.value }, v.label)));
    viewEl.value = state.status;
    searchEl.placeholder = state.type === "series" ? "Search shows" : "Search movies";
  }

  function renderBanners() {
    const out = [];
    if (!data.has_scan) out.push(notice("info", data.scan.running ? "Scanning… the list fills in when it finishes." : "No scan yet. Press Scan now."));
    if (data.has_scan && !data.targets.length) out.push(notice("warning", "No target tracker chosen, so nothing counts as on target. ", h("a", { class: "link", href: "/settings?section=target" }, "Choose one"), "."));
    replace(bannersEl, out);
  }

  function hostChips(item) {
    if (!item.hosts.length && !item.inactive_hosts.length) return null;
    return h("div", { class: "hosts" },
      item.hosts.map((host) => h("span", { class: `host mono${item.target_hosts.includes(host) ? " host--target" : ""}` }, host)),
      item.inactive_hosts.map((host) => h("span", { class: "host host--off mono", title: "Torrent is stopped, errored or still downloading" }, host)));
  }

  function metaLine(item) {
    const bits = [];
    if (item.kind === "season") {
      bits.push(`Season ${item.season}`);
      bits.push(item.episodes === item.total_episodes ? plural(item.episodes, "episode") : `${item.episodes} of ${item.total_episodes} episodes`);
    }
    if (item.year) bits.push(item.year);
    if (item.quality) bits.push(item.quality);
    if ((data.filters.connections || []).length > 1) bits.push(item.connection_name);
    return bits.join(" · ");
  }

  async function setIgnored(item, ignored) {
    try {
      await api.post("/ignore", { key: item.key, ignored });
      toast(ignored ? `Ignoring ${item.title}.` : `${item.title} is back in the list.`, "info");
      load();
      api.get("/overview").then((o) => store.set("overview", o)).catch(() => {});
    } catch (e) { toast(e.message, "danger"); }
  }

  function row(item) {
    const st = STATUS[item.status];
    const flags = [h("span", { class: `flag tone-${st.tone}` }, icon(st.icon), item.kind === "season" && item.status === "partial"
      ? `${item.on_target_files} of ${item.episodes} on target` : st.label)];
    if (item.kind === "season" && item.airing) flags.push(h("span", { class: "flag tone-info" }, icon("tower-broadcast"), "Airing"));
    else if (item.kind === "season" && !item.complete) flags.push(h("span", { class: "flag tone-warning" }, icon("triangle-exclamation"), "Incomplete season"));
    if (item.last_grab) {
      const t = timeAgo(item.last_grab.ts);
      flags.push(h("a", { class: "flag tone-info link-flag grab-flag", href: "/history", title: item.last_grab.release },
        icon("download"), `Grabbed ${!t ? "" : t === "now" ? "just now" : /\d$/.test(t) ? t : `${t} ago`}`));
    }
    if (item.match === "size") flags.push(h("span", { class: "flag tone-neutral", title: "Linked by exact file size, not by hardlink" }, "by size"));
    flags.push(h("span", { class: "mono muted" }, bytes(item.size)));

    const actions = [
      h("button", { type: "button", class: "btn btn--tertiary btn--sm", onclick: () => openDetails(item) }, icon("circle-info"), "Details"),
      h("button", { type: "button", class: "btn btn--secondary btn--sm", onclick: () => openSearch(item) }, icon("magnifying-glass"), "Search"),
      item.arr_url ? h("a", { class: "btn btn--tertiary btn--sm btn--square", href: item.arr_url, target: "_blank", rel: "noopener noreferrer",
        "aria-label": `Open ${item.title} in ${item.kind === "movie" ? "Radarr" : "Sonarr"}`, title: `Open in ${item.kind === "movie" ? "Radarr" : "Sonarr"}` }, icon("arrow-up-right-from-square")) : null,
      h("button", { type: "button", class: "btn btn--tertiary btn--sm btn--square", "aria-label": item.ignored ? `Stop ignoring ${item.title}` : `Ignore ${item.title}`,
        title: item.ignored ? "Stop ignoring" : "Ignore (not available on the target)", onclick: () => setIgnored(item, !item.ignored) }, icon(item.ignored ? "arrows-rotate" : "ban")),
    ];
    // Grabbed but not on target yet: dim the row so the titles still to do stand out.
    const grabbed = item.last_grab && item.status !== "on_target";
    return h("li", { class: `trailer-row${grabbed ? " is-grabbed" : ""}` },
      h("div", { class: "trailer-row__title" },
        h("div", { class: "trailer-row__name" }, icon(item.kind === "season" ? "tv" : "film", "icon tone-neutral"), h("span", {}, item.title)),
        h("div", { class: "trailer-row__meta" }, metaLine(item))),
      h("div", { class: "trailer-row__file" },
        hostChips(item) || h("span", { class: "muted hint" }, "No torrent in qBittorrent"),
        h("div", { class: "trailer-row__flags" }, flags)),
      h("div", { class: "trailer-row__actions" }, actions));
  }

  async function openDetails(item) {
    const label = item.kind === "season" ? `${item.title} · Season ${item.season}` : `${item.title}${item.year ? ` (${item.year})` : ""}`;
    const d = createDialog({ title: label, subtitle: STATUS[item.status].label, size: "lg" });
    d.body.append(h("p", { class: "files__loading muted" }, "Loading…"));
    d.footer.append(h("span", {}), h("div", { class: "dialog__actions" },
      h("button", { type: "button", class: "btn btn--secondary", onclick: () => { d.close(); openSearch(item); } }, icon("magnifying-glass"), "Search target"),
      h("button", { type: "button", class: "btn btn--tertiary", onclick: d.close }, "Close")));
    try {
      const r = await api.get(`/items/${encodeURIComponent(item.key)}`);
      const torrents = r.torrents.length ? h("ul", { class: "files" }, r.torrents.map((t) => h("li", { class: "file" },
        h("div", { class: "file__icon" }, icon(t.is_target && t.seeding ? "circle-check" : "tower-broadcast", t.is_target && t.seeding ? "icon tone-success" : "icon")),
        h("div", { class: "file__main" },
          h("div", { class: "file__name" }, t.name),
          h("div", { class: "file__meta" },
            h("span", { class: `host mono${t.is_target ? " host--target" : ""}` }, t.host || "no tracker"),
            t.client ? h("span", { class: "hint" }, t.client) : null,
            h("span", { class: "mono muted" }, bytes(t.size)),
            t.seeding ? null : h("span", { class: "flag tone-warning" }, icon("circle-xmark"), t.state),
            r.file_count > 1 ? h("span", { class: "hint" }, `${t.files_covered} of ${r.file_count} files`) : null)))))
        : h("p", { class: "muted" }, "No torrent in qBittorrent seeds these files.");
      const files = h("details", { class: "file-paths" }, h("summary", {}, `Library ${r.file_count === 1 ? "file" : `files (${r.file_count})`}`),
        h("ul", { class: "path-list" }, r.files.map((f) => h("li", {},
          h("span", { class: "mono" }, f.path), " ",
          h("span", { class: "hint" }, `${bytes(f.size)} · ${f.match === "inode" ? "hardlink" : f.match === "size" ? "matched by size" : "no torrent"}`)))));
      replace(d.body, h("div", { class: "stack" }, h("div", { class: "label" }, "Torrents"), torrents, files));
    } catch (e) { replace(d.body, notice("danger", e.message)); }
  }

  function renderRows() {
    replace(summaryEl, data.total ? `${plural(data.total, state.type === "series" ? "season" : "movie")} · ${bytes(data.total_size)}` : null);
    replace(listEl, data.items.length ? data.items.map(row)
      : h("li", { class: "activity-empty" }, !data.has_scan ? (data.scan.running ? "Scanning…" : "Nothing scanned yet.") : state.status === "need" ? "Everything here is on the target. Nice." : "No titles match your filters."));
    const pages = Math.max(1, Math.ceil(data.total / data.per_page));
    const from = data.total ? (data.page - 1) * data.per_page + 1 : 0;
    const to = Math.min(data.total, data.page * data.per_page);
    replace(footEl,
      h("div", { class: "trailer-foot__left" },
        h("span", { class: "muted" }, `Showing ${number(from)}–${number(to)} of ${number(data.total)}`),
        h("label", { class: "rows-per-page" }, h("span", {}, "Rows per page"),
          h("select", { class: "select select--sm", "aria-label": "Rows per page", onchange: (e) => change({ per_page: +e.target.value }) },
            PER_PAGE.map((n) => h("option", { value: n, selected: n === state.per_page }, n))))),
      pages > 1 ? h("div", { class: "pager pager--inline" },
        h("button", { type: "button", class: "btn btn--tertiary btn--sm", disabled: data.page <= 1, onclick: () => go(data.page - 1) }, icon("chevron-left"), "Previous"),
        h("span", { class: "muted" }, `Page ${data.page} of ${pages}`),
        h("button", { type: "button", class: "btn btn--tertiary btn--sm", disabled: data.page >= pages, onclick: () => go(data.page + 1) }, "Next", icon("chevron-right"))) : null);
  }

  async function load() {
    const mine = ++seq;
    const p = new URLSearchParams({ type: state.type, page: state.page, per_page: state.per_page, status: state.status, sort: state.sort });
    if (state.q) p.set("q", state.q);
    if (state.connection) p.set("connection", state.connection);
    if (state.airing) p.set("airing", "show");
    try {
      const result = await api.get(`/items?${p}`);
      if (mine !== seq || stopped) return;
      data = result;
      state.page = data.page;
      renderTabs(); renderFilters(); renderBanners(); renderRows();
    } catch (err) {
      if (mine === seq && !stopped) replace(bannersEl, notice("danger", err.message));
    }
  }

  const offTabs = store.subscribe("overview", renderTabs);
  const offScan = store.subscribe("scanFinished", () => load());
  const offGrab = store.subscribe("grabbed", () => load());
  renderTabs();
  load();
  return () => { stopped = true; clearTimeout(typing); offTabs(); offScan(); offGrab(); scanBtn.cleanup?.(); };
}
