"use strict";
(() => {
  const form = document.querySelector("[data-goodreads-form]");
  const idsElement = document.getElementById("goodreads-match-ids");
  if (!form || !idsElement) return;
  const ids = JSON.parse(idsElement.textContent);
  const button = form.querySelector("[data-goodreads-confirm]");
  const progress = document.querySelector("[data-goodreads-progress]");
  const heading = document.querySelector("[data-import-heading]");
  const summary = document.querySelector("[data-import-summary]");
  const meter = document.querySelector("[data-import-progress]");
  const counter = document.querySelector("[data-import-counter]");
  const percent = document.querySelector("[data-import-percent]");
  const current = document.querySelector("[data-import-current]");
  const processed = document.querySelector("[data-import-processed]");
  const titlesElement = document.getElementById("goodreads-match-titles");
  const titles = titlesElement ? JSON.parse(titlesElement.textContent) : [];
  document.querySelectorAll("[data-goodreads-id]").forEach(card => { card.hidden = true; });
  if (summary) summary.hidden = true;
  // A form control named "action" shadows HTMLFormElement.action.
  const endpoint = form.getAttribute("action") || window.location.href;
  button.disabled = true;
  let done = 0;
  let failed = 0;
  const updateProgress = number => {
    if (counter) counter.textContent = interpolate(gettext("%(current)s de %(total)s"), {current: number, total: ids.length}, true);
    if (meter) { meter.max = ids.length; meter.value = done; }
    if (percent) percent.textContent = `${Math.round(done / ids.length * 100)} %`;
    if (processed) processed.textContent = `${done} / ${ids.length}`;
  };
  form.addEventListener("submit", () => {
    button.textContent = gettext("Importando…");
    button.disabled = true;
  });
  const run = async () => {
    try {
      for (let index = 0; index < ids.length; index++) {
        updateProgress(index + 1);
        if (current) current.textContent = titles[index] || "";
        const cell = document.querySelector(`[data-goodreads-id="${ids[index]}"]`);
        let received = false;
        try {
          const body = new FormData(form);
          body.set("action", "match");
          body.set("index", String(index));
          const response = await fetch(endpoint, {method: "POST", body, credentials: "same-origin", headers: {"Accept": "application/json"}});
          if (response.status === 404 || response.status === 403 || response.redirected) throw new Error("Preview expired");
          if (!response.ok) { failed++; continue; }
          const match = await response.json();
          received = true;
          if (cell) {
            cell.querySelector("[data-match-label]").textContent = match.match_label;
            cell.querySelector("[data-match-details]").textContent = [match.match_title, match.match_isbn].filter(Boolean).join(" · ");
            const cover = cell.querySelector("[data-match-cover]");
            if (match.match_cover) { cover.src = match.match_cover; cover.hidden = false; }
            else { cover.removeAttribute("src"); cover.hidden = true; }
            cell.querySelector("[data-cover-fallback]").hidden = !match.match_cover_from_work;
          }
        } catch (error) {
          if (error.message === "Preview expired") throw error;
          failed++;
        } finally {
          if (!received && cell) cell.querySelector("[data-match-label]").textContent = gettext("No se ha podido completar la búsqueda externa");
          done++;
          if (cell) cell.hidden = false;
          updateProgress(done);
        }
      }
      progress.textContent = failed
        ? gettext("Algunas consultas han fallado. Se han buscado los demás libros; puedes conservar las coincidencias encontradas o volver a intentarlo.")
        : gettext("Búsqueda completada. Revisa las coincidencias antes de confirmar.");
    } catch (error) {
      progress.textContent = gettext("No se ha podido completar toda la búsqueda. Puedes importar con las coincidencias encontradas o volver a subir el archivo.");
    } finally {
      if (heading) heading.textContent = done === ids.length ? gettext("Listo para importar") : gettext("Revisa los resultados");
      if (current) current.textContent = "";
      if (summary) summary.hidden = false;
      button.disabled = false;
    }
  };
  run();
})();
