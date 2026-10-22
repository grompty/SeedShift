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

/** "…/Pack.Folder/Show.S01E01.mkv" -> "Pack.Folder/Show.S01E01.mkv": enough to see where a file is. */
const fileName = (p) => String(p).split(/[\\/]/).filter(Boolean).slice(-2).join("/");

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
    const where = h("p", { class: "hint" }, job.via_folder ? "Sonarr read the pack's folder: " : "Sonarr couldn't read the pack's folder, so it was asked by download ID instead: ",
      h("span", { class: "mono" }, job.folder));
    const skippedList = job.skipped ? h("details", { class: "file-paths", open: !c.length },
      h("summary", {}, `${plural(job.skipped, "file")} in the pack skipped`),
      h("ul", { class: "path-list" }, job.skipped_files.map((s) => h("li", {},
        h("span", { class: "mono" }, fileName(s.path) || "?"), " ", h("span", { class: "hint" }, s.reason))))) : null;
    if (!c.length) {
      head.push(notice("info", job.already && !job.skipped
        ? "Every episode Sonarr found in the pack is already imported from it. Run a scan if the season still shows as partly on target."
        : job.already
          ? `${plural(job.already, "episode")} already come from the pack. Sonarr couldn't use the other files; the reasons are below.`
          : "Sonarr didn't match any file in the pack to an episode of this season. The reasons are below."));
      replace(bodyEl, head, where, skippedList);
      return;
    }
    head.push(h("p", { class: "hint hint--lead" },
      `Sonarr imports the ticked episodes from the pack and replaces your current files. The pack's files are hardlinked or copied, never moved, so the torrent keeps seeding.`));
    if (c.some((x) => x.lower)) head.push(notice("warning", "Sonarr rates some of your current files higher than the pack's, by quality or custom format score. They're unticked, so they stay unless you tick them. ",
      c.some((x) => x.score) ? "If you import them anyway, Sonarr may later look for an upgrade again, unless the pack's score meets your profile's upgrade cutoff." : ""));
    if (c.some((x) => x.same)) head.push(notice("warning", "For some episodes, Sonarr reads the pack's file as the same quality and group you already have. They're unticked. Check the file names below before you import them."));
    head.push(where);

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
          for (const i of x.together.length ? x.together : [x.index]) { if (e.target.checked) picked.add(i); else picked.delete(i); }
          if (x.together.length) { render(); return; }
          all.checked = picked.size === c.length;
          all.indeterminate = picked.size > 0 && picked.size < c.length;
          paintButton();
        } }),
        h("span", { class: "mono import-row__ep" }, x.episode || "?")),
      h("div", { class: "import-row__from" },
        x.current ? [h("span", {}, release(x.current)), h("span", { class: "hint" }, x.current.source)] : h("span", { class: "hint" }, "Not in your library"),
        x.current_path ? h("span", { class: "import-row__path mono", title: x.current_path }, fileName(x.current_path)) : null,
        x.together.length ? h("span", { class: "hint import-row__path" }, `One file for ${x.together.map((i) => c[i].episode).join(" + ")} now. They're imported together.`) : null),
      icon("arrow-right", "icon tone-neutral"),
      h("div", { class: "import-row__to" },
        h("span", {}, release(x.new)),
        x.score ? h("span", { class: "flag tone-warning", title: "Sonarr's custom format score for the pack's file vs yours" },
          icon("triangle-exclamation"), `Lower score: ${x.score.new} vs your ${x.score.current}`)
          : x.lower ? h("span", { class: "flag tone-warning" }, icon("triangle-exclamation"), "Lower quality") : null,
        x.same ? h("span", { class: "flag tone-warning" }, icon("triangle-exclamation"), "Same as you have") : null,
        x.path ? h("span", { class: "import-row__path mono", title: x.path }, fileName(x.path)) : null)));

    replace(bodyEl, head,
      h("div", { class: "import-head" }, h("label", { class: "checkline" }, all, "All episodes"),
        job.already ? h("span", { class: "hint" }, `${plural(job.already, "episode")} already from the pack`) : null),
      h("ul", { class: "import-list" }, rows), skippedList);
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
