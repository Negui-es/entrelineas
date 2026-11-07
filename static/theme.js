"use strict";
(() => {
  const root = document.documentElement;
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  const apply = value => {
    const theme = ["light", "dark"].includes(value) ? value : "auto";
    root.dataset.theme = theme;
    const dark = theme === "dark" || (theme === "auto" && system.matches);
    document.querySelectorAll('meta[name="theme-color"]').forEach(meta => {
      meta.removeAttribute("media");
      meta.setAttribute("content", dark ? "#191724" : "#f6f5fb");
    });
  };
  apply(root.dataset.theme);
  document.querySelectorAll("[data-theme-select]").forEach(control => {
    control.addEventListener("change", () => apply(control.value));
  });
  system.addEventListener("change", () => apply(root.dataset.theme));
  // Keep the preview aligned with restored form controls after back navigation.
  window.addEventListener("pageshow", () => {
    const selected = document.querySelector("[data-theme-select]:checked") || document.querySelector("select[data-theme-select]");
    if (selected) apply(selected.value);
  });
})();
