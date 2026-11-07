from copy import deepcopy
from unittest.mock import patch
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from . import catalog
from .catalog_views import _sign, _load
from .matching import same_work_confidence, group_works
from .ranking import rank_results
from .tests import AppTestCase


def edition(key="OL1M", **values):
    return {"provider": "openlibrary", "source_id": key, "kind": "edition",
            "title": "La sombra del viento", "author": "Carlos Ruiz Zafón", "isbn": "", **values}


class WorkMatchingTests(SimpleTestCase):
    def test_explicit_author_prefixes_accents_and_name_order(self):
        for author in ["libro de Carlos Ruiz Zafón", "Escrito por Carlos Ruiz Zafon", "written by Carlos Ruiz Zafón",
                       "Écrit par Carlos Ruiz Zafón", "scritto da Carlos Ruiz Zafón", "Ruiz Zafón, Carlos"]:
            report = same_work_confidence(edition(), edition("OL2M", author=author))
            self.assertEqual(report["score"], 98, author)
            self.assertTrue(report["automatic"])

    def test_initials_coauthors_and_translators_are_not_assumed_to_be_the_author(self):
        for author in ["C. Ruiz Zafón", "Carlos Ruiz", "Carlos Ruiz Zafón y Ana Pérez", "traducido por Carlos Ruiz Zafón", "Ana Pérez"]:
            self.assertFalse(same_work_confidence(edition(), edition("OL2M", author=author))["automatic"], author)

    def test_provider_description_needs_an_explicit_credit(self):
        self.assertTrue(same_work_confidence(edition(), edition("OL2M", author="novela de Carlos Ruiz Zafón", author_is_description=True))["automatic"])
        for author in ["Una novela ambientada en Barcelona", "novela de 2001 de Carlos Ruiz Zafón"]:
            self.assertFalse(same_work_confidence(edition(), edition("OL2M", author=author, author_is_description=True))["automatic"])

    def test_volume_digits_roman_numerals_and_spelled_out_parts_block_merges(self):
        for first, second in [("Una historia de muchas páginas Vol. 1", "Una historia de muchas páginas Vol. 2"),
                              ("Una historia de muchas páginas vol1", "Una historia de muchas páginas vol2"),
                              ("Una historia de muchas páginas tomo I", "Una historia de muchas páginas tomo II"),
                              ("Una historia de muchas páginas part one", "Una historia de muchas páginas part two")]:
            self.assertFalse(same_work_confidence(edition(title=first), edition("OL2M", title=second))["automatic"])

    def test_adaptations_guides_and_abridgements_remain_separate(self):
        for suffix in [": novela gráfica", ": guía de lectura", " (abridged)", " (adaptación)"]:
            self.assertFalse(same_work_confidence(edition(), edition("OL2M", title="La sombra del viento" + suffix))["automatic"])

    def test_generic_titles_and_missing_authors_need_more_evidence(self):
        self.assertFalse(same_work_confidence(edition(title="Cuentos"), edition("OL2M", title="Cuentos"))["automatic"])
        self.assertFalse(same_work_confidence(edition(author=""), edition("OL2M", author=""))["automatic"])
        self.assertFalse(same_work_confidence(edition(author="Ruiz"), edition("OL2M", author="Ruiz"))["automatic"])

    def test_shared_work_identity_allows_different_translated_titles(self):
        first = edition(work_key="/works/OL1W")
        second = edition("OL2M", work_key="/works/OL1W", title="The Shadow of the Wind", language="eng")
        self.assertEqual(same_work_confidence(first, second)["score"], 99)

    def test_even_shared_identifiers_do_not_override_author_conflicts(self):
        first = edition(work_key="/works/OL1W", isbn="9788408163435")
        second = edition("OL2M", work_key="/works/OL1W", isbn="9788408163435", author="Ana Pérez")
        self.assertFalse(same_work_confidence(first, second)["automatic"])
        self.assertEqual(len(rank_results([first, second], "sombra")), 2)

    def test_equal_isbn_with_conflicting_titles_is_not_merged(self):
        first = edition(isbn="9788408163435")
        second = edition("OL2M", isbn="9788408163435", title="Una obra completamente distinta")
        self.assertFalse(same_work_confidence(first, second)["automatic"])
        self.assertEqual(len(rank_results([first, second], "sombra")), 2)

    def test_different_isbns_become_options_without_merging_edition_fields(self):
        first = edition(isbn="9788408163435", language="spa", total_pages=575)
        second = edition("OL2M", isbn="9780140328721", language="eng", total_pages=400)
        raw = deepcopy([first, second])
        groups = group_works(rank_results(raw, "sombra"))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["kind"], "work_group")
        self.assertEqual(groups[0]["group_confidence"], 98)
        self.assertEqual({e["total_pages"] for e in groups[0]["editions"]}, {575, 400})
        self.assertEqual([first, second], raw)

    def test_grouping_cannot_join_by_transitive_similarity_alone(self):
        items = rank_results([edition("OL1M"), edition("OL2M"), edition("OL3M")], "sombra")
        def match(a, b):
            score = 80 if {a["source_id"], b["source_id"]} == {"OL1M", "OL3M"} else 98
            return {"score": score, "automatic": score >= 95, "reasons": []}
        with patch("library.matching.same_work_confidence", side_effect=match):
            groups = group_works(items)
        self.assertEqual(len(groups), 2)

    def test_author_entities_are_never_book_versions(self):
        self.assertFalse(same_work_confidence(edition(kind="author"), edition("OL2M", kind="author"))["automatic"])

    def test_grouping_is_stable_across_provider_arrival_order(self):
        items = [edition("OL3M"), edition("OL1M"), edition("OL2M")]
        self.assertEqual(group_works(rank_results(items, "sombra")), group_works(rank_results(list(reversed(items)), "sombra")))


class GroupSelectionTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)

    def test_group_links_are_short_bound_to_user_and_expire_with_the_cache(self):
        group = group_works(rank_results([edition("OL1M"), edition("OL2M", synopsis="word " * 10000)], "sombra"))[0]
        request = RequestFactory().get("/"); request.user = self.user
        token = _sign(request, group)
        self.assertLess(len(token), 500)
        self.assertEqual(_load(request, token)["data"]["kind"], "work_group")
        request.user = self.make_user("other@example.com")
        self.assertIsNone(_load(request, token))
        request.user = self.user
        cache.clear()
        self.assertIsNone(_load(request, token))

    def test_group_preview_requires_selecting_a_separate_edition(self):
        group = group_works(rank_results([edition("OL1M"), edition("OL2M")], "sombra"))[0]
        request = RequestFactory().get("/"); request.user = self.user
        token = _sign(request, group)
        with patch.object(catalog, "details") as details:
            response = self.client.get(reverse("catalog_preview"), {"selection": token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["options"]), 2)
        details.assert_not_called()
        self.assertEqual(self.client.post(reverse("catalog_save"), {"selection": token, "destination": "library"}).status_code, 404)

    def test_search_card_displays_confidence_and_version_link(self):
        group = group_works(rank_results([edition("OL1M"), edition("OL2M")], "sombra"))[0]
        with patch.object(catalog, "search", return_value={"items": [group], "total": 1, "warnings": [], "has_next": False}):
            response = self.client.get(reverse("catalog_search"), {"q": "sombra"})
        self.assertContains(response, "Confianza estimada")
        self.assertContains(response, "98 %")
        self.assertContains(response, "Ver versiones")

    def test_image_policy_accepts_official_archive_redirects(self):
        response = self.client.get(reverse("catalog_search"))
        policy = response.headers["Content-Security-Policy"]
        self.assertIn("https://*.us.archive.org", policy.split("img-src", 1)[1].split(";", 1)[0])
        self.assertIn("script-src 'self'", policy)

    def test_search_prefers_the_cover_for_the_selected_edition(self):
        raw = {"docs": [{"key": "OL1W", "title": "La sombra del viento", "author_name": ["Carlos Ruiz Zafón"],
                         "cover_i": 10107644, "editions": {"docs": [{"key": "/books/OL1M", "isbn": ["9788408163435"], "cover_i": 15156378}]}}]}
        with patch.object(catalog, "_request", return_value=raw) as remote:
            item = catalog.openlibrary_search("sombra")["items"][0]
        self.assertEqual(item["cover_scope"], "edition")
        self.assertIn("/15156378-M.jpg", item["cover_url"])
        self.assertIn("editions.cover_i", remote.call_args.args[1]["fields"])
