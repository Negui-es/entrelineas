from django.utils.translation import gettext_lazy as _
"""BNE SRU/MARC21, BookBrainz and optional Boktyven adapters."""
import re
import xml.etree.ElementTree as ET

from .catalog import CatalogError, _request, canonical_isbn, clean_text, positive_int, safe_cover

M = "{http://www.loc.gov/MARC21/slim}"
S = "{http://www.loc.gov/zing/srw/}"
BBID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
BNE_ID = re.compile(r"[0-9]{10,25}\Z")


def empty_page(**extra):
    return {"items": [], "has_next": False, "total": 0, **extra}


def base_item(provider, key, title, author=""):
    return {"provider": provider, "source_id": key, "work_key": key, "kind": "edition",
            "title": clean_text(title) or "Título no disponible", "author": clean_text(author, 160),
            "isbn": "", "publisher": "", "publication_date": "", "language": "", "synopsis": "",
            "total_pages": None, "cover_url": "", "color": "blue"}


def cql_literal(value):
    # Keep visitor input entirely inside a CQL quoted literal.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def bne_records(query, page=1, size=12):
    xml = _request("", {"version": "1.2", "operation": "searchRetrieve", "query": query,
                         "recordSchema": "marcxml", "recordPacking": "xml",
                         "startRecord": (page - 1) * size + 1, "maximumRecords": size}, "bne")
    if not isinstance(xml, str) or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I):
        raise CatalogError(_("Respuesta XML no válida de BNE."))
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise CatalogError(_("No se ha podido leer la respuesta de BNE.")) from exc
    if any(node.tag.rsplit("}", 1)[-1] == "diagnostic" for node in root.iter()):
        raise CatalogError(_("BNE no ha podido realizar esta consulta."))
    count = positive_int(root.findtext(S + "numberOfRecords")) or 0
    items = []
    for record in root.iter(M + "record"):
        def values(tag, codes="a"):
            return [clean_text(node.text, 8000) for field in record.findall(M + "datafield")
                    if field.get("tag") == tag for node in field.findall(M + "subfield")
                    if node.get("code") in codes and node.text]
        def joined(tag, codes="a"):
            return " ".join(values(tag, codes)).strip(" /:;,. ")
        key = next((n.text for n in record.findall(M + "controlfield") if n.get("tag") == "001"), "")
        if not BNE_ID.fullmatch(key or ""):
            continue
        authors = joined("100") or joined("110")
        if not authors:
            # MARC 700 also includes translators/editors; require the author role.
            authors = ", ".join(clean_text(n.text, 160) for field in record.findall(M + "datafield")
                                if field.get("tag") == "700" and any(
                                    n.get("code") == "4" and n.text == "aut" for n in field.findall(M + "subfield"))
                                for n in field.findall(M + "subfield") if n.get("code") == "a")
        item = base_item("bne", key, joined("245", "ab"), authors)
        identifiers = [canonical_isbn(re.split(r"[ (]", v.strip())[0]) for v in values("020")]
        item["isbns"] = [value for value in identifiers if value]
        item["isbn"] = next((v for v in identifiers if v), "")
        fixed = next((n.text or "" for n in record.findall(M + "controlfield") if n.get("tag") == "008"), "")
        pages = re.search(r"(?:^|\s)(\d+)\s*(?:p(?:\.|$)|pág|pages)", joined("300"), re.I)
        item.update(publisher=(joined("264", "b") or joined("260", "b"))[:200],
                    publication_date=(joined("264", "c") or joined("260", "c"))[:80],
                    language=(joined("041") or fixed[35:38].strip(" |^"))[:40],
                    total_pages=positive_int(pages.group(1)) if pages else None,
                    synopsis=joined("520")[:8000])
        items.append(item)
    return {"items": items, "total": count, "has_next": page < 50 and page * size < count}


def bne_search(query, mode="all", page=1):
    isbn = canonical_isbn(query)
    index = "isbn" if isbn else {"title": "title", "author": "creator"}.get(mode, "all_for_ui")
    relation = "=" if isbn or mode == "title" else " all "
    result = bne_records("alma." + index + relation + cql_literal(isbn or query), page)
    if isbn:
        for item in result["items"]:
            if isbn in item.get("isbns", []):
                item["isbn"] = isbn
        result["items"] = [item for item in result["items"] if item["isbn"] == isbn]
    return result


def bne_details(selection):
    key = selection.get("source_id", "")
    if not BNE_ID.fullmatch(key):
        raise CatalogError(_("Referencia de BNE no válida."))
    items = bne_records("alma.mms_id=" + cql_literal(key), size=1)["items"]
    item = next((i for i in items if i["source_id"] == key), None)
    expected = canonical_isbn(selection.get("isbn", ""))
    if item and expected and expected in item.get("isbns", []):
        item["isbn"] = expected
    return checked_details(item, selection)


def checked_details(item, selection):
    if not item:
        raise CatalogError(_("La edición ya no está disponible en esta fuente."))
    expected = canonical_isbn(selection.get("isbn", ""))
    if expected and expected != item.get("isbn"):
        raise CatalogError(_("El ISBN de la fuente ha cambiado. Vuelve a buscar la edición."))
    return item


def bb_candidate(raw):
    key = raw.get("bbid", "")
    if not BBID.fullmatch(key):
        return None
    authors = raw.get("authors") or [n.get("name", "") for n in (raw.get("authorCredits") or {}).get("names", [])]
    alias = raw.get("defaultAlias") or {}
    item = base_item("bookbrainz", key, alias.get("name", ""), ", ".join(clean_text(a, 160) for a in authors)[:160])
    item.update(language=clean_text(next(iter(raw.get("languages") or []), ""), 40),
                total_pages=positive_int(raw.get("pages")),
                publisher=", ".join(clean_text(p.get("name")) for p in raw.get("publishers") or [])[:200],
                publication_date=clean_text(raw.get("releaseEventDate"), 80))
    item["publication_date"] = re.sub(r"^\+00(\d{4})(?=-|$)", r"\1", item["publication_date"])
    # Alias language describes the name, not the edition's language.
    return item


def bookbrainz_search(query, mode="all", page=1):
    if canonical_isbn(query) or mode == "isbn":
        return empty_page(warnings=[_("BookBrainz se consulta por título y autor; su buscador documentado no ofrece un filtro ISBN.")])
    data = _request("/search", {"q": query, "type": "author" if mode == "author" else "edition",
                                "size": 12, "from": (page - 1) * 12}, "bookbrainz")
    items = []
    for raw in (data.get("searchResult") or [])[:12]:
        if not isinstance(raw, dict):
            continue
        item = bb_candidate(raw)
        if item:
            if mode == "author":
                item.update(kind="author", author="")
            items.append(item)
    count = positive_int(data.get("totalCount", data.get("searchCount"))) or 0
    return {"items": items, "total": count, "has_next": page < 50 and page * 12 < count}


def bookbrainz_options(selection):
    key = selection.get("source_id", "")
    if not BBID.fullmatch(key) or selection.get("kind") != "author":
        raise CatalogError(_("Referencia de autor no válida."))
    data = _request("/edition", {"author": key}, "bookbrainz")
    return [item for row in (data.get("editions") or [])[:100]
            if isinstance(row, dict) and (item := bb_candidate(row.get("entity") or {}))]


def bookbrainz_details(selection):
    key = selection.get("source_id", "")
    if not BBID.fullmatch(key):
        raise CatalogError(_("Referencia de BookBrainz no válida."))
    raw = _request("/edition/" + key, provider="bookbrainz")
    item = bb_candidate(raw)
    if not item or item["source_id"] != key:
        raise CatalogError(_("No encontramos esta edición en BookBrainz."))
    identifiers = _request("/edition/" + key + "/identifiers", provider="bookbrainz")
    item["isbn"] = next((isbn for value in identifiers.get("identifiers", [])
                         if value.get("type") in {"ISBN-13", "ISBN-10"}
                         and (isbn := canonical_isbn(value.get("value", "")))), "")
    return checked_details(item, selection)


def bok_candidate(raw):
    isbn = canonical_isbn(raw.get("isbn", ""))
    if not isbn:
        return None
    item = base_item("boktyven", isbn, raw.get("title"), raw.get("author"))
    item.update(isbn=isbn, publisher=clean_text(raw.get("publisher")),
                publication_date=str(positive_int(raw.get("publicationYear")) or ""),
                language=clean_text(raw.get("language"), 40), synopsis=clean_text(raw.get("description"), 8000),
                cover_url=safe_cover(raw.get("coverUrl")), cover_scope="edition")
    return item


def boktyven_search(query, mode="all", page=1):
    if page > 1:  # No pagination parameters are documented.
        return empty_page()
    isbn = canonical_isbn(query)
    data = _request("/books/search", {"q": isbn or query}, "boktyven")
    items = [item for raw in (data.get("results") or [])[:50]
             if isinstance(raw, dict) and (item := bok_candidate(raw))]
    if isbn:
        items = [item for item in items if item["isbn"] == isbn]
    elif mode in {"title", "author"}:
        from .ranking import similarity
        items = [item for item in items if similarity(query, item[mode], author=mode == "author") >= .65]
    return {"items": items, "total": len(items), "has_next": False}


def boktyven_details(selection):
    isbn = canonical_isbn(selection.get("source_id", ""))
    if not isbn:
        raise CatalogError(_("Referencia de Boktyven no válida."))
    items = boktyven_search(isbn, "isbn")["items"]
    return checked_details(next((item for item in items if item["isbn"] == isbn), None), selection)
