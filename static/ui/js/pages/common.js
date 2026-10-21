import { h } from "../dom.js";
import { icon } from "../icons.js";
import { openMenu } from "../shell.js";
import { api } from "../api.js";
import { store } from "../store.js";
import { toast } from "../toast.js";

/** H1 row with the mobile menu button. The h1 is focusable so route changes can move focus to it. */
export function pageHeading(title, actions) {
  return h("div", { class: "page-heading" },
    h("div", { class: "page-heading__title" },
      h("button", { type: "button", class: "btn btn--tertiary btn--square menu-button", "aria-label": "Open menu", onclick: openMenu }, icon("bars")),
      h("h1", { tabindex: "-1" }, title)),
    actions ? h("div", { class: "page-heading__actions" }, actions) : null);
}

export function notice(tone, ...children) {
  return h("div", { class: `notice notice--${tone}`, role: tone === "danger" ? "alert" : "status" },
    icon(tone === "danger" || tone === "warning" ? "triangle-exclamation" : "circle-info", "icon notice__icon"),
    h("div", { class: "notice__body" }, children));
}

/** "Scan now" button that reflects the running scan. */
export function scanButton(cls = "btn--primary") {
  const btn = h("button", { type: "button", class: `btn ${cls}`, onclick: async () => {
    btn.disabled = true;
    try {
      const r = await api.post("/scan", {});
      store.set("scan", r.scan);
      toast("Scan started.", "info");
    } catch (e) { toast(e.message, "danger"); btn.disabled = false; }
  } }, icon("arrows-rotate"), "Scan now");
  const paint = (s) => { btn.disabled = !!s?.running; btn.lastChild.textContent = s?.running ? "Scanning…" : "Scan now"; };
  paint(store.get("scan"));
  const off = store.subscribe("scan", paint);
  btn.cleanup = off;
  return btn;
}

export const STATUS = {
  on_target: { label: "On target", tone: "success", icon: "circle-check" },
  singles: { label: "On target as singles", tone: "info", icon: "circle-info" },
  partial: { label: "Partly on target", tone: "info", icon: "circle-info" },
  target_stopped: { label: "On target, but not seeding", tone: "warning", icon: "circle-xmark" },
  missing: { label: "Not on target", tone: "warning", icon: "triangle-exclamation" },
  not_seeding: { label: "Not seeding", tone: "danger", icon: "ban" },
};
