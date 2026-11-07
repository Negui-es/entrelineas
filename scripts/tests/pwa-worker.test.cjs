const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const vm = require('node:vm');
const config = {version: 'test', assets: ['/static/pwa/icon.png'],
  offline: {es: '/pwa/offline/es/', en: '/pwa/offline/en/'}, defaultLanguage: 'es'};
const source = readFileSync(resolve(__dirname, '../../static/pwa/worker.js'), 'utf8').replace('__PWA_CONFIG__', JSON.stringify(config));

function worker(fetcher = async () => new Response('Private response')) {
  const handlers = {}, additions = [], deletions = [];
  const cache = {addAll: async requests => additions.push(...requests),
    match: async request => new Response(String(typeof request === 'string' ? request : request.url))};
  const self = {location: {origin: 'https://entrelineas.negui.es'}, navigator: {language: 'en-GB'},
    clients: {claim: async () => {}}, addEventListener: (name, handler) => { handlers[name] = handler; }};
  const caches = {open: async () => cache, keys: async () => ['entrelineas-public-shell-old', 'unrelated-cache'],
    delete: async key => { deletions.push(key); }};
  vm.runInNewContext(source, {self, caches, Request, Response, URL, fetch: fetcher});
  return {handlers, additions, deletions,
    request(path, options = {}) {
      let response;
      handlers.fetch({request: {url: 'https://entrelineas.negui.es' + path, method: 'GET', mode: 'navigate', ...options},
        respondWith: value => { response = value; }});
      return response;
    }};
}

test('precaches only public shell assets without authentication credentials', async () => {
  const app = worker(); let done;
  app.handlers.install({waitUntil: value => { done = value; }}); await done;
  assert.equal(app.additions.length, 3);
  for (const request of app.additions) {
    assert.equal(request.credentials, 'omit');
    assert.match(request.url, /\/(static\/pwa|pwa\/offline)\//);
  }
});

test('private navigations always use network and are never added to cache', async () => {
  let calls = 0;
  const app = worker(async () => { calls++; return new Response('My private review'); });
  assert.equal(await (await app.request('/es/libros/17/')).text(), 'My private review');
  assert.equal(calls, 1);
  assert.equal(app.additions.length, 0);
});

test('offline navigation returns the correct language with no false save confirmation', async () => {
  const app = worker(async () => { throw new Error('Offline'); });
  const response = await app.request('/es/buscar/?q=private');
  assert.equal(response.status, 503);
  assert.equal(response.headers.get('Content-Language'), 'es');
  assert.equal(await response.text(), '/pwa/offline/es/');
  assert.equal((await app.request('/')).headers.get('Content-Language'), 'en');
});

test('POST, cross-origin requests and user images are not intercepted or queued', () => {
  const app = worker();
  assert.equal(app.request('/es/resenas/nueva/', {method: 'POST'}), undefined);
  assert.equal(app.request('/es/portadas/123/', {mode: 'no-cors'}), undefined);
  assert.equal(app.request('/', {url: 'https://another.example/'}), undefined);
});

test('application errors pass through and activation only removes owned older caches', async () => {
  const app = worker(async () => new Response('Application error', {status: 500}));
  assert.equal((await app.request('/es/')).status, 500);
  let done; app.handlers.activate({waitUntil: value => { done = value; }}); await done;
  assert.deepEqual(app.deletions, ['entrelineas-public-shell-old']);
});
