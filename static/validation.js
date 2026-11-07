"use strict";

// Keep native constraints and server validation, replacing only browser popups.
(() => {
  let nextId = 0;
  const errors = new WeakMap();
  const controls = form => Array.from(form.elements).filter(field => field.willValidate);
  const describe = (field, id, add) => {
    const ids = new Set((field.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
    if (add) ids.add(id); else ids.delete(id);
    if (ids.size) field.setAttribute("aria-describedby", Array.from(ids).join(" "));
    else field.removeAttribute("aria-describedby");
  };
  const message = field => {
    const state = field.validity;
    if (state.valueMissing) return field.type === "checkbox"
      ? gettext("Marca esta casilla para continuar.")
      : field.type === "radio" || field.tagName === "SELECT"
        ? gettext("Selecciona una opción.") : gettext("Completa este campo.");
    if (state.typeMismatch) return field.type === "email"
      ? gettext("Introduce un email válido.") : gettext("Introduce una dirección web válida.");
    if (state.tooShort) return interpolate(gettext("Escribe al menos %(limit)s caracteres."), {limit: field.minLength}, true);
    if (state.tooLong) return interpolate(gettext("Usa como máximo %(limit)s caracteres."), {limit: field.maxLength}, true);
    if (state.rangeUnderflow) return interpolate(gettext("Introduce un valor igual o superior a %(limit)s."), {limit: field.min}, true);
    if (state.rangeOverflow) return interpolate(gettext("Introduce un valor igual o inferior a %(limit)s."), {limit: field.max}, true);
    if (state.badInput || state.stepMismatch) return gettext("Introduce un número válido.");
    return gettext("Revisa el formato de este campo.");
  };
  const clear = field => {
    const error = errors.get(field);
    if (!error) return;
    describe(field, error.id, false);
    field.removeAttribute("aria-invalid");
    errors.delete(field);
    // Radio buttons can share one field error.
    if (!Array.from(field.form?.elements || []).some(other => errors.get(other) === error)) error.remove();
  };
  const show = field => {
    const container = field.closest(".field");
    let error = errors.get(field) || container?.querySelector("[data-client-error]");
    if (!error) {
      error = document.createElement("div");
      error.id = `validation-error-${++nextId}`;
      error.className = "field-errors client-error";
      error.dataset.clientError = "";
      error.setAttribute("aria-live", "polite");
      if (container) container.append(error);
      else field.insertAdjacentElement("afterend", error);
    }
    error.textContent = message(field);
    errors.set(field, error);
    field.setAttribute("aria-invalid", "true");
    describe(field, error.id, true);
  };
  document.querySelectorAll("form").forEach(form => {
    if (form.noValidate) return;
    // With JavaScript unavailable, the browser still validates normally.
    form.noValidate = true;
    controls(form).forEach(field => {
      const serverError = field.closest(".field")?.querySelector(".field-errors");
      if (serverError) {
        if (!serverError.id) serverError.id = `validation-error-${++nextId}`;
        errors.set(field, serverError);
        field.setAttribute("aria-invalid", "true");
        describe(field, serverError.id, true);
      }
    });
    form.addEventListener("submit", event => {
      if (event.submitter?.formNoValidate) return;
      const invalid = controls(form).filter(field => !field.validity.valid);
      controls(form).filter(field => field.validity.valid).forEach(clear);
      if (!invalid.length) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      invalid.forEach(show);
      invalid[0].focus();
    }, true);
    const update = event => {
      const field = event.target;
      if (!field.willValidate) return;
      const related = field.type === "radio"
        ? controls(form).filter(other => other.type === "radio" && other.name === field.name) : [field];
      related.forEach(other => {
        if (!errors.has(other)) return;
        clear(other);
        other.closest(".field")?.classList.remove("invalid");
        if (!other.validity.valid) show(other);
      });
    };
    form.addEventListener("input", update);
    form.addEventListener("change", update);
    form.addEventListener("reset", () => controls(form).forEach(clear));
    form.addEventListener("invalid", event => {
      event.preventDefault();
      show(event.target);
    }, true);
  });
})();
