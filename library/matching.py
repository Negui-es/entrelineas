"""Conservative, explainable work matching. Scores are heuristics, not probabilities."""
from copy import deepcopy
from difflib import SequenceMatcher
import re
from django.utils.translation import gettext as _
from .catalog import canonical_isbn
from .ranking import known, normalize, order_key

WORK_THRESHOLD = 95
AUTHOR_PREFIX = re.compile(
    r"^(?:libro (?:de|por)|obra de|novela de|escrit[oa] por|autor(?:a)?\s*:?|"
    r"written by|book by|a novel by|author\s*:?|livre de|ecrit(?:e)? par|"
    r"scritto da|scrittrice\s*:?|libro di|buch von|geschrieben von|von|by|por)\s+")
ROLE_WORDS = {"traducido", "traductor", "traduccion", "translated", "translator", "traduction",
              "traduit", "traduzione", "tradotto", "ubersetzt", "ubersetzung", "illustrator", "ilustrador"}
GENERIC_TITLES = {"poesia", "poesias", "poems", "poetry", "cuentos", "relatos", "stories",
                  "obras", "obras completas", "collected works", "selected works", "ensayos", "essays",
                  "cartas", "letters", "anthology", "antologia", "gedichte", "poesie", "poesies",
                  "racconti", "erzahlungen", "nouvelles", "contes", "oeuvres completes", "opere complete",
                  "gesammelte werke", "complete works"}
CONTENT_MARKERS = {
    "adaptation": r"\b(?:adaptacion|adaptation|adattamento|bearbeitung)\b",
    "graphic": r"\b(?:novela grafica|graphic novel|comic|manga|bande dessinee|fumetto)\b",
    "abridged": r"\b(?:abreviad[oa]|abridged|abrege|gekurzt|ridott[oa]|resumen|summary)\b",
    "guide": r"\b(?:guia|guide|companion|study|analyse|analisis|studienfuhrer)\b",
    "collection": r"\b(?:estuche|box set|boxed set|omnibus|trilogia|tetralogia|sammelband|cofanetto|coffret)\b",
}


def author_name(item):
    credit = normalize(item.get("author"))
    if not known(credit):
        return ""
    stripped = AUTHOR_PREFIX.sub("", credit, count=1)
    if item.get("author_is_description") and stripped == credit:
        return ""  # A provider description is not automatically a person credit.
    if set(stripped.split()) & ROLE_WORDS or re.search(r"\d", stripped):
        return ""
    words = stripped.split()
    return stripped if 1 <= len(words) <= 16 else ""


def author_tokens(item):
    # Surname-first credits and leading role labels are harmless. Coauthors are
    # retained, so a different contributor list cannot become an exact match.
    return sorted(author_name(item).split())


def work_identity(item):
    provider = item.get("provider")
    key = item.get("work_key", "")
    if provider == "local" and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", key):
        return (provider, key)
    if provider == "openlibrary" and re.fullmatch(r"/works/OL\d+W", key):
        return (provider, key)
    if provider == "inventaire":
        key = key or (item.get("source_id", "") if item.get("kind") == "work" else "")
        if re.fullmatch(r"(?:wd:Q\d+|inv:[0-9a-f]{32})", key):
            return (provider, key)
    return None


def title_markers(item):
    title = normalize(item.get("title"))
    numbers = tuple(re.findall(r"\d+", title))
    volumes = tuple(re.findall(r"\b(?:vol(?:ume|umen)?|tomo|part(?:e)?|band|tome|book|libro)\s+([ivxlcdm]+|\d+|one|two|three|four|five|uno|dos|tres|cuatro|cinco|un|deux|trois|quatre|cinq|eins|zwei|drei|vier|funf|due|tre|quattro|cinque)\b", title))
    content = frozenset(key for key, pattern in CONTENT_MARKERS.items() if re.search(pattern, title))
    return numbers, volumes, content


def same_work_confidence(first, second):
    """Return score, evidence and permission to group. Never change source data."""
    title_a, title_b = normalize(first.get("title")), normalize(second.get("title"))
    authors_a, authors_b = author_tokens(first), author_tokens(second)
    exact_author = bool(authors_a and authors_a == authors_b)
    exact_title = bool(known(title_a) and title_a == title_b)
    author_similarity = SequenceMatcher(None, " ".join(authors_a), " ".join(authors_b), autojunk=False).ratio() if authors_a and authors_b else 0
    reasons, score = [], 0
    if first.get("kind") == "author" or second.get("kind") == "author":
        return {"score": 0, "automatic": False, "reasons": []}
    if title_markers(first) != title_markers(second):
        return {"score": 0, "automatic": False, "reasons": [_("Volumen o contenido diferente")]}
    if first.get("provider") == second.get("provider") == "local" and work_identity(first) and work_identity(first) == work_identity(second):
        return {"score": 100, "automatic": True, "reasons": [_("Identificador de obra coincidente")]}
    # Conflicting known authors override even a reused ISBN or work identifier.
    if authors_a and authors_b and not exact_author:
        score = min(89, round(60 + 29 * author_similarity)) if exact_title and author_similarity >= .8 else 0
        return {"score": score, "automatic": False, "reasons": [_("Autor no confirmado")]}
    isbn = canonical_isbn(first.get("isbn", ""))
    same_isbn = bool(isbn and isbn == canonical_isbn(second.get("isbn", "")))
    identity = work_identity(first)
    same_identity = bool(identity and identity == work_identity(second))
    if same_isbn:
        # ISBN identifies an edition, but obvious title contradictions still win.
        if known(title_a) and known(title_b) and not exact_title:
            ratio = SequenceMatcher(None, title_a, title_b, autojunk=False).ratio()
            if ratio < .8:
                return {"score": 0, "automatic": False, "reasons": [_("ISBN con datos contradictorios")]}
        score, reasons = 100, [_("Mismo ISBN válido")]
    elif same_identity:
        score, reasons = 99, [_("Identificador de obra coincidente")]
    elif exact_author and len(authors_a) >= 2 and exact_title and title_a not in GENERIC_TITLES:
        score, reasons = 98, [_("Título normalizado idéntico"), _("Autor normalizado idéntico")]
    elif exact_author and len(authors_a) >= 2 and known(title_a) and known(title_b) and title_a not in GENERIC_TITLES and title_b not in GENERIC_TITLES:
        ratio = SequenceMatcher(None, title_a, title_b, autojunk=False).ratio()
        # A small typo is acceptable; arbitrary subtitle containment is not.
        score = 95 if ratio >= .96 and min(len(title_a), len(title_b)) >= 16 else min(94, round(70 * ratio + 25))
        reasons = [_("Título muy similar"), _("Autor normalizado idéntico")]
    elif exact_title:
        score, reasons = 60, [_("Falta confirmar el autor")]
    return {"score": score, "automatic": score >= WORK_THRESHOLD, "reasons": reasons}


def group_works(items):
    """Complete-link clustering: every member must match every other member.

    Edition metadata is never blended here. Representatives keep the original
    ranking, and options retain the per-ISBN sources produced by rank_results.
    """
    clusters = []
    for item in sorted(deepcopy(items), key=order_key):
        for cluster in clusters:
            if all(same_work_confidence(item, existing)["automatic"] for existing in cluster):
                cluster.append(item)
                break
        else:
            clusters.append([item])
    output = []
    for cluster in clusters:
        if len(cluster) == 1:
            output.append(cluster[0])
            continue
        reports = [same_work_confidence(a, b) for index, a in enumerate(cluster) for b in cluster[index+1:]]
        weakest = min(reports, key=lambda report: report["score"])
        representative = deepcopy(cluster[0])
        representative.update(kind="work_group", editions=cluster, group_confidence=weakest["score"],
                              group_reasons=weakest["reasons"], result_count=len(cluster))
        output.append(representative)
    return sorted(output, key=order_key)
