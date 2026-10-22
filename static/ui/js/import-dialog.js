import { h, replace } from "./dom.js";
import { icon } from "./icons.js";
import { api } from "./api.js";
import { plural } from "./format.js";
import { toast } from "./toast.js";
import { createDialog } from "./dialog.js";

function notice(tone, ...children) {
  return h("div", { class: `notice notice--${tone}`, role: tone === "danger" ? "alert" : "status" },
    icon(tone === "danger" || tone === "warning" ? "triangle-exclamation" : "circle-info", "icon notice__icon"),
    h("div", { class: "notice__body" }, children));
}

const release = (q) => [q.quality, q.group].filter(Boolean).join(" · ") || "unknown";

/** Finish import: tick the episodes Sonarr should import from the target pack, replacing the current files. */
export function openFinishImport(item, onDone) {
  const d = createDialog({ title: `Finish import · ${item.title} · Season ${item.season}`, subtitle: "Asking Sonarr what's in the pack…", size: "lg" });
  const bodyEl = h("div", { class: "stack" }, h("p", { class: "files__loading muted" }, "Asking Sonarr which episodes it can import from the pack…"));
  const err = h("div", {});
  const go = h("button", { type: "button", class: "btn btn--danger-solid", disabled: true }, icon("list-check"), "Import");
  d.body.append(bodyEl, err);
  d.footer.append(h("span", {}), h("div", { class: "dialog__actions" },
    h("button", { type: "button", class: "btn btn--tertiary", onclick: d.close }, "Cancel"), go));

  let job = null;
  const picked = new Set();

  function paintButton() {
    go.disabled = !picked.size;
    replace(go, icon("list-check"), picked.size ? `Import ${plural(picked.size, "episode")}` : "Import");
  }

  function render() {
    d.setHeading(`Finish import · ${item.title} · Season ${item.season}`, job.pack.name);
    const c = job.candidates;
    const head = [];
    if (!c.length) {
      head.push(notice("info", job.already
        ? "Every episode Sonarr found in the pack is already imported from it. Run a scan if the season still shows as partly on target."
        : "Sonarr didn't match any file in the pack to an episode of this season. Check the pack in Sonarr's Manual Import."));
      replace(bodyEl, head);
      return;
    }
    head.push(h("p", { class: "hint hint--lead" },
      `Sonarr imports the ticked episodes from the pack and replaces your current files. The pack's files are hardlinked or copied, never moved, so the torrent keeps seeding.`));
    if (c.some((x) => x.lower)) head.push(notice("warning", "Some of your current files are better than the pack's. They're unticked, so they stay unless you tick them."));
    if (job.via_folder) head.push(h("p", { class: "hint" }, "Sonarr doesn't track this torrent as one of its downloads, so it reads the pack's folder instead."));

    const all = h("input", { type: "checkbox", "aria-label": "All episodes", onchange: (e) => {
      picked.clear();
      if (e.target.checked) c.forEach((x) => picked.add(x.index));
      render();
    } });
    all.checked = picked.size === c.length;
    all.indeterminate = picked.size > 0 && picked.size < c.length;

    const rows = c.map((x) => h("li", { class: `import-row${x.lower ? " is-lower" : ""}` },
      h("label", { class: "import-row__pick" },
        h("input", { type: "checkbox", checked: picked.has(x.index), onchange: (e) => {
          if (e.target.checked) picked.add(x.index); else picked.delete(x.index);
          all.checked = picked.size === c.length;
          all.indeterminate = picked.size > 0 && picked.size < c.length;
          paintButton();
        } }),
        h("span", { class: "mono import-row__ep" }, x.episode || "?")),
      h("div", { class: "import-row__from" },
        x.current ? [h("span", {}, release(x.current)), h("span", { class: "hint" }, x.current.source)] : h("span", { class: "hint" }, "Not in your library")),
      icon("arrow-right", "icon tone-neutral"),
      h("div", { class: "import-row__to" },
        h("span", {}, release(x.new)),
        x.lower ? h("span", { class: "flag tone-warning" }, icon("triangle-exclamation"), "Lower quality") : null)));

    replace(bodyEl, head,
      h("div", { class: "import-head" }, h("label", { class: "checkline" }, all, "All episodes"),
        job.already ? h("span", { class: "hint" }, `${plural(job.already, "episode")} already from the pack`) : null),
      h("ul", { class: "import-list" }, rows));
    paintButton();
  }

  go.onclick = async () => {
    go.disabled = true; replace(err);
    try {
      const r = await api.post("/import", { id: job.id, indices: [...picked] });
      toast(`${r.message} Follow it on the History page.`, "success");
      d.close();
      onDone?.();
    } catch (e) { replace(err, notice("danger", e.message)); go.disabled = false; }
  };

  api.post("/import/preview", { key: item.key }).then((r) => {
    job = r.import;
    job.candidates.filter((x) => x.checked).forEach((x) => picked.add(x.index));
    render();
  }).catch((e) => { d.setHeading(`Finish import · ${item.title} · Season ${item.season}`, ""); replace(bodyEl, notice("danger", e.message)); });
}
