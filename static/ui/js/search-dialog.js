import { h, replace } from "./dom.js";
import { icon } from "./icons.js";
import { api } from "./api.js";
import { bytes, plural } from "./format.js";
import { toast } from "./toast.js";
import { createDialog } from "./dialog.js";
import { store } from "./store.js";

/** "3h", "5d", "4mo", "2y" from hours. */
function age(hours) {
  const hrs = Number(hours || 0);
  if (hrs < 48) return `${Math.max(1, Math.round(hrs))}h`;
  const days = hrs / 24;
  if (days < 60) return `${Math.round(days)}d`;
  if (days < 730) return `${Math.round(days / 30)}mo`;
  return `${Math.round(days / 365)}y`;
}

function notice(tone, ...children) {
  return h("div", { class: `notice notice--${tone}`, role: tone === "danger" ? "alert" : "status" },
    icon(tone === "danger" || tone === "warning" ? "triangle-exclamation" : "circle-info", "icon notice__icon"),
    h("div", { class: "notice__body" }, children));
}

/** Interactive search for one title, limited to the target indexers. */
export function openSearch(item) {
  const arr = item.kind === "movie" ? "Radarr" : "Sonarr";
  const label = item.kind === "season" ? `${item.title} · Season ${item.season}` : `${item.title}${item.year ? ` (${item.year})` : ""}`;
  const d = createDialog({ title: `Search · ${label}`, subtitle: "Starting…", size: "lg" });
  const bodyEl = h("div", { class: "stack stack--tight" });
  const footLeft = h("span", { class: "hint" });
  d.body.append(bodyEl);
  d.footer.append(footLeft, h("div", { class: "dialog__actions" }, h("button", { type: "button", class: "btn btn--tertiary", onclick: d.close }, "Close")));

  let job = null;
  let timer = null;
  let closed = false;
  let showSingles = false;
  d.el.addEventListener("close", () => { closed = true; clearTimeout(timer); });

  function subtitle() {
    const via = job.via === "prowlarr" ? "via Prowlarr" : `via ${arr}`;
    const where = job.indexers.length ? job.indexers.join(", ") : "target";
    if (job.status === "running") return `${where} · ${via} · searching… ${job.elapsed}s`;
    if (job.status === "error") return `${where} · ${via}`;
    const shown = showSingles || item.kind !== "season" ? job.results.length : job.results.filter((r) => r.full_season !== false).length;
    return `${where} · ${via} · ${plural(shown, item.kind === "season" && !showSingles ? "season pack" : "result")}`;
  }

  function resultCard(r) {
    const flags = [];
    if (r.in_client) flags.push(h("span", { class: "flag tone-warning", title: "A torrent with this name is in qBittorrent" }, icon("triangle-exclamation"), "Already in qBittorrent"));
    if (r.same_release) flags.push(h("span", { class: "flag tone-info" }, icon("circle-info"), "Possible match"));
    if (r.rejected) flags.push(h("span", { class: "flag tone-warning" }, icon("triangle-exclamation"), r.rejections[0] || `${arr} would reject it`));
    const button = r.grabbed
      ? h("span", { class: "status status--success" }, r.grabbed)
      : h("button", { type: "button", class: `btn btn--sm ${r.rejected ? "btn--secondary btn--warn" : "btn--primary"}`, onclick: () => confirmGrab(r) },
          icon("download"), r.rejected ? "Force grab" : "Grab");
    return h("li", { class: "release" },
      h("div", { class: "release__title mono" }, r.title),
      h("div", { class: "release__meta" },
        r.quality ? h("span", { class: "chip" }, r.quality) : null,
        h("span", { class: "mono" }, bytes(r.size)),
        r.seeders != null ? h("span", { class: "tone-success", title: "Seeders" }, icon("arrow-up"), String(r.seeders)) : null,
        r.cf_score != null ? h("span", { class: "muted", title: "Custom format score" }, `CF ${r.cf_score > 0 ? "+" : ""}${r.cf_score}`) : null,
        h("span", { class: "muted", title: "Age" }, age(r.age_hours)),
        job.indexers.length > 1 ? h("span", { class: "muted" }, r.indexer) : null,
        r.info_url ? h("a", { class: "link", href: r.info_url, target: "_blank", rel: "noopener noreferrer", title: "Open on the tracker" }, icon("arrow-up-right-from-square")) : null),
      r.rejections.length > 1 ? h("details", { class: "release__why" }, h("summary", {}, `${r.rejections.length} reasons`),
        h("ul", {}, r.rejections.map((x) => h("li", {}, x)))) : null,
      h("div", { class: "release__foot" }, h("div", { class: "release__flags" }, flags), button));
  }

  function render() {
    d.setHeading(`Search · ${label}`, subtitle());
    if (job.status === "running") {
      replace(bodyEl, h("p", { class: "files__loading muted" }, job.via === "prowlarr"
        ? "Asking the target through Prowlarr…" : `${arr} is searching every indexer. This can take a minute.`));
      replace(footLeft);
      return;
    }
    if (job.status === "error") {
      const settingsLink = /Settings/.test(job.error) ? h("a", { class: "link", href: "/settings?section=target", onclick: () => d.close() }, " Open settings") : null;
      replace(bodyEl, notice("danger", job.error, settingsLink));
      replace(footLeft);
      return;
    }
    const all = job.results;
    const singles = item.kind === "season" ? all.filter((r) => r.full_season === false) : [];
    const shown = showSingles ? all : all.filter((r) => r.full_season !== false);
    const head = [];
    if (job.warning) head.push(notice("warning", job.warning));
    if (job.guessed) head.push(notice("info", `Searching ${job.indexers.join(", ")} because its address matches the target. `,
      h("a", { class: "link", href: "/settings?section=target", onclick: () => d.close() }, "Choose the target indexer")));
    if (job.via === "arr" && all.some((r) => r.rejected)) head.push(h("p", { class: "hint" }, `Force grab downloads it even though ${arr} would normally skip it. If it isn't an upgrade, ${arr} won't import it automatically; finish it with Manual Import.`));
    if (singles.length) head.push(h("label", { class: "checkline" },
      h("input", { type: "checkbox", checked: showSingles, onchange: (e) => { showSingles = e.target.checked; render(); } }),
      `Show ${plural(singles.length, "single-episode result")}`));
    replace(bodyEl, head, shown.length ? h("ul", { class: "releases" }, shown.map(resultCard))
      : h("p", { class: "files__loading muted" }, all.length ? "Only single episodes found. Tick the box above to see them."
        : "Nothing found on the target. Try the tracker's own site, or ignore this title."));
    replace(footLeft, job.hidden ? `${plural(job.hidden, "result")} from other indexers hidden` : "");
  }

  function confirmGrab(r) {
    const c = createDialog({ title: r.rejected ? "Force grab?" : `Send to ${arr}?`, size: "sm", role: "alertdialog", tone: r.rejected ? "danger" : null });
    const err = h("div", {});
    const lines = [h("p", { class: "mono release__title" }, r.title),
      h("p", { class: "hint hint--lead" }, `${arr} downloads it (${bytes(r.size)}) to qBittorrent with its usual category and tags.`)];
    lines.push(h("p", { class: "hint" }, "Downloading this counts against your ratio on the target, unless it's freeleech."));
    if (job.auto_replace) lines.push(notice("warning", "When it's downloaded, it replaces your current file."));
    if (r.in_client) lines.push(notice("warning", "This release is already in qBittorrent, so qBittorrent will most likely refuse it as a duplicate.",
      item.kind === "season" ? " If its episodes aren't in your library, use Finish import in Details instead." : ""));
    if (r.same_release) lines.push(notice("info", "This might be the release you already have. Worth a quick check before you grab it."));
    if (r.rejected) lines.push(notice("warning", `${arr} would normally skip it: ${r.rejections.join("; ")}.`));
    if (job.via === "prowlarr") lines.push(h("p", { class: "hint" }, `${arr} checks it against your profile first and can still refuse it.`));
    c.body.append(...lines, err);
    const go = h("button", { type: "button", class: `btn ${r.rejected ? "btn--danger-solid" : "btn--primary"}`, onclick: async () => {
      go.disabled = true; replace(err);
      try {
        const res = await api.post("/grab", { search_id: job.id, index: r.index });
        r.grabbed = res.message;
        store.set("grabbed", Date.now()); // pages showing the Grabbed tag reload
        toast(`${res.message} ${r.title}`, "success");
        c.close();
        render();
      } catch (e) { replace(err, notice("danger", e.message)); go.disabled = false; }
    } }, icon("download"), r.rejected ? "Force grab" : "Grab");
    c.footer.append(h("span", {}), h("div", { class: "dialog__actions" }, h("button", { type: "button", class: "btn btn--tertiary", onclick: c.close }, "Cancel"), go));
  }

  async function poll() {
    try {
      job = (await api.get(`/search/${job.id}`)).search;
    } catch (e) { job = { ...job, status: "error", error: e.message }; }
    if (closed) return;
    render();
    if (job.status === "running") timer = setTimeout(poll, 1500);
  }

  api.post("/search", { key: item.key }).then((r) => {
    if (closed) return;
    job = r.search;
    render();
    if (job.status === "running") timer = setTimeout(poll, 1000);
  }).catch((e) => {
    job = { status: "error", error: e.message, via: "", indexers: [], results: [], elapsed: 0 };
    render();
  });
}
