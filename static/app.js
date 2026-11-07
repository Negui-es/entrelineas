"use strict";
function initializeCovers(root) {
root.querySelectorAll(".catalog-cover-image").forEach(image => {
  const setCover = visible => {
    image.hidden = !visible;
    image.closest(".book-cover").classList.toggle("has-image", visible);
    image.closest(".book-card")?.querySelectorAll("[data-cover-reason]").forEach(reason => { reason.hidden = !visible; });
    image.closest(".detail-page")?.querySelectorAll("[data-cover-upload]").forEach(action => { action.hidden = visible; });
  };
  const fallback = () => setCover(false);
  image.addEventListener("error", fallback);
  image.addEventListener("load", () => setCover(image.naturalWidth > 1 && image.naturalHeight > 1));
  if (image.complete) setCover(image.naturalWidth > 1 && image.naturalHeight > 1);
});
}
initializeCovers(document);
document.querySelectorAll("[data-confirm]").forEach(form => {
  form.addEventListener("submit", event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
const copyTimers = new WeakMap();

document.querySelectorAll("[data-copy]").forEach(button => {
  button.addEventListener("click", async () => {
    const field = document.getElementById(button.dataset.copy);
    const status = button.closest(".sharing-panel").querySelector(".copy-status");
    clearTimeout(copyTimers.get(status));
    try {
      await navigator.clipboard.writeText(field.value);
      status.textContent = gettext("Enlace copiado.");
      copyTimers.set(status, setTimeout(() => { status.textContent = ""; }, 6000));
    } catch {
      field.focus();
      field.select();
      status.textContent = gettext("Selecciona y copia el enlace con el menú de tu navegador.");
    }
  });
});

(() => {
  const form = document.querySelector("[data-search-form]");
  if (!form) return;
  const button = form.querySelector("[data-search-submit]");
  const status = document.getElementById("catalog-search-status");
  const results = document.getElementById("catalog-results");
  const message = status.querySelector("[data-search-message]");
  const messages = [
    gettext("Desempolvando estanterías imaginarias…"),
    gettext("Preguntando al bibliotecario de los libros perdidos…"),
    gettext("Siguiendo un rastro de marcapáginas…"),
    gettext("Buscando entre dragones y primeras ediciones…"),
    gettext("Un momento: este libro se ha escondido detrás de otro."),
    gettext("Convenciendo a los libros de que se ordenen solos…"),
    gettext("Consultando al consejo de lectores nocturnos…"),
    gettext("Abriendo puertas a otros mundos… con cuidado."),
    gettext("El catálogo está pasando de capítulo…"),
    gettext("Separando los títulos de los giros de guion…"),
    gettext("Persiguiendo una portada que nos suena mucho…"),
    gettext("Poniéndonos las gafas de encontrar historias…"),
    gettext("No es una pausa dramática. Bueno, un poco sí."),
    gettext("Revisando debajo del montón de libros pendientes…"),
    gettext("Este catálogo tiene más pasillos de los que parecía."),
    gettext("Pidiendo indicaciones a un personaje secundario…"),
    gettext("Desenredando títulos con nombres larguísimos…"),
    gettext("Buscando tu próxima excusa para leer hasta tarde…"),
    gettext("Haciendo sitio en tu mesita de noche… mentalmente."),
    gettext("Comprobando que no se haya escapado a una secuela…"),
    gettext("Leyendo los lomos sin torcer demasiado el cuello…"),
    gettext("Un libro nunca llega tarde: crea suspense."),
    gettext("Los puntos suspensivos también necesitan protagonismo…"),
    gettext("Consultando el índice del universo lector…"),
    gettext("Buscando una historia con la que perder la noción del tiempo…"),
    gettext("Intentando no distraernos con la contraportada…"),
    gettext("Alineando estrellas, letras y algún ISBN…"),
    gettext("Por aquí huele a papel y a una buena historia."),
    gettext("Nuestro marcapáginas está haciendo de brújula…"),
    gettext("Ya sabemos qué diría un libro: pasa la página."),
  ];
  let messageTimer = null;
  let messageAnimation = null;
  let messageBag = [];
  let previousMessage = null;
  const showMessage = () => {
    if (!messageBag.length) {
      messageBag = [...messages];
      for (let i = messageBag.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [messageBag[i], messageBag[j]] = [messageBag[j], messageBag[i]];
      }
      if (messageBag[messageBag.length - 1] === previousMessage) {
        [messageBag[0], messageBag[messageBag.length - 1]] = [messageBag[messageBag.length - 1], messageBag[0]];
      }
    }
    previousMessage = messageBag.pop();
    message.textContent = previousMessage;
    messageAnimation?.cancel();
    if (message.animate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      messageAnimation = message.animate([
        {opacity: 0, transform: "translateY(6px)"},
        {opacity: 1, transform: "translateY(0)"},
      ], {duration: 350, easing: "ease-out"});
    }
  };
  let searching = false;

  const reset = () => {
    searching = false;
    clearInterval(messageTimer);
    messageTimer = null;
    messageAnimation?.cancel();
    messageAnimation = null;
    message.textContent = "";
    button.disabled = false;
    results.hidden = false;
    results.setAttribute("aria-busy", "false");
    status.hidden = true;
    form.removeAttribute("aria-busy");
  };
  // Validation runs in the capture phase, so invalid searches never look busy.
  form.addEventListener("submit", event => {
    if (event.defaultPrevented) return;
    if (searching) {
      event.preventDefault();
      return;
    }
    searching = true;
    button.disabled = true;
    results.hidden = true;
    results.setAttribute("aria-busy", "true");
    status.hidden = false;
    showMessage();
    messageTimer = setInterval(showMessage, 3000);
    form.setAttribute("aria-busy", "true");
    // Keep inputs enabled so the browser submits title/ISBN, mode and source.
  });
  window.addEventListener("pageshow", reset);
  window.addEventListener("pagehide", reset);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && searching) reset();
  });
})();

// Keep normal page links as the fallback; enhance only the personal panels.
(() => {
  const grid = document.querySelector("[data-panel-grid]");
  const pagination = document.querySelector("[data-panel-pagination]");
  const controls = pagination?.querySelector("[data-load-controls]");
  if (!grid || !controls || !("IntersectionObserver" in window)) return;
  const links = pagination.querySelector("[data-page-links]");
  const button = controls.querySelector("[data-load-more]");
  const status = controls.querySelector("[data-load-status]");
  const mobile = window.matchMedia("(max-width: 720px)");
  const initialNext = links.querySelector('[rel="next"]')?.getAttribute("href");
  const initialCards = new Set(grid.children);
  let next = initialNext;
  let loading = false;
  let controller;

  const observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) loadMore();
  }, { rootMargin: "0px 0px 350px 0px" });

  async function loadMore() {
    if (loading || !next || !mobile.matches) return;
    loading = true;
    observer.disconnect();
    button.disabled = true;
    status.textContent = gettext("Cargando…");
    grid.setAttribute("aria-busy", "true");
    const requestController = new AbortController();
    controller = requestController;
    try {
      const response = await fetch(next, {
        signal: requestController.signal,
        credentials: "same-origin",
        headers: { "Accept": "text/html" },
      });
      if (!response.ok || response.redirected) throw new Error("Page unavailable");
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      if (requestController.signal.aborted) return;
      const incoming = page.querySelector("[data-panel-grid]");
      const paging = page.querySelector("[data-panel-pagination]");
      if (!incoming || !paging) throw new Error("Invalid panel response");
      const cards = Array.from(incoming.children);
      if (!cards.length || cards.some(card => !card.matches(".book-card"))) throw new Error("Invalid cards");
      const fragment = document.createDocumentFragment();
      cards.forEach(card => fragment.append(document.importNode(card, true)));
      initializeCovers(fragment);
      grid.append(fragment);
      next = paging.querySelector('[rel="next"]')?.getAttribute("href");
      button.hidden = !next;
      status.textContent = next ? "" : gettext("Has llegado al final.");
      if (next) observer.observe(controls);
    } catch (error) {
      if (error.name !== "AbortError") {
        status.textContent = gettext("No se han podido cargar más resultados. Pulsa para reintentar.");
      }
    } finally {
      if (controller === requestController) {
        loading = false;
        button.disabled = false;
        grid.removeAttribute("aria-busy");
      }
    }
  }

  function setMode() {
    observer.disconnect();
    controller?.abort();
    controller = null;
    loading = false;
    grid.removeAttribute("aria-busy");
    // Restore the original page when returning to the desktop pagination.
    Array.from(grid.children).forEach(card => {
      if (!initialCards.has(card)) card.remove();
    });
    next = initialNext;
    button.disabled = false;
    button.hidden = !next;
    status.textContent = next ? "" : gettext("Has llegado al final.");
    links.hidden = mobile.matches;
    controls.hidden = !mobile.matches;
    if (mobile.matches && next) observer.observe(controls);
  }

  button.addEventListener("click", loadMore);
  mobile.addEventListener("change", setMode);
  setMode();
})();
