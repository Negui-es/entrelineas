import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

const source = await readFile(new URL('../deploy/cloudflare-worker.js', import.meta.url), 'utf8');
const { default: worker } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const request = (options = {}) => new Request('https://entrelineas.negui.es/buscar/?q=libro', {
  headers: { Accept: 'text/html', Cookie: 'sessionid=test-session' }, ...options,
});

test('App responses and their cookies, redirects and errors are untouched', async () => {
  for (const status of [200, 302, 404, 500, 503]) {
    const response = new Response('original application response', {
      status, headers: { 'Set-Cookie': 'sessionid=original; Secure; HttpOnly', Location: '/acceso/login/' },
    });
    globalThis.fetch = async (incoming, options) => {
      assert.equal(incoming.headers.get('Cookie'), 'sessionid=test-session');
      assert.equal(options.redirect, 'manual');
      return response;
    };
    assert.equal(await worker.fetch(request()), response);
  }
});

test('Tunnel and gateway failures return a complete, uncached 503 page', async () => {
  for (const status of [502, 504, 520, 521, 522, 523, 524, 525, 526, 530]) {
    globalThis.fetch = async () => new Response('upstream failure', { status });
    const response = await worker.fetch(request());
    assert.equal(response.status, 503);
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
    assert.equal(response.headers.get('Retry-After'), '60');
    const html = await response.text();
    assert.ok(html.includes('503 · Biblioteca en pausa'));
    assert.ok(html.includes('<style>') && html.includes('<script>'));
    assert.ok(!html.includes('href="/static/') && !html.includes('src="/static/'));
  }
});

test('Thrown connection errors do not disclose their details', async () => {
  globalThis.fetch = async () => { throw new Error('private network internals'); };
  const response = await worker.fetch(request());
  assert.equal(response.status, 503);
  assert.ok(!(await response.text()).includes('private network internals'));
});

test('A POST is sent once with its body, and is never retried', async () => {
  let calls = 0;
  globalThis.fetch = async (incoming) => {
    calls++;
    assert.equal(incoming.method, 'POST');
    assert.equal(await incoming.text(), 'title=Un+libro');
    throw new Error('lost connection after submission');
  };
  const response = await worker.fetch(request({ method: 'POST', body: 'title=Un+libro' }));
  assert.equal(calls, 1);
  assert.equal(response.status, 503);
  assert.ok((await response.text()).includes('comprueba el resultado cuando vuelva el servicio'));
});

test('JSON clients and assets receive JSON rather than an HTML document', async () => {
  globalThis.fetch = async () => new Response(null, { status: 502 });
  const response = await worker.fetch(request({ headers: { Accept: 'application/json' } }));
  assert.match(response.headers.get('Content-Type'), /application\/json/);
  assert.equal((await response.json()).error, 'service_unavailable');
});

test('HEAD returns the same status and headers without a response body', async () => {
  globalThis.fetch = async () => { throw new Error('offline'); };
  const response = await worker.fetch(request({ method: 'HEAD' }));
  assert.equal(response.status, 503);
  assert.equal(await response.text(), '');
});

test('Inline script and stylesheet match the restrictive CSP hashes', async () => {
  globalThis.fetch = async () => { throw new Error('offline'); };
  const response = await worker.fetch(request());
  const html = await response.text();
  const policy = response.headers.get('Content-Security-Policy');
  for (const tag of ['style', 'script']) {
    const content = html.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`))[1];
    const hash = createHash('sha256').update(content).digest('base64');
    assert.ok(policy.includes(`'sha256-${hash}'`));
  }
  assert.ok(!policy.includes('unsafe-inline'));
});

test('workers.dev is an isolated preview and HTTP redirects preserve the URL', async () => {
  globalThis.fetch = async () => { throw new Error('must not contact origin'); };
  const preview = await worker.fetch(new Request('https://example.workers.dev/', { headers: { Accept: 'text/html' } }));
  assert.equal(preview.status, 503);
  const redirect = await worker.fetch(new Request('http://entrelineas.negui.es/acceso/login/?next=%2F'));
  assert.equal(redirect.status, 308);
  assert.equal(redirect.headers.get('Location'), 'https://entrelineas.negui.es/acceso/login/?next=%2F');
});

test('Fallback prefers a supported URL prefix, then weighted browser languages', async () => {
  globalThis.fetch = async () => { throw new Error('offline'); };
  for (const [path, accept, code] of [
    ['/it/libri/1/', 'de-DE', 'it'], ['/en/library/', 'es', 'en'],
    ['/', 'ja,de-DE;q=0.9,en;q=0.5', 'de'], ['/', 'fr-CA,es;q=0.5', 'fr'],
    ['/', 'ja,zh', 'es'],
  ]) {
    const response = await worker.fetch(new Request('https://entrelineas.negui.es' + path, {
      headers: { Accept: 'text/html', 'Accept-Language': accept },
    }));
    assert.equal(response.headers.get('Content-Language'), code);
    assert.ok((await response.text()).includes(`lang="${code}"`));
  }
});

test('Every localized fallback has matching script and style hashes', async () => {
  globalThis.fetch = async () => { throw new Error('offline'); };
  for (const code of ['es', 'en', 'de', 'fr', 'it']) {
    const response = await worker.fetch(new Request(`https://entrelineas.negui.es/${code}/`, {
      headers: { Accept: 'text/html' },
    }));
    const html = await response.text();
    const policy = response.headers.get('Content-Security-Policy');
    for (const tag of ['style', 'script']) {
      const content = html.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`))[1];
      assert.ok(policy.includes(`'sha256-${createHash('sha256').update(content).digest('base64')}'`));
    }
    assert.ok(html.includes(`https://entrelineas.negui.es/${code}/`));
  }
});
