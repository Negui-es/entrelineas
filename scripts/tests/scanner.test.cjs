const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const vm = require('node:vm');
const source = readFileSync(resolve(__dirname, '../../static/scanner.js'), 'utf8');

class Element {
  constructor() { this.events = {}; this.dataset = {}; this.hidden = false; this.value = ''; this.open = false; }
  addEventListener(type, fn) { (this.events[type] ||= []).push(fn); }
  emit(type, event = {}) { for (const fn of this.events[type] || []) fn({target: this, ...event}); }
  setAttribute(name, value) { this[name] = value; }
  showModal() { this.open = true; }
  close() { this.open = false; this.emit('close'); }
  focus() { this.focused = true; }
  click() { this.clicked = true; this.emit('click'); }
  pause() {}
  play() { this.played = true; return Promise.resolve(); }
  requestSubmit() { this.submissions = (this.submissions || 0) + 1; }
  getBoundingClientRect() { return this.box || {left: 0, top: 0, width: 600, height: 600, right: 600, bottom: 600}; }
}
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

function setup(options = {}) {
  const ids = ['scanner-dialog', 'scan-open', 'barcode-video', 'scanner-viewport', 'scanner-guide', 'scanner-live',
    'scanner-state', 'scan-state-title', 'scan-spinner', 'scan-state-icon', 'scan-status', 'scan-retry',
    'barcode-photo', 'scan-close', 'scan-manual', 'scan-photo', 'catalog-query', 'catalog-mode', 'catalog-search-form'];
  if (options.manual) ids.push('manual-isbn-form', 'manual-isbn');
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const video = elements['barcode-video'];
  Object.assign(video, {videoWidth: 1920, videoHeight: 1080, readyState: 2});
  elements['scanner-viewport'].box = {left: 10, top: 20, width: 600, height: 400};
  elements['scanner-guide'].box = {left: 70, top: 130, width: 480, height: 180};
  const track = new Element();
  track.stop = () => { track.stops = (track.stops || 0) + 1; };
  const stream = {getTracks: () => [track], getVideoTracks: () => [track]};
  const calls = {media: [], crops: [], revoked: []};
  const document = new Element();
  Object.assign(document, {hidden: false, body: {classList: {add() {}, remove() {}}},
    getElementById: id => elements[id] || null,
    createElement: () => ({getContext: () => ({drawImage: (...args) => calls.crops.push(args)})})});
  let code = options.code || '9788418690600';
  const window = new Element();
  window.isSecureContext = true;
  window.ZXingBrowser = {BrowserMultiFormatOneDReader: class {
    decodeFromCanvas() { return {getText: () => code}; }
    decodeFromImageUrl() { return options.photoResult || Promise.resolve({getText: () => code}); }
  }};
  const tasks = new Map(); let taskId = 0;
  const context = {document, window, gettext: value => value, Date,
    navigator: {mediaDevices: {getUserMedia: constraints => {
      calls.media.push(constraints);
      return options.getMedia ? options.getMedia(stream) : Promise.resolve(stream);
    }}},
    URL: {createObjectURL: () => 'blob:test', revokeObjectURL: url => calls.revoked.push(url)},
    setTimeout: (fn, delay) => { tasks.set(++taskId, {fn, delay}); return taskId; },
    clearTimeout: id => tasks.delete(id)};
  vm.runInNewContext(source, context);
  return {elements, track, stream, calls, document, window,
    setCode(value) { code = value; },
    tick(delay) { const entry = [...tasks].find(([, task]) => task.delay === delay); if (entry) { tasks.delete(entry[0]); entry[1].fn(); } }};
}

test('opens directly with the rear camera and stops late permission grants after closing', async () => {
  let grant;
  const app = setup({getMedia: stream => new Promise(resolve => { grant = () => resolve(stream); })});
  app.elements['scan-open'].click();
  assert.equal(app.elements['scanner-dialog'].open, true);
  assert.equal(app.calls.media.length, 1);
  assert.equal(app.calls.media[0].audio, false);
  assert.equal(app.calls.media[0].video.facingMode.ideal, 'environment');
  app.elements['scan-close'].click();
  grant(); await settle();
  assert.equal(app.track.stops, 1);
  assert.equal(app.elements['barcode-video'].played, undefined);
  assert.equal(app.elements['scanner-dialog'].open, false);
});

test('only two agreeing valid ISBN frames submit; scanning matches the visible crop', async () => {
  const app = setup();
  app.elements['scan-open'].click(); await settle();
  assert.equal(app.elements['scanner-dialog'].dataset.state, 'active');
  assert.equal(app.elements['catalog-search-form'].submissions, undefined);
  const crop = app.calls.crops[0];
  assert.ok(Math.abs(crop[1] - 312) < .01);
  assert.ok(Math.abs(crop[2] - 297) < .01);
  assert.ok(Math.abs(crop[3] - 1296) < .01);
  assert.equal(crop[7], 1280);
  app.tick(150);
  assert.equal(app.elements['scanner-dialog'].dataset.state, 'success');
  assert.equal(app.track.stops, 1);
  app.tick(350);
  assert.equal(app.elements['catalog-query'].value, '9788418690600');
  assert.equal(app.elements['catalog-mode'].value, 'isbn');
  assert.equal(app.elements['catalog-search-form'].submissions, 1);
  app.tick(150); app.tick(350);
  assert.equal(app.elements['catalog-search-form'].submissions, 1);
});

test('rejects bad checksums and routes the same scan into manual ISBN lookup', async () => {
  const app = setup({manual: true, code: '9788418690601'});
  app.elements['scan-open'].click(); await settle();
  app.tick(150); app.tick(150);
  assert.equal(app.elements['manual-isbn-form'].submissions, undefined);
  app.setCode('9788418690600'); app.tick(150); app.tick(150); app.tick(350);
  assert.equal(app.elements['manual-isbn'].value, '9788418690600');
  assert.equal(app.elements['manual-isbn-form'].submissions, 1);
  assert.equal(app.elements['catalog-search-form'].submissions, undefined);
});

test('permission rejection leaves manual entry usable with no extra permission request', async () => {
  const app = setup({getMedia: () => Promise.reject({name: 'NotAllowedError'})});
  app.elements['scan-open'].click(); await settle();
  assert.equal(app.elements['scanner-dialog'].dataset.state, 'error');
  assert.equal(app.elements['scan-retry'].hidden, false);
  assert.match(app.elements['scan-status'].textContent, /No se ha permitido/);
  app.elements['catalog-query'].value = 'Un título';
  app.elements['scan-manual'].click();
  assert.equal(app.elements['catalog-query'].focused, true);
  assert.equal(app.elements['catalog-query'].value, '');
  assert.equal(app.elements['catalog-mode'].value, 'isbn');
  assert.equal(app.calls.media.length, 1);
});

test('backgrounding or Escape releases the camera and closes the modal', async () => {
  for (const action of ['background', 'escape']) {
    const app = setup(); app.elements['scan-open'].click(); await settle();
    if (action === 'background') { app.document.hidden = true; app.document.emit('visibilitychange'); }
    else app.elements['scanner-dialog'].emit('cancel', {preventDefault() {}});
    assert.equal(app.elements['scanner-dialog'].open, false);
    assert.equal(app.track.stops, 1);
    app.tick(150); app.tick(350);
    assert.equal(app.elements['catalog-search-form'].submissions, undefined);
  }
});

test('closing during photo decoding cancels submission and revokes the image URL', async () => {
  let finish;
  const result = new Promise(resolve => { finish = () => resolve({getText: () => '9788418690600'}); });
  const app = setup({photoResult: result});
  app.elements['scan-open'].click(); await settle();
  app.elements['scan-photo'].click();
  app.elements['barcode-photo'].files = [{type: 'image/jpeg', size: 1200}];
  app.elements['barcode-photo'].emit('change');
  app.elements['scan-close'].click(); finish(); await settle(); app.tick(350);
  assert.equal(app.elements['catalog-search-form'].submissions, undefined);
  assert.deepEqual(app.calls.revoked, ['blob:test']);
  assert.ok(app.track.stops >= 1);
});
