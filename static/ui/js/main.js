import { h } from "./dom.js";
import { defineRoutes, startRouter } from "./router.js";
import { buildShell, setActiveRoute, startPolling, closeMenu } from "./shell.js";

const root = document.getElementById("shell");
buildShell(root);

const main = h("main", { id: "main", class: "main", tabindex: "-1" });
root.append(main);

defineRoutes([
  { name: "overview", paths: ["/"], load: () => import("./pages/overview.js") },
  { name: "titles", paths: ["/titles"], load: () => import("./pages/titles.js") },
  { name: "history", paths: ["/history"], load: () => import("./pages/history.js") },
  { name: "settings", paths: ["/settings"], load: () => import("./pages/settings.js") },
  { name: "notfound", paths: [], fallback: true, load: () => import("./pages/notfound.js") },
], main, (name) => { setActiveRoute(name); closeMenu(); });

startPolling();
startRouter();
