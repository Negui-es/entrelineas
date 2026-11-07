"use strict";
(() => {
  const dialog = document.getElementById("install-dialog");
  if (!dialog) return;
  const nativeButton = dialog.querySelector("[data-install-native]");
  const mode = window.matchMedia("(display-mode: standalone)");
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
  const platform = ios ? "ios" : /Android/.test(navigator.userAgent) ? "android" : "other";
  let pending = null, installedHere = false;
  const installed = () => installedHere || mode.matches || navigator.standalone === true;
  function update() {
    const done = installed();
    document.querySelectorAll("[data-install-open]").forEach(button => { button.hidden = done; });
    document.querySelectorAll("[data-install-status]").forEach(status => { status.hidden = !done; });
    nativeButton.hidden = !pending || done;
    dialog.querySelectorAll("[data-install-guide]").forEach(guide => {
      guide.hidden = Boolean(pending) || (platform !== "other" && guide.dataset.installGuide !== platform);
    });
    dialog.querySelector("[data-install-domain]").hidden = location.hostname === "entrelineas.negui.es";
    if (done && dialog.open) dialog.close();
  }
  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    pending = event;
    update();
  });
  window.addEventListener("appinstalled", () => { installedHere = true; pending = null; update(); });
  mode.addEventListener?.("change", update);
  document.querySelectorAll("[data-install-open]").forEach(button => button.addEventListener("click", () => {
    update();
    if (!installed() && !dialog.open) {
      dialog.showModal();
      document.body.classList.add("install-open");
    }
  }));
  dialog.addEventListener("close", () => document.body.classList.remove("install-open"));
  dialog.querySelector("[data-install-close]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", event => {
    const box = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
  });
  nativeButton.addEventListener("click", async () => {
    if (!pending) return;
    const event = pending;
    pending = null;
    nativeButton.disabled = true;
    try {
      await event.prompt();
      if ((await event.userChoice).outcome === "accepted") dialog.close();
    } catch { /* Browser menu instructions remain available when the prompt cannot open. */ }
    finally { nativeButton.disabled = false; update(); }
  });
  update();
  if ("serviceWorker" in navigator && window.isSecureContext) {
    const register = () => navigator.serviceWorker.register("/service-worker.js", {scope: "/", updateViaCache: "none"}).catch(() => {});
    if (document.readyState === "complete") register();
    else window.addEventListener("load", register, {once: true});
  }
})();
