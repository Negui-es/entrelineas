// Exercise the shipped import script with DOM-shaped controls and mocked HTTP.
// No browser, network calls, accounts or real user files are used.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2] || "static/goodreads.js", "utf8");

async function scenario(responses, actionAttribute = null) {
  const button = {disabled: false};
  const progress = {textContent: ""};
  const controls = Object.fromEntries(["heading", "summary", "progress", "counter", "percent", "current", "processed"].map(name => [name, {textContent: "", hidden: false, value: 0}]));
  const listeners = {};
  const cells = Array.from({length: 3}, () => {
    const fields = Object.fromEntries(["label", "details", "cover", "fallback"].map(key => [key, {
      textContent: "", hidden: true, removeAttribute(name) { delete this[name]; },
    }]));
    return {fields, querySelector(selector) {
      return fields[{"[data-match-label]": "label", "[data-match-details]": "details",
        "[data-match-cover]": "cover", "[data-cover-fallback]": "fallback"}[selector]];
    }};
  });
  const form = {
    // Real HTML forms expose named inputs as properties, including .action.
    action: {name: "action", value: "confirm"},
    getAttribute(name) { assert.equal(name, "action"); return actionAttribute; },
    querySelector() { return button; },
    addEventListener(name, handler) { listeners[name] = handler; },
  };
  const document = {
    querySelector(selector) {
      if (selector === "[data-goodreads-form]") return form;
      if (selector === "[data-goodreads-progress]") return progress;
      const control = selector.match(/^\[data-import-(\w+)\]$/);
      if (control) return controls[control[1]];
      const cell = selector.match(/"(\d+)"/);
      return cell ? cells[Number(cell[1]) - 1] : null;
    },
    querySelectorAll() { return cells; },
    getElementById(id) { return {textContent: id === "goodreads-match-titles" ? '["Uno","Dos","Tres"]' : '["1","2","3"]'}; },
  };
  const calls = [];
  class FormData {
    constructor(target) { assert.equal(target, form); this.values = new Map([["csrfmiddlewaretoken", "test-csrf"], ["token", "test-preview"]]); }
    set(key, value) { this.values.set(key, value); }
    get(key) { return this.values.get(key); }
  }
  vm.runInNewContext(source, {document, FormData, window: {location: {href: "https://example.invalid/es/biblioteca/importar/goodreads/"}},
    gettext: text => text, interpolate: (text, values) => text.replace(/%\((\w+)\)s/g, (_, key) => values[key]),
    fetch: async (url, options) => {
      calls.push({url, options, completed: controls.progress.value, counter: controls.counter.textContent,
        visible: cells.filter(cell => !cell.hidden).length, summaryHidden: controls.summary.hidden});
      if (typeof url !== "string") throw new Error("Form action is a control, not a URL");
      const index = Number(options.body.get("index"));
      const status = responses[index] || 200;
      return {status, ok: status === 200, json: async () => ({match_label: "Edición encontrada por ISBN", match_title: "Libro",
        match_isbn: "9788408163435", match_cover: "https://covers.openlibrary.org/b/id/1-M.jpg", match_cover_from_work: true})};
    },
  });
  for (let i = 0; button.disabled && i < 20; i++) await new Promise(setImmediate);
  assert.equal(button.disabled, false, "Confirmation becomes available after matching");
  return {calls, cells, progress, controls, button, listeners};
}

(async () => {
  const normal = await scenario([]);
  assert.equal(normal.calls.length, 3, "Search every row");
  for (const [index, call] of normal.calls.entries()) {
    assert.equal(call.url, "https://example.invalid/es/biblioteca/importar/goodreads/", "Use the page URL despite the hidden action input");
    assert.equal(call.options.body.get("action"), "match");
    assert.equal(call.options.body.get("index"), String(index));
    assert.equal(call.options.body.get("csrfmiddlewaretoken"), "test-csrf");
    assert.equal(call.options.credentials, "same-origin");
    assert.equal(call.completed, index, "The bar advances only after processing a book");
    assert.equal(call.visible, index, "Cards appear progressively, never all at once");
    assert.equal(call.counter, `${index + 1} de 3`);
    assert.equal(call.summaryHidden, true);
    assert.equal(normal.cells[index].fields.cover.hidden, false);
    assert.match(normal.cells[index].fields.cover.src, /^https:\/\/covers\.openlibrary\.org/);
  }
  assert.match(normal.progress.textContent, /Búsqueda completada/);
  assert.equal(normal.controls.progress.value, 3);
  assert.equal(normal.controls.percent.textContent, "100 %");
  assert.equal(normal.controls.summary.hidden, false);
  assert.ok(normal.cells.every(cell => !cell.hidden));
  normal.listeners.submit();
  assert.equal(normal.button.disabled, true);
  assert.equal(normal.button.textContent, "Importando…");
  const partial = await scenario([503, 200, 200], "/explicit-import/");
  assert.equal(partial.calls.length, 3, "One failed row must not stop the remaining searches");
  assert.equal(partial.calls[0].url, "/explicit-import/");
  assert.match(partial.cells[0].fields.label.textContent, /No se ha podido/);
  assert.equal(partial.cells[1].fields.cover.hidden, false);
  assert.match(partial.progress.textContent, /Algunas consultas/);
  const expired = await scenario([403]);
  assert.equal(expired.calls.length, 1, "Stop when authentication or preview expires");
  assert.equal(expired.controls.progress.value, 1, "Interrupted work must not show fake completion");
  console.log("Goodreads frontend: endpoint, all rows, covers, CSRF, partial failures and expired preview verified.");
})().catch(error => { console.error(error); process.exitCode = 1; });
