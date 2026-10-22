import { h, replace } from "./dom.js";
import { icon } from "./icons.js";
import { api } from "./api.js";
import { store } from "./store.js";
import { poll } from "./poller.js";
import { hostOf, timeUntil, timeAgo } from "./format.js";
import { navigate } from "./router.js";

const NAV = [
  { href: "/", route: "overview", icon: "house", label: "Overview" },
  { href: "/titles", route: "titles", icon: "film", label: "Titles" },
  { href: "/history", route: "history", icon: "clock-rotate-left", label: "History" },
  { href: "/settings", route: "settings", icon: "gear", label: "Settings" },
];

const COLLAPSE_KEY = "ss.sidebar";
const readCollapsed = () => { try { return localStorage.getItem(COLLAPSE_KEY) === "collapsed"; } catch { return false; } };
const writeCollapsed = (v) => { try { localStorage.setItem(COLLAPSE_KEY, v ? "collapsed" : "open"); } catch { /* private mode */ } };

let sidebar, scrim, toggleButton, servicesEl, jobsEl, collapsedBadge;

// Seedshift logo: two database stacks with arrows circling between them. Stroked, so it isn't in icons.js.
const LOGO_PATH = "M4 7.5A10 3.5 0 1 0 24 7.5A10 3.5 0 1 0 4 7.5M4 7.5V26.5M24 7.5V26.5M4 26.5A10 3.5 0 0 0 24 26.5M4 13.8A10 3.5 0 0 0 24 13.8M4 20.2A10 3.5 0 0 0 24 20.2M40 37.5A10 3.5 0 1 0 60 37.5A10 3.5 0 1 0 40 37.5M40 37.5V56.5M60 37.5V56.5M40 56.5A10 3.5 0 0 0 60 56.5M40 43.8A10 3.5 0 0 0 60 43.8M40 50.2A10 3.5 0 0 0 60 50.2M28 8C42 8 50 16 50 28M46 24L50 29L54 24M36 56C22 56 14 48 14 36M18 40L14 35L10 40";
function logo() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 64 64", fill: "none", stroke: "currentColor", "stroke-width": "3.6",
    "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false", class: "icon brand__icon" })) svg.setAttribute(k, v);
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", LOGO_PATH);
  svg.append(path);
  return svg;
}

export function openMenu() {
  sidebar.dataset.open = "true";
  scrim.hidden = false;
  document.body.classList.add("menu-open");
  sidebar.querySelector(".nav__item")?.focus();
}
export function closeMenu({ restoreFocus = false } = {}) {
  if (sidebar.dataset.open !== "true") return;
  sidebar.dataset.open = "false";
  scrim.hidden = true;
  document.body.classList.remove("menu-open");
  if (restoreFocus) document.querySelector(".menu-button")?.focus();
}

function setCollapsed(collapsed) {
  document.body.dataset.sidebar = collapsed ? "collapsed" : "open";
  toggleButton.setAttribute("aria-expanded", String(!collapsed));
  const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
  toggleButton.setAttribute("aria-label", label);
  toggleButton.title = label;
  writeCollapsed(collapsed);
}

export function setActiveRoute(route) {
  for (const link of sidebar.querySelectorAll(".nav__item")) {
    if (link.dataset.route === route) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

export const ago = (iso) => { const t = timeAgo(iso); return !t ? "" : t === "now" ? "just now" : /\d$/.test(t) ? t : `${t} ago`; };

/* ── Screenshot mode: the API answers with made-up names (privacy.py). Per browser, in a cookie. ── */
export const screenshotMode = () => document.cookie.split("; ").includes("seedshift_private=1");
function setScreenshotMode(on) {
  document.cookie = `seedshift_private=${on ? 1 : 0}; path=/; max-age=${on ? 31536000 : 0}; SameSite=Lax`;
  location.reload();
}

/* ── Services panel: target, connections, next scan ─────────────────── */

function renderServices(o) {
  const connections = o?.connections || [];
  const errors = o?.errors || [];
  const failing = new Set(errors.map((e) => e.source));
  const targets = o?.targets || [];
  // Connection health, shown above the services. Says nothing about the target: that has its own heading.
  const overall = !connections.length ? ["neutral", "None yet"]
    : failing.size ? ["danger", `${failing.size} failed`]
    : !o?.scanned_at ? ["neutral", "Not scanned yet"]
    : ["success", "All connected"];

  const groups = [["qbittorrent", "qBittorrent"], ["radarr", "Radarr"], ["sonarr", "Sonarr"], ["prowlarr", "Prowlarr"]]
    .map(([key, label]) => [key, label, connections.filter((c) => c.type === key)])
    .filter(([, , items]) => items.length);

  const rows = groups.map(([key, label, items]) => {
    const down = items.filter((c) => failing.has(c.id)).length;
    const tipId = `tip-${key}`;
    return h("li", { class: "service" },
      h("button", { type: "button", class: "service__button", "aria-describedby": tipId },
        h("span", {}, label),
        h("span", { class: `service__count mono${down ? " tone-danger" : ""}` },
          down ? `${items.length - down} of ${items.length} OK` : items.length === 1 ? "Connected" : `${items.length} connected`)),
      h("div", { role: "tooltip", id: tipId, class: "service__tip" },
        h("span", { class: "service__tip-title" }, label),
        items.map((c) => h("span", { class: "service__tip-row" },
          h("span", { class: "service__tip-line" },
            h("span", { class: "service__tip-name" }, c.name),
            h("span", { class: `service__state tone-${failing.has(c.id) ? "danger" : "success"}` },
              h("span", { class: "dot" }), failing.has(c.id) ? "Last scan failed" : "OK")),
          c.url ? h("span", { class: "service__tip-host mono" }, hostOf(c.url)) : null))));
  });

  const scan = store.get("scan") || o?.scan;
  const next = scan?.running ? "Now" : o?.next_scan_at ? timeUntil(o.next_scan_at) : "Manual";
  replace(servicesEl,
    h("div", { class: "services__head" },
      h("span", { class: "services__title" }, targets.length > 1 ? "Target trackers" : "Target tracker")),
    h("div", { class: "target-host mono" }, targets.length ? targets.join(", ") : h("a", { class: "link", href: "/settings?section=target" }, "Choose a tracker")),
    h("div", { class: "services__head" },
      h("span", { class: "services__title" }, "Connections"),
      h("span", { class: `services__overall tone-${overall[0]}` }, h("span", { class: "dot" }), overall[1])),
    h("ul", { class: "services__list" }, rows),
    h("div", { class: "services__sync" },
      h("span", { class: "services__sync-label", title: o?.scanned_at ? `Last scan ${ago(o.scanned_at)}` : "Not scanned yet" }, icon("arrows-rotate"), "Next scan"),
      h("span", { class: "mono services__sync-value" }, next)),
    h("button", { type: "button", class: "services__private", role: "switch", "aria-checked": String(screenshotMode()),
      title: "Shows made-up titles, trackers and paths, so you can share screenshots", onclick: () => setScreenshotMode(!screenshotMode()) },
      icon("wand-magic-sparkles"), "Screenshot mode", h("span", { class: `mono ${screenshotMode() ? "tone-accent" : "muted"}` }, screenshotMode() ? "On" : "Off")));

  const summary = `Target tracker: ${targets.join(", ") || "not set"}. Connections: ${overall[1]}. Next scan ${next}.`;
  collapsedBadge.title = summary;
  collapsedBadge.setAttribute("aria-label", summary);
  collapsedBadge.classList.toggle("is-alert", failing.size > 0 || !targets.length);
}

/* ── Scan progress panel ─────────────────────────────────────────────── */

function renderScan() {
  const s = store.get("scan");
  jobsEl.hidden = !s?.running;
  if (jobsEl.hidden) { replace(jobsEl); return; }
  const pct = s.total ? (s.done / s.total) * 100 : null;
  replace(jobsEl,
    h("div", { class: "jobs__title" }, h("span", { class: "dot dot--pulse" }), "Scanning"),
    h("div", { class: "job" },
      h("div", { class: "job__line" },
        h("span", { class: "job__name" }, s.phase || "Working"),
        h("span", { class: "mono job__meta" }, s.total ? `${s.done} of ${s.total}` : "…")),
      pct != null ? h("div", { class: "progress", role: "progressbar", "aria-label": s.phase || "Scan",
        "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(pct)) },
        h("span", { style: `width:${Math.max(0, Math.min(100, pct))}%` })) : null));
}

/* ── Build + start ──────────────────────────────────────────────────── */

export function buildShell(root) {
  const version = root.dataset.version || "";
  scrim = h("button", { type: "button", class: "scrim", hidden: true, "aria-label": "Close navigation", onclick: () => closeMenu({ restoreFocus: true }) });
  toggleButton = h("button", { type: "button", class: "btn btn--tertiary sidebar__toggle", onclick: () => setCollapsed(document.body.dataset.sidebar !== "collapsed") },
    icon("chevron-left", "icon sidebar__toggle-icon"));
  servicesEl = h("section", { class: "services", "aria-label": "Target and services" });
  jobsEl = h("section", { class: "jobs", "aria-label": "Scan progress", "aria-live": "polite", hidden: true });
  collapsedBadge = h("button", { type: "button", class: "services-badge", onclick: () => setCollapsed(false) }, icon("tower-broadcast", "icon"));

  sidebar = h("aside", { class: "sidebar", id: "sidebar", "data-open": "false" },
    h("a", { class: "brand", href: "/", "aria-label": "Seedshift, overview" },
      h("span", { class: "brand__mark" }, logo()),
      h("span", { class: "brand__text" },
        h("span", { class: "brand__name" }, "Seedshift", version ? h("span", { class: "brand__version" }, `v${version}`) : null),
        h("span", { class: "brand__sub" }, "Focus your seed size"))),
    toggleButton,
    h("nav", { class: "nav", "aria-label": "Primary" },
      NAV.map((n) => h("a", { class: "nav__item", href: n.href, "data-route": n.route, title: n.label },
        icon(n.icon, "icon nav__icon"), h("span", { class: "nav__text" }, n.label)))),
    jobsEl,
    servicesEl,
    collapsedBadge);

  root.append(sidebar, scrim);
  if (screenshotMode()) root.append(h("div", { class: "private-pill", role: "status" }, icon("wand-magic-sparkles"), "Screenshot mode: names are made up"));
  setCollapsed(readCollapsed());
  renderServices(store.get("overview"));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar.dataset.open === "true") closeMenu({ restoreFocus: true });
  });
  window.matchMedia("(min-width: 64rem)").addEventListener("change", () => closeMenu());
  // Place a service tooltip next to its button. It's position: fixed so the scrolling sidebar can't clip it.
  const placeTip = (event) => {
    const button = event.target.closest?.(".service__button");
    const tip = button?.nextElementSibling;
    if (!tip) return;
    requestAnimationFrame(() => {
      const r = button.getBoundingClientRect();
      const narrow = window.innerWidth < 512;
      tip.style.left = `${narrow ? r.left : r.right + 8}px`;
      tip.style.top = `${Math.max(8, narrow ? r.top - tip.offsetHeight - 8 : Math.min(r.bottom - tip.offsetHeight, window.innerHeight - tip.offsetHeight - 8))}px`;
    });
  };
  servicesEl.addEventListener("mouseover", placeTip);
  servicesEl.addEventListener("focusin", placeTip);
  store.subscribe("overview", renderServices);
  store.subscribe("scan", renderScan);
  setInterval(() => renderServices(store.get("overview")), 30000);
}

export function startPolling() {
  const overview = poll(async () => store.set("overview", await api.get("/overview")), () => 15000);
  let wasRunning = false;
  const scan = poll(async () => {
    const r = await api.get("/scan");
    store.set("scan", r.scan);
    // A scan just finished: refresh the numbers everywhere.
    if (wasRunning && !r.scan.running) {
      store.set("overview", await api.get("/overview"));
      store.set("scanFinished", r.scanned_at || Date.now());
    }
    wasRunning = r.scan.running;
  }, () => (store.get("scan")?.running ? 1500 : 6000));
  // Kick the fast poll right after someone starts a scan.
  store.subscribe("scan", (s) => { if (s?.running && !wasRunning) { wasRunning = true; setTimeout(() => scan.now(), 800); } });
  return { overview, scan };
}

export { navigate };
