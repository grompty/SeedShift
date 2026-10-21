import { h, replace } from "../dom.js";
import { icon } from "../icons.js";
import { api } from "../api.js";
import { bytes, timeAgo, plural } from "../format.js";
import { poll } from "../poller.js";
import { pageHeading, notice } from "./common.js";

export const title = "History";

// What happened after the grab, when "Replace my file after a grab" was on.
const REPLACE = {
  waiting: { tone: "info", icon: "clock-rotate-left", label: "Waiting for download" },
  downloading: { tone: "info", icon: "download", label: "Downloading" },
  importing: { tone: "info", icon: "arrows-rotate", label: "Importing" },
  replaced: { tone: "success", icon: "circle-check", label: "Replaced your file" },
  imported: { tone: "success", icon: "circle-check", label: "Imported" },
  blocked: { tone: "warning", icon: "triangle-exclamation", label: "Import blocked" },
  failed: { tone: "danger", icon: "circle-xmark", label: "Import failed" },
  lost: { tone: "neutral", icon: "circle-info", label: "Not followed" },
};

function when(iso) {
  const t = timeAgo(iso);
  return !t ? "" : t === "now" ? "just now" : /\d$/.test(t) ? t : `${t} ago`;
}

function row(e) {
  const name = e.kind === "season" ? `${e.title} · Season ${e.season}` : `${e.title}${e.year ? ` (${e.year})` : ""}`;
  const result = e.ok
    ? h("span", { class: "flag tone-success" }, icon("circle-check"), e.message || "Sent")
    : h("span", { class: "flag tone-danger" }, icon("circle-xmark"), e.message || "Failed");
  const rep = e.replace && REPLACE[e.replace.state];
  return h("li", { class: "trailer-row history-row" },
    h("div", { class: "trailer-row__title" },
      h("div", { class: "trailer-row__name" }, icon(e.kind === "season" ? "tv" : "film", "icon tone-neutral"), h("span", {}, name || e.key)),
      h("div", { class: "trailer-row__meta" }, [e.connection, e.via === "prowlarr" ? "via Prowlarr" : null, e.forced ? "forced" : null].filter(Boolean).join(" · "))),
    h("div", { class: "trailer-row__file" },
      h("div", { class: "mono trailer-row__path" }, e.release),
      h("div", { class: "trailer-row__flags" },
        e.quality ? h("span", { class: "muted" }, e.quality) : null,
        e.size ? h("span", { class: "mono muted" }, bytes(e.size)) : null,
        e.indexer ? h("span", { class: "muted" }, e.indexer) : null)),
    h("div", { class: "history-row__result" },
      h("time", { class: "mono muted history-row__time", datetime: e.ts, title: new Date(e.ts).toLocaleString() }, when(e.ts)),
      result,
      rep ? h("span", { class: `flag tone-${rep.tone}`, title: e.replace.message || "" }, icon(rep.icon), rep.label) : null,
      rep && e.replace.message && !["replaced", "imported"].includes(e.replace.state)
        ? h("span", { class: "hint history-row__why" }, e.replace.message) : null));
}

export function mount(container) {
  const bannerEl = h("div", { class: "banners" });
  const listEl = h("ul", { class: "trailer-list" });
  const footEl = h("div", { class: "trailer-foot" });
  container.append(h("div", { class: "page" }, pageHeading("History"), bannerEl,
    h("div", { class: "page__section" }, h("section", { class: "panel", "aria-label": "Grab history" },
      h("div", { class: "trailer-head history-head", "aria-hidden": "true" }, h("span", {}, "Title"), h("span", {}, "Release"), h("span", {}, "Result")),
      listEl, footEl))));

  async function load() {
    try {
      const r = await api.get("/history");
      replace(bannerEl);
      replace(listEl, r.entries.length ? r.entries.map(row)
        : h("li", { class: "activity-empty" }, "Nothing grabbed through Seedshift yet. Grabs from the Search window show up here."));
      replace(footEl, r.total ? h("span", { class: "muted" }, `${plural(r.total, "grab")} · the newest 500 are kept`) : null);
    } catch (e) { replace(bannerEl, notice("danger", e.message)); }
  }
  // Refresh while something is being followed, so states move along on their own.
  const p = poll(load, () => 20000);
  return () => p.stop();
}
