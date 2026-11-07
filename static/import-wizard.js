"use strict";
(() => {
  const confirmation = document.querySelector("[data-native-confirm]");
  if (confirmation) confirmation.addEventListener("submit", event => {
    const button = confirmation.querySelector("button[type=submit]");
    if (button.disabled) { event.preventDefault(); return; }
    button.disabled = true;
    button.textContent = gettext("Importando…");
    confirmation.setAttribute("aria-busy", "true");
  });
  if (confirmation) window.addEventListener("pageshow", event => {
    if (!event.persisted) return;
    const button = confirmation.querySelector("button[type=submit]");
    button.disabled = false;
    button.textContent = gettext("Confirmar importación");
    confirmation.setAttribute("aria-busy", "false");
  });
  const root = document.querySelector("[data-import-wizard]");
  if (!root) return;
  const form = root.querySelector("[data-wizard-form]");
  const radios = [...form.querySelectorAll('input[name="source"]')];
  const file = form.querySelector('input[type="file"]');
  const error = root.querySelector("[data-file-error]");
  const dropzone = root.querySelector("[data-dropzone]");
  const back = root.querySelector("[data-wizard-back]");
  const submit = root.querySelector("[data-upload-submit]");
  const importSteps = document.querySelector("[data-import-steps]");
  const exportSteps = document.querySelector("[data-export-steps]");
  const importStages = ["source", "file", "loading"];
  let busy = false;
  const selected = () => radios.find(radio => radio.checked);
  const show = (step, focus = true) => {
    root.dataset.wizardStage = step;
    form.hidden = !importStages.includes(step);
    if (importSteps) importSteps.hidden = !importStages.includes(step);
    const reassurance = document.querySelector("[data-import-reassurance]");
    if (reassurance) reassurance.hidden = !importStages.includes(step);
    if (exportSteps) exportSteps.hidden = !["export", "exporting", "exported"].includes(step);
    root.querySelectorAll("[data-wizard-step]").forEach(screen => {
      screen.hidden = screen.dataset.wizardStep !== step;
      if (!screen.hidden && focus) screen.querySelector("[data-step-heading]").focus();
    });
    document.querySelectorAll("[data-flow-step]").forEach(item => {
      const index = ["source", "file", "review"].indexOf(item.dataset.flowStep);
      const current = step === "source" ? 0 : 1;
      item.classList.toggle("is-active", index === current);
      item.classList.toggle("is-done", index < current);
      if (index === current) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    });
    document.querySelectorAll("[data-export-flow]").forEach(item => {
      const done = step === "exported";
      const active = !done && item.dataset.exportFlow === (step === "exporting" ? "exported" : "export");
      item.classList.toggle("is-active", active);
      item.classList.toggle("is-done", done || step === "exporting" && item.dataset.exportFlow === "export");
      if (active) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    });
    root.querySelectorAll("[data-platform-help]").forEach(help => {
      help.hidden = help.dataset.platformHelp !== selected()?.value;
    });
    const title = root.querySelector("[data-upload-heading]");
    if (selected()) title.textContent = interpolate(gettext("Añade tu archivo de %(platform)s"), {
      platform: selected().value === "goodreads" ? "Goodreads" : "Entrelíneas"
    }, true);
    root.setAttribute("aria-busy", ["loading", "exporting"].includes(step) ? "true" : "false");
  };
  root.querySelectorAll("[data-transfer-action]").forEach(link => link.addEventListener("click", event => {
    event.preventDefault();
    if (!busy) show(link.dataset.transferAction === "import" ? "source" : "export");
  }));
  root.querySelectorAll("[data-wizard-home]").forEach(link => link.addEventListener("click", event => {
    event.preventDefault();
    if (!busy) show("direction");
  }));
  const exportLink = root.querySelector("[data-export-download]");
  const exportError = root.querySelector("[data-export-error]");
  if (exportLink) exportLink.addEventListener("click", async event => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    exportError.hidden = true;
    show("exporting");
    try {
      const response = await fetch(exportLink.href, {credentials: "same-origin"});
      if (!response.ok || response.redirected || !response.headers.get("Content-Type")?.includes("text/csv")) throw new Error("export");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const download = document.createElement("a");
      const filename = response.headers.get("Content-Disposition")?.match(/filename="([A-Za-z0-9._-]+)"/);
      download.href = url;
      download.download = filename ? filename[1] : "entrelineas.csv";
      download.hidden = true;
      document.body.append(download);
      download.click();
      download.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      show("exported");
    } catch {
      show("export");
      exportError.textContent = gettext("No hemos podido preparar el archivo. Comprueba tu conexión o vuelve a iniciar sesión e inténtalo de nuevo.");
      exportError.hidden = false;
    } finally {
      busy = false;
    }
  });
  const clearError = () => { error.hidden = true; error.textContent = ""; file.removeAttribute("aria-invalid"); };
  const fail = message => {
    error.textContent = message;
    error.hidden = false;
    file.setAttribute("aria-invalid", "true");
    file.value = "";
    file.focus();
  };
  const choosePlatform = () => {
    if (busy || root.dataset.wizardStage !== "source") return;
    file.value = "";
    clearError();
    show("file");
  };
  radios.forEach(radio => {
    radio.addEventListener("change", choosePlatform);
    radio.addEventListener("click", choosePlatform);
  });
  back.addEventListener("click", () => {
    if (busy) return;
    clearError();
    show("source");
  });
  const readFile = () => {
    if (busy || !file.files.length) return;
    clearError();
    const chosen = file.files[0];
    if (!/\.csv$/i.test(chosen.name)) return fail(gettext("Elige un archivo CSV exportado desde la plataforma que has seleccionado."));
    if (chosen.size > 5 * 1024 * 1024) return fail(gettext("El archivo supera el límite de 5 MB."));
    if (!chosen.size) return fail(gettext("El archivo está vacío. Prueba con otra exportación."));
    form.requestSubmit();
  };
  file.addEventListener("change", readFile);
  for (const type of ["dragenter", "dragover"]) dropzone.addEventListener(type, event => {
    event.preventDefault();
    if (!busy) dropzone.classList.add("is-dragging");
  });
  dropzone.addEventListener("dragleave", event => {
    if (!dropzone.contains(event.relatedTarget)) dropzone.classList.remove("is-dragging");
  });
  dropzone.addEventListener("drop", event => {
    event.preventDefault();
    dropzone.classList.remove("is-dragging");
    if (busy) return;
    if (event.dataTransfer.files.length !== 1) return fail(gettext("Añade un solo archivo cada vez."));
    file.files = event.dataTransfer.files;
    readFile();
  });
  form.addEventListener("submit", event => {
    if (busy) { event.preventDefault(); return; }
    if (!form.checkValidity()) { event.preventDefault(); form.reportValidity(); return; }
    busy = true;
    submit.disabled = true;
    show("loading");
  });
  root.classList.add("wizard-ready");
  back.hidden = false;
  submit.hidden = true;
  show(root.dataset.initialStage || (selected() ? "file" : "source"), false);
  window.addEventListener("pageshow", event => {
    if (!event.persisted) return;
    busy = false;
    submit.disabled = false;
    file.value = "";
    show(root.dataset.initialStage || (selected() ? "file" : "source"), false);
  });
})();
