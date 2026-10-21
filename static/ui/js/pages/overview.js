import { h, replace } from "../dom.js";
import { icon } from "../icons.js";
import { store } from "../store.js";
import { api } from "../api.js";
import { toast } from "../toast.js";
import { number, bytes, plural } from "../format.js";
import { pageHeading, notice, scanButton } from "./common.js";
import { ago } from "../shell.js";

export const title = "Overview";

function stat({ iconName, label, value, detail, accent, action }) {
  return h("div", { class: "stat" },
    h("div", { class: `stat__icon${accent ? " tone-warning" : " stat__icon--accent"}` }, icon(iconName)),
    h("div", { class: "stat__body" },
      h("div", { class: "stat__label" }, label),
      h("div", { class: "stat__figures" },
        h("span", { class: "stat__value mono" }, value),
        h("span", { class: "stat__detail" }, detail))),
    action);
}

export function mount(container) {
  const scanBtn = scanButton();
  const heading = pageHeading("Overview", scanBtn);
  const bannerEl = h("div", { class: "banners" });
  const statsEl = h("div", { class: "stats" });
  const trackersEl = h("ul", { class: "tracker-list" });
  const scanEl = h("div", { class: "scan-facts" });
  container.append(h("div", { class: "page" }, heading, bannerEl, statsEl,
    h("div", { class: "page__section overview-grid" },
      h("section", { class: "panel", "aria-labelledby": "by-tracker" },
        h("div", { class: "panel__head" },
          h("h2", { class: "panel__title", id: "by-tracker" }, "Seeding by tracker"),
          h("span", { class: "hint" }, "Seeding torrents in qBittorrent")),
        trackersEl),
      h("section", { class: "panel", "aria-labelledby": "last-scan" },
        h("div", { class: "panel__head" }, h("h2", { class: "panel__title", id: "last-scan" }, "Last scan")),
        scanEl))));

  async function makeTarget(host, add) {
    const current = store.get("overview")?.targets || [];
    const next = add ? [...current, host] : [host];
    try {
      await api.put("/settings", { target_trackers: next.join(", ") });
      store.set("overview", await api.get("/overview"));
      toast(`${host} is ${add ? "now also" : "now"} the target.`, "success");
    } catch (e) { toast(e.message, "danger"); }
  }

  function render(o) {
    if (!o) { replace(statsEl, h("p", { class: "muted stat" }, "Loading…")); return; }

    const banners = [];
    if (!o.connections.length) {
      banners.push(notice("info", "Start in ", h("a", { class: "link", href: "/settings" }, "Settings"), ": connect qBittorrent and at least one Radarr or Sonarr."));
    } else if (!o.has_scan && !o.scan.running) {
      banners.push(notice("info", "No scan yet. Press Scan now to read qBittorrent and your libraries."));
    }
    if (o.has_scan && !o.targets.length) {
      banners.push(notice("warning", "No target tracker chosen. Pick one below with ", h("strong", {}, "Make target"), ", or in ", h("a", { class: "link", href: "/settings?section=target" }, "Settings"), "."));
    }
    if (o.scan.error) banners.push(notice("danger", `The last scan failed: ${o.scan.error}`));
    for (const e of o.errors || []) {
      const name = e.source === "qbittorrent" ? "qBittorrent" : (o.connections.find((c) => c.id === e.source) || {}).name || e.source;
      banners.push(notice("danger", h("strong", {}, name), `: ${e.message}`));
    }
    const d = o.diagnostics || {};
    if (o.has_scan && d.library_files && d.library_files_on_disk === 0) {
      banners.push(notice("warning", "None of your library files are visible inside this container, so matching falls back to file size. Mount your data share, or add a path mapping in ",
        h("a", { class: "link", href: "/settings?section=paths" }, "Settings → Paths"), ". Looked for: ", h("span", { class: "mono" }, d.example_missing_path || "?")));
    }
    replace(bannerEl, banners);

    const t = o.totals;
    const target = (o.trackers || []).filter((r) => r.is_target);
    const targetSize = target.reduce((n, r) => n + r.size, 0);
    const targetCount = target.reduce((n, r) => n + r.count, 0);
    const allSize = (o.trackers || []).reduce((n, r) => n + r.size, 0);
    replace(statsEl,
      stat({ iconName: "tower-broadcast", label: "On target tracker", value: o.has_scan ? bytes(targetSize) : "—",
        detail: o.has_scan ? `${plural(targetCount, "torrent")} · ${allSize ? ((targetSize / allSize) * 100).toFixed(1) : "0.0"}% of all seeding` : "Not scanned" }),
      stat({ iconName: "film", label: "Movies not on target", value: t ? number(t.movies.need) : "—",
        detail: t ? `${bytes(t.movies.need_size)} · ${number(t.movies.on_target)} of ${number(t.movies.total)} on target` : "", accent: !!t?.movies.need,
        action: t?.movies.need ? h("a", { class: "btn btn--tertiary btn--sm stat__action", href: "/titles" }, "Review", icon("arrow-right")) : null }),
      stat({ iconName: "tv", label: "Seasons without a target pack", value: t ? number(t.seasons.need) : "—",
        detail: t ? `${bytes(t.seasons.need_size)} · ${number(t.seasons.on_target)} of ${number(t.seasons.total)} on target` : "", accent: !!t?.seasons.need,
        action: t?.seasons.need ? h("a", { class: "btn btn--tertiary btn--sm stat__action", href: "/titles?type=series" }, "Review", icon("arrow-right")) : null }));

    const max = Math.max(1, ...(o.trackers || []).map((r) => r.size));
    replace(trackersEl, (o.trackers || []).length ? o.trackers.map((r) => h("li", { class: `tracker-row${r.is_target ? " is-target" : ""}` },
      h("div", { class: "tracker-row__line" },
        h("span", { class: "tracker-row__host mono" }, r.host),
        r.is_target ? h("span", { class: "status status--success" }, "Target") : null,
        h("span", { class: "tracker-row__figures mono" }, `${bytes(r.size)} · ${number(r.count)}`,
          r.stopped ? h("span", { class: "tone-warning", title: `${bytes(r.stopped_size)} not seeding` }, ` · ${number(r.stopped)} stopped`) : null)),
      h("div", { class: "tracker-row__bar", "aria-hidden": "true" }, h("span", { style: `width:${(r.size / max) * 100}%` })),
      !r.is_target && r.host !== "(no tracker)" ? h("div", { class: "tracker-row__actions" },
        h("button", { type: "button", class: "btn btn--tertiary btn--sm", onclick: () => makeTarget(r.host, false) }, "Make target"),
        o.targets.length ? h("button", { type: "button", class: "btn btn--tertiary btn--sm", title: "For trackers with more than one announce host", onclick: () => makeTarget(r.host, true) }, "Add as target") : null) : null))
      : h("li", { class: "activity-empty" }, o.has_scan ? "No torrents in qBittorrent." : "Scan to see where your torrents seed."));

    if (!o.has_scan) { replace(scanEl, h("p", { class: "muted" }, o.scan.running ? "Scanning…" : "Never.")); return; }
    const fact = (label, value, hint) => h("div", { class: "scan-fact" }, h("span", { class: "label" }, label), h("span", { class: "mono" }, value), hint ? h("span", { class: "hint" }, hint) : null);
    const matched = (d.matched_inode || 0) + (d.matched_size || 0);
    replace(scanEl,
      fact("Finished", ago(o.scanned_at), `took ${o.duration}s · v${o.version}${o.next_scan_at ? "" : " · automatic scans off"}`),
      fact("Torrents", number(d.torrents_total), `${number(d.torrents_on_disk)} read from disk, ${number(d.torrents_api_only)} by size only`),
      fact("Library files", number(d.library_files), `${number(d.library_files_on_disk)} visible in this container`),
      fact("Linked to a torrent", number(matched), `${number(d.matched_inode)} by hardlink, ${number(d.matched_size)} by size, ${number(d.unmatched)} without a torrent`));
  }

  render(store.get("overview"));
  const off = store.subscribe("overview", render);
  api.get("/overview").then((o) => store.set("overview", o)).catch((e) => replace(bannerEl, notice("danger", e.message)));
  return () => { off(); scanBtn.cleanup?.(); };
}
