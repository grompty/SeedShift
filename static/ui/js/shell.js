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
  { href: "/settings", route: "settings", icon: "gear", label: "Settings" },
];

const COLLAPSE_KEY = "ss.sidebar";
const readCollapsed = () => { try { return localStorage.getItem(COLLAPSE_KEY) === "collapsed"; } catch { return false; } };
const writeCollapsed = (v) => { try { localStorage.setItem(COLLAPSE_KEY, v ? "collapsed" : "open"); } catch { /* private mode */ } };

let sidebar, scrim, toggleButton, servicesEl, jobsEl, collapsedBadge;

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

/* ── Services panel: target, connections, next scan ─────────────────── */

function renderServices(o) {
  const connections = o?.connections || [];
  const errors = o?.errors || [];
  const failing = new Set(errors.map((e) => e.source));
  const targets = o?.targets || [];
  const overall = !targets.length ? ["warning", "No target"] : failing.size ? ["danger", `${failing.size} failed`] : ["success", "Ready"];

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
      h("span", { class: "services__title" }, "Target"),
      h("span", { class: `services__overall tone-${overall[0]}` }, h("span", { class: "dot" }), overall[1])),
    h("div", { class: "target-host mono" }, targets.length ? targets.join(", ") : h("a", { class: "link", href: "/settings?section=target" }, "Choose a tracker")),
    h("ul", { class: "services__list" }, rows),
    h("div", { class: "services__sync" },
      h("span", { class: "services__sync-label", title: o?.scanned_at ? `Last scan ${ago(o.scanned_at)}` : "Not scanned yet" }, icon("arrows-rotate"), "Next scan"),
      h("span", { class: "mono services__sync-value" }, next)));

  const summary = `Target ${targets.join(", ") || "not set"}. Next scan ${next}.`;
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
      h("span", { class: "brand__mark" }, icon("tower-broadcast", "icon brand__icon")),
      h("span", { class: "brand__text" },
        h("span", { class: "brand__name" }, "Seedshift"),
        h("span", { class: "brand__sub", title: version ? `v${version}` : null }, "Tracker consolidation"))),
    toggleButton,
    h("nav", { class: "nav", "aria-label": "Primary" },
      NAV.map((n) => h("a", { class: "nav__item", href: n.href, "data-route": n.route, title: n.label },
        icon(n.icon, "icon nav__icon"), h("span", { class: "nav__text" }, n.label)))),
    jobsEl,
    servicesEl,
    collapsedBadge);

  root.append(sidebar, scrim);
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
