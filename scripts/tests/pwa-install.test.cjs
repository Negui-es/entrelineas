const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const vm = require('node:vm');
const source = readFileSync(resolve(__dirname, '../../static/pwa.js'), 'utf8');

class Element {
  constructor(data = {}) { this.events = {}; this.dataset = data; this.open = false; }
  addEventListener(name, fn) { (this.events[name] ||= []).push(fn); }
  emit(name, event = {}) { return Promise.all((this.events[name] || []).map(fn => fn(event))); }
  showModal() { this.open = true; }
  close() { this.open = false; this.emit('close'); }
}
function setup({userAgent = 'Android Chrome', standalone = false, touch = 0} = {}) {
  const native = new Element(), open = new Element(), status = new Element(), close = new Element();
  const domain = new Element(), ios = new Element({installGuide: 'ios'}), android = new Element({installGuide: 'android'});
  const dialog = new Element(), window = new Element(), mode = new Element();
  mode.matches = standalone;
  dialog.querySelector = selector => ({'[data-install-native]': native, '[data-install-close]': close, '[data-install-domain]': domain})[selector];
  dialog.querySelectorAll = () => [ios, android];
  const document = {readyState: 'complete', getElementById: () => dialog,
    querySelectorAll: selector => selector === '[data-install-open]' ? [open] : [status],
    body: {classList: {add() {}, remove() {}}}};
  window.matchMedia = () => mode;
  vm.runInNewContext(source, {window, document, navigator: {userAgent, maxTouchPoints: touch}, location: {hostname: 'entrelineas.negui.es'}});
  return {native, open, status, ios, android, dialog, window};
}

test('Android only shows the native prompt after explicit install click, then recovers after dismissal', async () => {
  const app = setup(); let prompted = 0;
  await app.window.emit('beforeinstallprompt', {preventDefault() {}, prompt: async () => { prompted++; }, userChoice: Promise.resolve({outcome: 'dismissed'})});
  assert.equal(prompted, 0);
  await app.open.emit('click');
  assert.equal(app.dialog.open, true);
  assert.equal(app.native.hidden, false);
  await app.native.emit('click');
  assert.equal(prompted, 1);
  assert.equal(app.native.hidden, true);
  assert.equal(app.android.hidden, false);
  assert.equal(app.native.disabled, false);
});

test('iPhone and desktop-mode iPad get Safari instructions rather than a false install button', () => {
  for (const data of [{userAgent: 'iPhone Safari'}, {userAgent: 'Macintosh Safari', touch: 5}]) {
    const app = setup(data);
    assert.equal(app.ios.hidden, false);
    assert.equal(app.android.hidden, true);
    assert.equal(app.native.hidden, true);
  }
});

test('installed mode hides install actions and reports the installed state', async () => {
  const standalone = setup({standalone: true});
  assert.equal(standalone.open.hidden, true);
  assert.equal(standalone.status.hidden, false);
  const app = setup();
  await app.open.emit('click'); await app.window.emit('appinstalled');
  assert.equal(app.dialog.open, false);
  assert.equal(app.open.hidden, true);
  assert.equal(app.status.hidden, false);
});
