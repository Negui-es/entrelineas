"use strict";
document.querySelectorAll("[data-toast]").forEach(toast => {
  const region = toast.parentElement;
  let remaining = 6000;
  let started = 0;
  let timer = null;
  let hovered = false;
  let closed = false;
  const automatic = Number(toast.dataset.level) < 30;
  const pause = () => {
    if (timer === null) return;
    clearTimeout(timer);
    remaining = Math.max(0, remaining - (performance.now() - started));
    timer = null;
  };
  const visibilityChanged = () => document.hidden ? pause() : resume();
  const dismiss = () => {
    if (closed) return;
    closed = true;
    pause();
    document.removeEventListener("visibilitychange", visibilityChanged);
    toast.remove();
    if (!region.querySelector("[data-toast]")) region.remove();
  };
  const resume = () => {
    if (!automatic || closed || timer !== null || hovered || document.hidden || toast.contains(document.activeElement)) return;
    started = performance.now();
    timer = setTimeout(dismiss, remaining);
  };
  toast.querySelector("[data-toast-close]").addEventListener("click", dismiss);
  toast.addEventListener("mouseenter", () => { hovered = true; pause(); });
  toast.addEventListener("mouseleave", () => { hovered = false; resume(); });
  toast.addEventListener("focusin", pause);
  toast.addEventListener("focusout", () => queueMicrotask(resume));
  document.addEventListener("visibilitychange", visibilityChanged);
  resume();
});
