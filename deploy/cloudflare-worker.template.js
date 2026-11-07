// Entrelíneas: attach as a Route entrelineas.negui.es/* in zone negui.es.
// Keep the existing proxied Tunnel DNS record. Do not attach as a Custom Domain.
const APP_HOST = "entrelineas.negui.es";
const ORIGIN_FAILURES = new Set([502, 504, 520, 521, 522, 523, 524, 525, 526, 530]);
const OFFLINE_PAGES = /* GENERATED_PAGES */;

function language(request) {
  const prefix = new URL(request.url).pathname.split("/")[1];
  if (Object.hasOwn(OFFLINE_PAGES, prefix)) return prefix;
  const candidates = (request.headers.get("Accept-Language") || "").split(",").map(part => {
    const [tag, ...options] = part.trim().toLowerCase().split(";");
    const quality = options.find(value => value.trim().startsWith("q="));
    return { code: tag.split("-")[0], q: quality ? Number(quality.trim().slice(2)) : 1 };
  }).filter(item => item.q > 0 && item.q <= 1 && Object.hasOwn(OFFLINE_PAGES, item.code));
  candidates.sort((a, b) => b.q - a.q);
  return candidates[0]?.code || "es";
}

function unavailable(request) {
  const code = language(request);
  const page = OFFLINE_PAGES[code];
  const acceptsHTML = (request.headers.get("Accept") || "").toLowerCase().includes("text/html") ||
    request.headers.get("Sec-Fetch-Dest") === "document";
  const headers = new Headers({
    "Content-Type": acceptsHTML ? "text/html; charset=utf-8" : "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "CDN-Cache-Control": "no-store",
    "Cloudflare-CDN-Cache-Control": "no-store",
    "Retry-After": "60",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": page.csp,
    "Content-Language": code,
    "Vary": "Accept, Sec-Fetch-Dest, Accept-Language",
  });
  const unsafe = !["GET", "HEAD", "OPTIONS"].includes(request.method);
  let body = acceptsHTML ? page.html : JSON.stringify({
    error: "service_unavailable",
    message: page.message,
    retry_after: 60,
    ...(unsafe ? { notice: page.write_notice } : {}),
  });
  if (acceptsHTML && unsafe) {
    body = body.replace('id="offline-write-warning" hidden', 'id="offline-write-warning"');
  }
  return new Response(request.method === "HEAD" ? null : body, { status: 503, headers });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    // workers.dev and editor previews show the fallback without contacting an origin.
    if (url.hostname !== APP_HOST) return unavailable(request);
    if (url.protocol !== "https:") {
      url.protocol = "https:";
      return new Response(null, { status: 308, headers: { Location: url.toString(), "Cache-Control": "no-store" } });
    }
    try {
      // With a Route, this goes to the existing Tunnel origin, not back to this Worker.
      // Preserve method, body, cookies and headers; never automatically repeat writes.
      const response = await fetch(request, { redirect: "manual" });
      // Django's 404, 500 and catalogue 503 pages pass through unchanged.
      if (!ORIGIN_FAILURES.has(response.status)) return response;
      if (response.body) await response.body.cancel().catch(() => {});
      return unavailable(request);
    } catch (_) {
      return unavailable(request);
    }
  },
};
