from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase
from django.urls import reverse
from . import catalog
from .ranking import assess, rank_results, similarity
from .tests import AppTestCase

COVER = "https://covers.openlibrary.org/b/id/12345-M.jpg"


def candidate(key="OL1M", **extra):
    return {"source_id": key, "provider": "openlibrary", "kind": "edition",
            "title": "La sombra del viento", "author": "Carlos Ruiz Zafón", "isbn": "", **extra}


def rich(key="OL2M", **extra):
    values = {"publisher": "Planeta", "publication_date": "2017", "language": "spa", "total_pages": 592,
              "synopsis": "Descripción", "cover_url": COVER, **extra}
    return candidate(key, **values)


class RankingTests(SimpleTestCase):
    def test_exact_isbn_beats_complete_different_edition(self):
        exact = candidate(isbn="8408163434", author="", title="Ficha breve")
        wrong = rich(isbn="9780140328721")
        result = rank_results([wrong, exact], "9788408163435", "isbn")
        self.assertEqual(result[0]["source_id"], exact["source_id"])
        self.assertIn("ISBN exacto", result[0]["ranking"]["reasons"])

    def test_normalization_does_not_penalize_accents_case_or_punctuation(self):
        self.assertEqual(similarity("LA SOMBRA: del viento!", "La sombra del viento"), 1)
        self.assertEqual(similarity("Carlos Ruiz Zafon", "Zafón, Carlos Ruiz", author=True), 1)

    def test_exact_title_beats_complete_but_different_title(self):
        exact = candidate(author="")
        wrong = rich(title="La sombra de otro viento")
        self.assertEqual(rank_results([wrong, exact], "La sombra del viento", "title")[0]["source_id"], exact["source_id"])

    def test_quality_resolves_equally_relevant_editions(self):
        poor, complete = candidate(), rich(isbn="9788408163435")
        self.assertEqual(rank_results([poor, complete], poor["title"], "title")[0]["source_id"], complete["source_id"])

    def test_title_filter_does_not_promote_matching_author(self):
        correct = candidate()
        wrong = rich(title="Otra obra", author=correct["title"])
        self.assertEqual(rank_results([wrong, correct], correct["title"], "title")[0]["source_id"], correct["source_id"])

    def test_author_filter_matches_reordered_name(self):
        right = candidate(author="Zafón, Carlos Ruiz")
        wrong = rich(author="Carlos Castaneda")
        self.assertEqual(rank_results([wrong, right], "Carlos Ruiz Zafon", "author")[0]["source_id"], right["source_id"])

    def test_author_entities_are_ranked_by_name_not_description(self):
        right = candidate(kind="author", title="Carlos Ruiz Zafón", author="escritor español", author_is_description=True)
        wrong = rich(kind="author", title="Otro autor", author="Carlos Ruiz Zafón", author_is_description=True)
        self.assertEqual(rank_results([wrong, right], "Carlos Ruiz Zafón", "author")[0]["source_id"], right["source_id"])

    def test_all_mode_understands_title_and_author_in_one_query(self):
        right = candidate()
        wrong = rich(title="El viento", author="Otra persona")
        result = rank_results([wrong, right], "sombra viento Carlos Zafon")
        self.assertEqual(result[0]["source_id"], right["source_id"])
        self.assertIn("Título y autor coincidentes", result[0]["ranking"]["reasons"])

    def test_synopsis_length_does_not_inflate_score(self):
        short = rich(synopsis="Breve descripción.")
        long = rich(synopsis="Mucho texto " * 1000)
        self.assertEqual(assess(short, short["title"])["score"], assess(long, short["title"])["score"])

    def test_work_publication_year_does_not_count_as_edition_date(self):
        base = candidate()
        self.assertEqual(assess(base, base["title"])["score"], assess({**base, "first_year": 2001}, base["title"])["score"])

    def test_unknown_values_and_unsafe_cover_do_not_earn_quality(self):
        item = candidate(author="Autor no disponible", cover_url="https://evil.example/cover", total_pages=-1)
        rank = assess(item, item["title"])
        self.assertEqual(rank["components"]["information"], 0)
        self.assertEqual(rank["components"]["cover"], 0)

    def test_language_aliases_and_unknown_language(self):
        for code in ("es", "spa", "español"):
            self.assertEqual(assess(candidate(language=code), "sombra")["components"]["language"], 5)
        self.assertEqual(assess(candidate(), "sombra")["components"]["language"], 0)
        self.assertEqual(assess(candidate(language="eng"), "sombra", preferred_language="en")["components"]["language"], 5)

    def test_work_cover_and_author_portrait_are_not_treated_as_edition_cover(self):
        work = candidate(cover_url=COVER, cover_scope="work")
        edition = candidate(cover_url=COVER, cover_scope="edition")
        portrait = candidate(cover_url=COVER, cover_scope="portrait")
        self.assertEqual(assess(work, "sombra")["components"]["cover"], 5)
        self.assertEqual(assess(edition, "sombra")["components"]["cover"], 10)
        self.assertEqual(assess(portrait, "sombra")["components"]["cover"], 0)

    def test_same_isbn_group_chooses_best_representative_and_keeps_originals(self):
        poor = candidate(isbn="9788408163435")
        complete = rich(provider="inventaire", key="inv:" + "a" * 32, isbn="8408163434")
        original = deepcopy([poor, complete])
        result = rank_results([poor, complete], poor["title"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["provider"], "inventaire")
        self.assertEqual(len(result[0]["alternatives"]), 1)
        self.assertIn("Mismo ISBN en 2 fuentes", result[0]["ranking"]["reasons"])
        self.assertEqual([poor, complete], original)

    def test_repeated_provider_and_conflicting_title_do_not_count_as_corroboration(self):
        item = candidate(isbn="9788408163435")
        duplicate = candidate("OL2M", isbn="9788408163435")
        self.assertEqual(rank_results([item, duplicate], item["title"])[0]["ranking"]["components"]["corroboration"], 0)
        conflict = candidate("inv:" + "a" * 32, provider="inventaire", isbn="9788408163435", title="Una historia totalmente distinta")
        self.assertEqual(rank_results([item, conflict], item["title"])[0]["ranking"]["components"]["corroboration"], 0)

    def test_group_fills_missing_metadata_from_compatible_edition_only(self):
        primary = rich(isbn="9788408163435", author="", provider="inventaire")
        complement = candidate(isbn="9788408163435")
        result = rank_results([primary, complement], "9788408163435")[0]
        self.assertEqual(result["provider"], "inventaire")
        self.assertEqual(result["author"], "Carlos Ruiz Zafón")
        self.assertEqual(result["search_field_sources"]["author"], "openlibrary")
        self.assertEqual(primary["author"], "")
        wrong = candidate(isbn="9788408163435", title="Otro libro", author="Un autor distinto")
        result = rank_results([primary, wrong], "9788408163435")[0]
        self.assertEqual(result["author"], "")

    def test_different_isbns_and_unknown_isbn_are_not_merged_by_title(self):
        first = candidate(isbn="9788408163435")
        second = candidate("OL2M", isbn="9780140328721")
        unknown = candidate("OL3M")
        self.assertEqual(len(rank_results([first, second, unknown], first["title"])), 3)

    def test_result_order_is_deterministic_and_repeatable(self):
        items = [candidate("OL3M"), candidate("OL1M"), candidate("OL2M")]
        ordered = rank_results(items, "sombra")
        self.assertEqual(ordered, rank_results(list(reversed(items)), "sombra"))
        self.assertEqual(ordered, rank_results(ordered, "sombra"))


class SearchRankingIntegrationTests(AppTestCase):
    def test_search_uses_ranker_and_template_explains_order_without_percentage(self):
        user = self.make_user()
        self.client.force_login(user)
        exact = candidate()
        wrong = rich(title="Una sombra diferente")
        with patch.object(catalog, "_worker", return_value={"items": [wrong, exact], "has_next": False}):
            result = catalog.search("La sombra del viento", "title", provider="openlibrary")
        self.assertEqual(result["items"][0]["source_id"], exact["source_id"])
        with patch.object(catalog, "search", return_value=result):
            response = self.client.get(reverse("catalog_search"), {"q": "La sombra del viento", "mode": "title"})
        self.assertContains(response, "Título exacto")
        self.assertContains(response, "Motivos del orden de búsqueda")
        self.assertNotContains(response, "100 %")
