from django.utils.translation import gettext as _
"""Explainable catalogue ranking, with hard identity/match guards before quality.

Scores are ordering heuristics, not probabilities. No extra network calls are made.
"""
from copy import deepcopy
from difflib import SequenceMatcher
import re
import unicodedata

from .catalog import canonical_isbn, safe_cover

UNKNOWN = {"", "autor no disponible", "titulo no disponible", "unknown", "n a", "desconocido"}
INFORMATION_WEIGHTS = {"author": 4, "isbn": 4, "publisher": 3, "publication_date": 3,
                       "language": 2, "total_pages": 3, "synopsis": 1}
LANGUAGES = {"spa": "es", "espanol": "es", "spanish": "es", "eng": "en", "english": "en",
             "fra": "fr", "fre": "fr", "deu": "de", "ger": "de", "ita": "it", "por": "pt"}


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", value))


def known(value):
    return normalize(value) not in UNKNOWN


def language(value):
    value = normalize(value)
    return LANGUAGES.get(value, value)


def similarity(query, value, author=False):
    query, value = normalize(query), normalize(value)
    if not query or not known(value):
        return 0.0
    if query == value:
        return 1.0
    query_words, value_words = query.split(), value.split()
    if author and sorted(query_words) == sorted(value_words):
        return 1.0  # "Zafón, Carlos Ruiz" and "Carlos Ruiz Zafón".
    if set(query_words).issubset(value_words):
        return .95  # Full words match, including titles with subtitles.
    coverage = len(set(query_words) & set(value_words)) / len(set(query_words))
    characters = SequenceMatcher(None, query, value, autojunk=False).ratio()
    return min(.94, .55 * coverage + .45 * characters)


def match(item, query, mode):
    if item.get("kind") == "author":
        return similarity(query, item.get("title"), author=True), "author"
    title = similarity(query, item.get("title"))
    author = 0.0 if item.get("author_is_description") else similarity(query, item.get("author"), author=True)
    if mode == "title":
        return title, "title"
    if mode == "author":
        return author, "author"
    combined = 0.0
    words = set(normalize(query).split())
    title_words, author_words = set(normalize(item.get("title")).split()), set(normalize(item.get("author")).split())
    if words and words <= title_words | author_words and words & title_words and words & author_words:
        combined = .95
    best = max(title, author, combined)
    return best, "combined" if combined > max(title, author) else "title" if title >= author else "author"


def available(item, field):
    value = item.get("title") if field == "author" and item.get("kind") == "author" else item.get(field)
    if field == "isbn":
        return bool(canonical_isbn(value or ""))
    if field == "total_pages":
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    if field == "cover_url":
        local_path = r"/(?:es|en|de|fr|it)/(?:portadas|covers|cover|couvertures|copertine)/([0-9a-f-]{36})/"
        local = re.fullmatch(local_path, value or "") if item.get("provider") == "local" else None
        return bool(safe_cover(value or "") or (local and local[1] == item.get("local_id")))
    if field == "author" and item.get("author_is_description") and item.get("kind") != "author":
        return False
    return isinstance(value, str) and known(value)


def completeness(item):
    return sum(weight for field, weight in INFORMATION_WEIGHTS.items() if available(item, field))


def compatible(first, second):
    isbn = canonical_isbn(first.get("isbn", ""))
    if not isbn or isbn != canonical_isbn(second.get("isbn", "")):
        return False
    if similarity(first.get("title"), second.get("title")) < .8:
        return False
    if known(first.get("author")) and known(second.get("author")):
        if similarity(first["author"], second["author"], author=True) < .75:
            return False
    return True


def assess(item, query, mode="all", preferred_language="es"):
    requested_isbn = canonical_isbn(query)
    exact_isbn = bool(requested_isbn and canonical_isbn(item.get("isbn", "")) == requested_isbn)
    relevance, matched_field = match(item, query, mode)
    if requested_isbn:
        relevance = 1.0 if exact_isbn else 0.0
    tier = 3 if relevance == 1 else 2 if relevance >= .9 else 1 if relevance >= .65 else 0
    information = completeness(item)
    cover = {"work": 5, "portrait": 0}.get(item.get("cover_scope"), 10) if available(item, "cover_url") else 0
    preferred = bool(language(item.get("language")) and language(item.get("language")) == language(preferred_language))
    providers = {item.get("provider")}
    providers.update(a.get("provider") for a in item.get("alternatives", []) if compatible(item, a))
    providers.discard(None)
    corroboration = 5 if len(providers) > 1 else 0
    components = {"match": round(60 * relevance, 3), "information": information,
                  "cover": cover, "language": 5 if preferred else 0, "corroboration": corroboration}
    reasons = []
    if exact_isbn:
        reasons.append(_("ISBN exacto"))
    elif relevance == 1:
        reasons.append(_("Autor coincidente") if matched_field == "author" else _("Título exacto"))
    elif relevance >= .9:
        reasons.append(_("Título y autor coincidentes") if matched_field == "combined" else _("Coincidencia de autor") if matched_field == "author" else _("Coincidencia de título"))
    if cover:
        reasons.append(_("Portada de la obra") if item.get("cover_scope") == "work" else _("Portada indicada"))
    if preferred:
        reasons.append(_("En español") if language(preferred_language) == "es" else _("Idioma preferido"))
    if corroboration:
        reasons.append(_("Mismo ISBN en %(count)s fuentes") % {"count": len(providers)})
    if information >= 14:
        reasons.append(_("Ficha con más datos"))
    return {"score": round(sum(components.values()), 3), "match": relevance, "tier": tier,
            "exact_isbn": exact_isbn, "components": components, "reasons": reasons[:5]}


def order_key(item):
    rank = item["ranking"]
    return (-int(rank["exact_isbn"]), -rank["tier"], -rank["score"], -rank["match"],
            normalize(item.get("title")), normalize(item.get("author")),
            str(item.get("provider", "")), str(item.get("source_id", "")))


def rank_results(items, query, mode="all", preferred_language="es"):
    # Do not mutate provider/cache responses. Choose the best representative
    # within an ISBN group rather than letting provider arrival order choose it.
    groups = {}
    for raw in items:
        item = deepcopy(raw)
        alternatives = item.pop("alternatives", [])
        for candidate in [item, *alternatives]:
            candidate["isbn"] = canonical_isbn(candidate.get("isbn", ""))
            key = "isbn:" + candidate["isbn"] if candidate["isbn"] else (candidate.get("provider"), candidate.get("source_id"))
            groups.setdefault(key, {})[(candidate.get("provider"), candidate.get("source_id"))] = candidate
    from .matching import same_work_confidence
    edition_sets = []
    for unique in groups.values():
        candidates = list(unique.values())
        for item in candidates:
            item["ranking"] = assess(item, query, mode, preferred_language)
        candidates.sort(key=order_key)
        buckets = []
        for candidate in candidates:
            for bucket in buckets:
                if all(same_work_confidence(candidate, other)["automatic"] for other in bucket):
                    bucket.append(candidate)
                    break
            else:
                buckets.append([candidate])
        edition_sets.extend(buckets)
    grouped = []
    for candidates in edition_sets:
        representative = candidates[0]
        representative["alternatives"] = candidates[1:]
        representative.setdefault("search_field_sources", {})
        for alternative in candidates[1:]:
            if not compatible(representative, alternative):
                continue
            for field in (*INFORMATION_WEIGHTS, "cover_url"):
                if not available(representative, field) and available(alternative, field):
                    representative[field] = alternative[field]
                    representative["search_field_sources"][field] = alternative.get("provider")
                    if field == "cover_url":
                        representative["cover_scope"] = alternative.get("cover_scope", "edition")
                    if field == "author":
                        representative["author_is_description"] = False
        representative["ranking"] = assess(representative, query, mode, preferred_language)
        grouped.append(representative)
    return sorted(grouped, key=order_key)
