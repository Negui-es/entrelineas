from django.utils.translation import gettext_lazy as _
"""Cached catalogue clients. Never accepts a remote URL from a visitor."""
import hashlib
import json
import logging
import re
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, connections
from django.utils.html import strip_tags

logger = logging.getLogger("library.catalog")


def _failure_details(error):
    """Technical causes only: never log URLs, queries, bodies or credentials."""
    causes, details, seen = [], {}, set()
    while isinstance(error, BaseException) and id(error) not in seen:
        seen.add(id(error))
        causes.append(type(error).__name__)
        if isinstance(error, HTTPError):
            details["http_status"] = error.code
            retry = error.headers.get("Retry-After", "") if error.headers else ""
            if retry.isdigit():
                details["retry_after_seconds"] = retry
        if isinstance(error, OSError) and error.errno is not None:
            details["errno"] = error.errno
        if isinstance(error, ssl.SSLCertVerificationError):
            details["tls_verify_code"] = error.verify_code
            details["tls_verify_message"] = error.verify_message
        if isinstance(error, OSError) and getattr(error, "winerror", None) is not None:
            details["winerror"] = error.winerror
        if error.__traceback__:
            trace = error.__traceback__
            while trace.tb_next:
                trace = trace.tb_next
            details["location"] = f"{trace.tb_frame.f_code.co_name}:{trace.tb_lineno}"
        error = error.reason if isinstance(error, URLError) and isinstance(error.reason, BaseException) else error.__cause__
    return {"causes": " > ".join(causes), **details}

EDITION_ID = re.compile(r"OL[0-9]{1,12}M\Z")
WORK_KEY = re.compile(r"/works/OL[0-9]{1,12}W\Z")
SEARCH_FIELDS = ",".join([
    "key", "title", "author_name", "cover_i", "first_publish_year", "editions",
    "editions.key", "editions.title", "editions.isbn", "editions.language",
    "editions.cover_i",
])


class CatalogError(Exception):
    pass


def normalize_isbn(value):
    value = re.sub(r"[\s-]", "", str(value)).upper()
    if re.fullmatch(r"[0-9]{9}[0-9X]", value):
        digits = [10 if c == "X" else int(c) for c in value]
        if sum((10 - i) * n for i, n in enumerate(digits)) % 11 == 0:
            return value
    if re.fullmatch(r"97[89][0-9]{10}", value):
        if sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value)) % 10 == 0:
            return value
    return ""


def clean_text(value, maximum=200):
    if isinstance(value, dict):
        value = value.get("value", "")
    return strip_tags(value).strip()[:maximum] if isinstance(value, str) else ""


def positive_int(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if 0 < number <= 2_147_483_647 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _request(path, params=None, provider="openlibrary"):
    base = {"openlibrary": "https://openlibrary.org", "inventaire": "https://inventaire.io/api",
            "bne": "https://catalogo.bne.es/view/sru/34BNE_INST",
            "bookbrainz": "https://api.bookbrainz.org/1", "boktyven": "https://boktyven.no/api/v1"}[provider]
    url = base + path
    if params:
        url += "?" + urlencode(params)
    token = settings.BOKTYVEN_API_TOKEN if provider == "boktyven" else ""
    if provider == "boktyven" and not token:
        logger.warning("catalog_configuration_failed provider=boktyven reason=missing_token")
        raise CatalogError(_("Boktyven necesita un token de acceso configurado en el servidor."))
    key = "catalog:" + hashlib.sha256((url + token).encode()).hexdigest()
    existing = cache.get(key)
    if existing is not None:
        return existing
    cooldown = f"catalog:{provider}:retry-after"
    retry_at = cache.get(cooldown, 0)
    if retry_at > time.time():
        logger.warning("catalog_request_skipped provider=%s reason=rate_limit_cooldown remaining_seconds=%d", provider, retry_at - time.time())
        raise CatalogError(_("El catálogo está recibiendo muchas consultas. Prueba dentro de un momento."))
    # Rate limiting is shared between processes through Django's database cache.
    # Even with an identified User-Agent we keep the conservative 1 req/s limit.
    deadline = time.monotonic() + 3
    lock = f"catalog:{provider}:reservation-lock"
    reservation = f"catalog:{provider}:next-request"
    while not cache.add(lock, True, timeout=5):
        if time.monotonic() > deadline:
            logger.warning("catalog_request_failed provider=%s reason=reservation_lock_timeout wait_seconds=3", provider)
            raise CatalogError(_("Hay otra búsqueda en curso. Vuelve a intentarlo en unos segundos."))
        time.sleep(.1)
    try:
        wait = max(0, cache.get(reservation, 0) - time.time())
        time.sleep(min(wait, 1.1))
        cache.set(reservation, time.time() + 1.1, timeout=5)
    finally:
        cache.delete(lock)
    headers = {"User-Agent": settings.CATALOG_USER_AGENT, "Accept": "application/xml" if provider == "bne" else "application/json"}
    if token:
        headers["X-Access-Token"] = token
    request = Request(url, headers=headers)
    started = time.monotonic()
    try:
        with urlopen(request, timeout=8) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                logger.warning("catalog_request_failed provider=%s reason=response_too_large limit_bytes=2000000", provider)
                raise CatalogError(_("La respuesta del catálogo es demasiado grande. Prueba una búsqueda más concreta."))
            data = body.decode("utf-8") if provider == "bne" else json.loads(body)
        if provider != "bne" and not isinstance(data, dict):
            raise ValueError(_("Unexpected catalog response"))
    except HTTPError as error:
        if error.code == 404:
            data = {}
        elif error.code == 429:
            retry = error.headers.get("Retry-After", "") if error.headers else ""
            delay = min(86400, max(1, int(retry))) if retry.isdigit() else 60
            cache.set(cooldown, time.time() + delay, timeout=delay)
            logger.warning("catalog_request_failed provider=%s host=%s elapsed_ms=%d timeout_seconds=8 details=%s", provider, urlsplit(base).hostname, (time.monotonic() - started) * 1000, _failure_details(error))
            raise CatalogError(_("El catálogo está recibiendo muchas consultas. Prueba dentro de un momento.")) from error
        else:
            logger.warning("catalog_request_failed provider=%s host=%s elapsed_ms=%d timeout_seconds=8 details=%s", provider, urlsplit(base).hostname, (time.monotonic() - started) * 1000, _failure_details(error))
            raise CatalogError(_("El catálogo no está disponible ahora. Puedes añadir el libro manualmente.")) from error
    except (URLError, TimeoutError, OSError, ValueError) as error:
        logger.warning("catalog_request_failed provider=%s host=%s elapsed_ms=%d timeout_seconds=8 details=%s", provider, urlsplit(base).hostname, (time.monotonic() - started) * 1000, _failure_details(error))
        raise CatalogError(_("No hemos podido conectar con el catálogo. Puedes volver a intentarlo o añadir el libro manualmente.")) from error
    cache.set(key, data, timeout=3600 if path == "/search.json" else 86400)
    return data


def openlibrary_search(query, mode="all", page=1):
    query = query.strip()
    if not 2 <= len(query) <= 160:
        raise CatalogError(_("Escribe entre 2 y 160 caracteres para buscar."))
    if mode not in {"all", "title", "author", "isbn"}:
        mode = "all"
    compact = re.sub(r"[\s-]", "", query)
    isbn = normalize_isbn(query)
    if mode == "isbn" or (mode == "all" and re.fullmatch(r"[0-9]{9}[0-9Xx]|[0-9]{13}", compact)):
        if not isbn:
            raise CatalogError(_("Ese ISBN no es válido. Revisa los números del código de barras."))
    params = {"lang": "es", "limit": 12, "page": page, "fields": SEARCH_FIELDS}
    if isbn:
        params["q"] = "isbn:" + isbn
    else:
        params[{"title": "title", "author": "author"}.get(mode, "q")] = query
    data = _request("/search.json", params)
    items = []
    for raw in data.get("docs", [])[:12]:
        if not isinstance(raw, dict):
            continue
        editions = raw.get("editions", {})
        docs = editions.get("docs", []) if isinstance(editions, dict) else []
        edition = docs[0] if docs and isinstance(docs[0], dict) else {}
        edition_id = str(edition.get("key", "")).removeprefix("/books/")
        if not EDITION_ID.fullmatch(edition_id):
            continue
        authors = raw.get("author_name", [])
        authors = authors if isinstance(authors, list) else []
        identifiers = edition.get("isbn", [])
        identifiers = identifiers if isinstance(identifiers, list) else []
        valid_isbns = [normalize_isbn(i) for i in identifiers if normalize_isbn(i)]
        selected_isbn = isbn if isbn in valid_isbns else next((i for i in valid_isbns if len(i) == 13), next(iter(valid_isbns), ""))
        # For an ISBN lookup, never substitute a different edition silently.
        if isbn and selected_isbn != isbn:
            continue
        edition_cover = positive_int(edition.get("cover_i"))
        cover_id = edition_cover or positive_int(raw.get("cover_i"))
        work_key = "/works/" + str(raw.get("key", "")).removeprefix("/works/")
        items.append({
            "provider": "openlibrary", "kind": "edition", "work_key": work_key if WORK_KEY.fullmatch(work_key) else "",
            "source_id": edition_id,
            "title": clean_text(edition.get("title") or raw.get("title")) or "Título no disponible",
            "author": ", ".join(clean_text(a, 160) for a in authors[:4])[:160] or "Autor no disponible",
            "isbn": selected_isbn, "cover_id": cover_id,
            "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg?default=false" if cover_id else "", "cover_scope": "edition" if edition_cover else "work",
            "first_year": positive_int(raw.get("first_publish_year")), "color": "blue",
            "language": clean_text(next(iter(edition.get("language") or []), ""), 40),
            "publisher": ", ".join(clean_text(p) for p in (edition.get("publisher") or [])[:3])[:200],
            "publication_date": clean_text(edition.get("publish_date"), 80),
            "total_pages": positive_int(edition.get("number_of_pages")),
        })
    count = positive_int(data.get("numFound", data.get("num_found"))) or 0
    return {"items": items, "total": count, "has_next": page < 50 and page * 12 < count}


def openlibrary_details(selection):
    edition_id = selection.get("source_id", "")
    if not EDITION_ID.fullmatch(edition_id):
        raise CatalogError(_("La referencia del libro no es válida. Vuelve a buscarlo."))
    data = _request(f"/books/{edition_id}.json")
    if not data:
        raise CatalogError(_("Esta edición ya no está disponible. Prueba otro resultado o añádela manualmente."))
    isbns = [normalize_isbn(i) for name in ("isbn_13", "isbn_10") for i in (data.get(name) or []) if normalize_isbn(i)]
    if selection.get("isbn") and isbns and selection["isbn"] not in isbns:
        raise CatalogError(_("El ISBN no coincide con esta edición. Prueba otro resultado."))
    description = clean_text(data.get("description"), 8000)
    if not description:
        works = data.get("works") or []
        work = works[0].get("key", "") if works and isinstance(works[0], dict) else ""
        if WORK_KEY.fullmatch(work):
            try:
                description = clean_text(_request(work + ".json").get("description"), 8000)
            except CatalogError:
                pass  # The book can still be imported without a synopsis.
    covers = data.get("covers") or []
    # Use the edition's own cover; work covers may belong to another translation.
    cover_id = next((positive_int(c) for c in covers if positive_int(c)), None)
    publishers = data.get("publishers") or []
    languages = data.get("languages") or []
    language = clean_text(languages[0].get("key", ""), 40).removeprefix("/languages/") if languages and isinstance(languages[0], dict) else ""
    return {
        "provider": "openlibrary", "kind": "edition",
        "work_key": next((w.get("key") for w in data.get("works", []) if isinstance(w, dict) and WORK_KEY.fullmatch(w.get("key", ""))), f"/books/{edition_id}"),
        "source_id": edition_id, "title": clean_text(data.get("title")) or selection["title"],
        "author": selection["author"], "isbn": selection.get("isbn") or next(iter(isbns), ""),
        "publisher": ", ".join(clean_text(p) for p in publishers[:3])[:200],
        "publication_date": clean_text(data.get("publish_date"), 80), "language": language,
        "synopsis": description, "cover_id": cover_id,
        "total_pages": positive_int(data.get("number_of_pages")),
        "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg?default=false" if cover_id else "",
    }


def canonical_isbn(value):
    value = normalize_isbn(value)
    if len(value) == 10:
        stem = "978" + value[:9]
        return stem + str((-sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(stem))) % 10)
    return value


INV_URI = re.compile(r"(?:inv:[0-9a-f]{32}|wd:Q[0-9]{1,15}|isbn:97[89][0-9]{10})\Z")


def inv_entities(uris, relatives=""):
    uris = [u for u in uris if isinstance(u, str) and INV_URI.fullmatch(u)][:50]
    if not uris:
        return {}
    params = {"uris": "|".join(uris), "lang": "es", "attributes": "info|labels|descriptions|claims|image"}
    if relatives:
        params["relatives"] = relatives
    data = _request("/entities/by-uris", params, provider="inventaire")
    return data.get("entities", {}) if isinstance(data.get("entities"), dict) else {}


def inv_label(entity):
    labels = entity.get("labels") or {}
    return clean_text(labels.get("es") or labels.get("fromclaims") or labels.get("en") or next(iter(labels.values()), ""))


def safe_cover(value):
    if not isinstance(value, str):
        return ""
    if value.startswith("/img/entities/"):
        value = "https://inventaire.io" + value
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc not in {"covers.openlibrary.org", "inventaire.io", "images.cdn.europe-west1.gcp.commercetools.com"}:
        return ""
    if parsed.netloc == "inventaire.io" and not re.fullmatch(r"/img/entities/[0-9a-f]+", parsed.path):
        return ""
    return value[:500]


def inv_candidate(entity):
    image = entity.get("image") or {}
    claims = entity.get("claims") or {}
    isbn = next((canonical_isbn(i) for p in ("wdt:P212", "wdt:P957") for i in claims.get(p, []) if canonical_isbn(i)), "")
    return {"provider": "inventaire", "kind": entity.get("type", "work"), "source_id": entity.get("uri", ""),
            "work_key": next(iter(claims.get("wdt:P629", [])), "") if entity.get("type") == "edition" else entity.get("uri", ""),
            "title": inv_label(entity) or "Título no disponible", "author": "", "isbn": isbn,
            "cover_url": safe_cover(image.get("url", "") if isinstance(image, dict) else image), "cover_scope": "edition" if entity.get("type") == "edition" else "work", "color": "blue", "language": entity.get("originalLang", ""),
            "total_pages": positive_int(next(iter(claims.get("wdt:P1104", [])), None)),
            "publication_date": clean_text(next(iter(claims.get("wdt:P577", [])), ""), 80)}


def inventaire_search(query, mode, page):
    isbn = canonical_isbn(query)
    if isbn:
        entities = inv_entities(["isbn:" + isbn], "wdt:P629|wdt:P123")
        items = [inv_candidate(e) for e in entities.values() if e.get("type") == "edition"]
        items = [e for e in items if e["isbn"] == isbn]
        return {"items": items, "has_next": False, "total": len(items)}
    data = _request("/search", {"search": query, "types": "humans" if mode == "author" else "works", "lang": "es", "limit": 12, "offset": (page - 1) * 12}, provider="inventaire")
    items = []
    for raw in data.get("results", [])[:12]:
        uri = raw.get("uri", "")
        if INV_URI.fullmatch(uri):
            items.append({"provider": "inventaire", "source_id": uri, "kind": "author" if mode == "author" else "work",
                          "title": clean_text(raw.get("label")), "author": clean_text(raw.get("description"), 160),
                          "isbn": "", "cover_url": safe_cover(raw.get("image")), "cover_scope": "portrait" if mode == "author" else "work", "color": "blue", "author_is_description": True})
    return {"items": items, "has_next": bool(data.get("continue")), "total": positive_int(data.get("total")) or len(items)}


def inventaire_options(selection):
    uri = selection.get("source_id", "")
    if not INV_URI.fullmatch(uri):
        raise CatalogError(_("Referencia de catálogo no válida."))
    if selection.get("kind") == "author":
        data = _request("/entities/author-works", {"uri": uri}, provider="inventaire")
        uris = data.get("uris", data.get("works", []))
    else:
        data = _request("/entities/reverse-claims", {"property": "wdt:P629", "value": uri}, provider="inventaire")
        uris = data.get("uris", [])
    if isinstance(uris, dict):
        uris = list(uris)
    uris = [u.get("uri", "") if isinstance(u, dict) else u for u in uris]
    entities = inv_entities(uris[:50])
    items = [inv_candidate(e) for e in entities.values() if e.get("type") in ({"work"} if selection.get("kind") == "author" else {"edition"})]
    return sorted(items, key=lambda e: (e.get("language") != "es", e.get("isbn", "") == "", e["title"]))


def inventaire_details(selection):
    uri = selection.get("source_id", "")
    if not INV_URI.fullmatch(uri):
        raise CatalogError(_("Referencia de catálogo no válida."))
    entities = inv_entities([uri], "wdt:P629|wdt:P123")
    entity = entities.get(uri)
    if not entity or entity.get("type") != "edition":
        raise CatalogError(_("No encontramos esta edición en Inventaire."))
    claims = entity.get("claims") or {}
    work_uri = next(iter(claims.get("wdt:P629", [])), "")
    relatives = inv_entities([work_uri], "wdt:P50") if work_uri else {}
    entities.update(relatives)
    work = entities.get(work_uri, {})
    authors = [inv_label(entities[a]) for a in work.get("claims", {}).get("wdt:P50", []) if a in entities]
    publishers = [inv_label(entities[p]) for p in claims.get("wdt:P123", []) if p in entities]
    result = inv_candidate(entity)
    result.update({"kind": "edition", "author": ", ".join(authors)[:160] or "Autor no disponible",
                   "publisher": ", ".join(publishers)[:200], "publication_date": clean_text(next(iter(claims.get("wdt:P577", [])), ""), 80),
                   "language": entity.get("originalLang", "")[:40], "synopsis": "",
                   "total_pages": positive_int(next(iter(claims.get("wdt:P1104", [])), None)), "work_key": work_uri or uri})
    return result


PROVIDERS = {"openlibrary": "Open Library", "inventaire": "Inventaire", "bne": "Biblioteca Nacional de España",
             "bookbrainz": "BookBrainz", "boktyven": "Boktyven"}


def enabled_providers():
    return {key: label for key, label in PROVIDERS.items() if key != "boktyven" or settings.BOKTYVEN_API_TOKEN}


def provider_search(provider, query, mode, page):
    if provider in {"openlibrary", "inventaire"}:
        return (openlibrary_search if provider == "openlibrary" else inventaire_search)(query, mode, page)
    from .catalog_extra import bne_search, bookbrainz_search, boktyven_search
    return {"bne": bne_search, "bookbrainz": bookbrainz_search, "boktyven": boktyven_search}[provider](query, mode, page)


def provider_details(selection):
    provider = selection.get("provider")
    if provider in {"openlibrary", "inventaire"}:
        return (openlibrary_details if provider == "openlibrary" else inventaire_details)(selection)
    from .catalog_extra import bne_details, bookbrainz_details, boktyven_details
    if provider not in {"bne", "bookbrainz", "boktyven"}:
        raise CatalogError(_("Fuente no válida."))
    return {"bne": bne_details, "bookbrainz": bookbrainz_details, "boktyven": boktyven_details}[provider](selection)


def _worker(provider, query, mode, page):
    close_old_connections()
    try:
        return provider_search(provider, query, mode, page)
    finally:
        connections.close_all()


def search(query, mode="all", page=1, provider="all"):
    query = query.strip()
    if not 2 <= len(query) <= 160:
        raise CatalogError(_("Escribe entre 2 y 160 caracteres para buscar."))
    if mode not in {"all", "title", "author", "isbn"}:
        mode = "all"
    compact = re.sub(r"[\s-]", "", query)
    isbn = canonical_isbn(query)
    if (mode == "isbn" or (mode == "all" and re.fullmatch(r"[0-9]{9}[0-9Xx]|[0-9]{13}", compact))) and not isbn:
        raise CatalogError(_("Ese ISBN no es válido. Revisa los números del código de barras."))
    if provider == "boktyven" and provider not in enabled_providers():
        raise CatalogError(_("Boktyven aún no está activado: falta configurar su token de acceso."))
    selected = [provider] if provider in enabled_providers() else list(enabled_providers())
    if provider == "all" and isbn:
        selected = [p for p in selected if p != "bookbrainz"]
    items, warnings, more, failed = [], [], False, []
    with ThreadPoolExecutor(max_workers=5) as pool:
        pending = {p: pool.submit(_worker, p, query, mode, page) for p in selected}
        for p, future in pending.items():
            try:
                result = future.result()
                items.extend(result["items"])
                more = more or result["has_next"]
                warnings.extend(result.get("warnings", []))
            except (CatalogError, ValueError, TypeError, KeyError, AttributeError) as exc:
                failed.append(p)
                logger.warning("catalog_search_failed provider=%s mode=%s page=%s details=%s", p, mode, page, _failure_details(exc))
    from .ranking import rank_results
    from .matching import group_works
    ordered = rank_results(items, query, mode, settings.CATALOG_PREFERRED_LANGUAGE)
    ordered = group_works(ordered)
    return {"items": ordered, "warnings": warnings, "failed_providers": failed, "has_next": more, "total": len(ordered),
            "unavailable": bool(selected) and len(failed) == len(selected)}


def source_url(data):
    bases = {"openlibrary": "https://openlibrary.org/books/", "inventaire": "https://inventaire.io/entity/",
             "bookbrainz": "https://bookbrainz.org/edition/",
             "bne": "https://catalogo.bne.es/discovery/fulldisplay?vid=34BNE_INST:CATALOGO&docid=alma"}
    if data["provider"] == "boktyven":
        return "https://boktyven.no/api"  # Stable attribution; do not trust remote purchase redirects.
    return bases[data["provider"]] + data["source_id"]


def details(selection):
    if selection.get("kind") == "work_group":
        raise CatalogError(_("Elige una edición antes de añadir el libro."))
    if selection.get("provider") not in PROVIDERS:
        raise CatalogError(_("Fuente no válida."))
    item = provider_details(selection)
    item["isbn"] = canonical_isbn(item.get("isbn", ""))
    item["cover_url"] = safe_cover(item.get("cover_url", ""))
    item["sources"] = [{"provider": item["provider"], "external_id": item["source_id"], "url": source_url(item), "metadata": dict(item)}]
    fields = ["title", "author", "isbn", "publisher", "publication_date", "language", "synopsis", "cover_url", "total_pages"]
    item["field_sources"] = {f: item["provider"] for f in fields if item.get(f)}
    item["conflicts"] = []
    for alternative in selection.get("alternatives", [])[:4]:
        try:
            other = provider_details(alternative)
        except CatalogError:
            continue
        if not item["isbn"] or canonical_isbn(other.get("isbn", "")) != item["isbn"]:
            continue
        item["sources"].append({"provider": other["provider"], "external_id": other["source_id"], "url": source_url(other), "metadata": dict(other)})
        for field in fields:
            if not item.get(field) and other.get(field):
                item[field] = other[field]
                item["field_sources"][field] = other["provider"]
            elif field in {"total_pages", "publisher", "publication_date", "language"} and other.get(field) and item.get(field) != other[field]:
                item["conflicts"].append({"field": field, "selected": item[field], "alternative": other[field], "provider": other["provider"]})
    item["cover_url"] = safe_cover(item.get("cover_url", ""))
    return item
