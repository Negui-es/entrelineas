from django.urls import reverse
from unittest.mock import patch
from django.test import RequestFactory, SimpleTestCase, override_settings
from . import catalog, catalog_extra as extra
from .tests import AppTestCase
from .catalog_views import _sign

ISBN = "9788408163435"
BBID = "0b5a7a45-b3b1-40e8-83f7-8c127261b6c8"
BNE_XML = '''<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
<numberOfRecords>1</numberOfRecords><records><record><recordData>
<record xmlns="http://www.loc.gov/MARC21/slim">
<controlfield tag="001">991058669249708606</controlfield>
<datafield tag="020"><subfield code="a">978-84-08-16343-5 (rústica)</subfield></datafield>
<datafield tag="245"><subfield code="a">La sombra del viento /</subfield></datafield>
<datafield tag="100"><subfield code="a">Ruiz Zafón, Carlos</subfield></datafield>
<datafield tag="700"><subfield code="a">Un traductor</subfield></datafield>
<datafield tag="260"><subfield code="b">Booket,</subfield><subfield code="c">2016</subfield></datafield>
<datafield tag="300"><subfield code="a">575 p.</subfield></datafield>
<datafield tag="041"><subfield code="a">spa</subfield></datafield>
</record></recordData></record></records></searchRetrieveResponse>'''


class ExtraProviderTests(SimpleTestCase):
    @patch.object(extra, "_request", return_value=BNE_XML)
    def test_bne_parse_and_exact_isbn(self, request):
        item = extra.bne_search(ISBN, "isbn")["items"][0]
        self.assertEqual(item["isbn"], ISBN)
        self.assertEqual(item["total_pages"], 575)
        self.assertEqual(item["publisher"], "Booket")
        self.assertEqual(item["author"], "Ruiz Zafón, Carlos")
        self.assertEqual(item["language"], "spa")
        self.assertEqual(extra.bne_search("9780140328721", "isbn")["items"], [])
        self.assertIn("catalogo.bne.es", catalog.source_url(item))

    @patch.object(extra, "_request", return_value=BNE_XML)
    def test_bne_details_refresh_by_id_and_reject_changed_isbn(self, request):
        selection = {"source_id": "991058669249708606", "isbn": ISBN}
        self.assertEqual(extra.bne_details(selection)["isbn"], ISBN)
        self.assertIn("alma.mms_id=", request.call_args.args[1]["query"])
        with self.assertRaises(catalog.CatalogError):
            extra.bne_details({**selection, "isbn": "9780140328721"})
        with self.assertRaises(catalog.CatalogError):
            extra.bne_details({"source_id": '123" or alma.title="*'})

    def test_bne_xml_and_query_boundaries(self):
        for xml in ["<!DOCTYPE foo><foo/>", "<broken", '<x><diagnostic xmlns="urn:test"/></x>']:
            with patch.object(extra, "_request", return_value=xml), self.assertRaises(catalog.CatalogError):
                extra.bne_search("libro")
        self.assertEqual(extra.cql_literal('x" or alma.title="y'), '"x\\" or alma.title=\\"y"')

    @patch.object(extra, "_request")
    def test_bne_exact_query_selects_matching_secondary_isbn(self, request):
        request.return_value = BNE_XML.replace('<datafield tag="020">', '<datafield tag="020"><subfield code="a">9780140328721</subfield></datafield><datafield tag="020">', 1)
        item = extra.bne_search(ISBN, "isbn")["items"][0]
        self.assertEqual(item["isbn"], ISBN)
        self.assertEqual(extra.bne_details(item)["isbn"], ISBN)

    @patch.object(extra, "_request")
    def test_bookbrainz_search_author_and_edition_details(self, request):
        raw = {"bbid": BBID, "defaultAlias": {"name": "Un libro", "language": "eng"}, "authors": []}
        request.return_value = {"searchResult": [raw], "totalCount": 15}
        result = extra.bookbrainz_search("Un libro", "title")
        self.assertTrue(result["has_next"])
        self.assertEqual(result["items"][0]["language"], "")
        self.assertEqual(extra.bookbrainz_search("Autora", "author")["items"][0]["kind"], "author")
        request.side_effect = [{**raw, "authorCredits": {"names": [{"name": "Autora"}]}, "pages": 223,
                                "languages": ["spa"], "releaseEventDate": "+001997-07-26"},
                               {"identifiers": [{"type": "ISBN-13", "value": ISBN}]}]
        item = extra.bookbrainz_details({"source_id": BBID})
        self.assertEqual((item["author"], item["isbn"], item["total_pages"]), ("Autora", ISBN, 223))

    @patch.object(extra, "_request")
    def test_bookbrainz_author_related_editions_and_isbn_limitation(self, request):
        request.return_value = {"editions": [{"entity": {"bbid": BBID, "defaultAlias": {"name": "Libro"}}}]}
        self.assertEqual(len(extra.bookbrainz_options({"source_id": BBID, "kind": "author"})), 1)
        request.reset_mock()
        self.assertEqual(extra.bookbrainz_search(ISBN)["items"], [])
        request.assert_not_called()

    @override_settings(BOKTYVEN_API_TOKEN="")
    def test_boktyven_disabled_without_token(self):
        self.assertNotIn("boktyven", catalog.enabled_providers())
        with self.assertRaises(catalog.CatalogError):
            catalog.search("Un libro", provider="boktyven")
        with self.assertRaises(catalog.CatalogError):
            catalog._request("/books/search", {"q": "libro"}, "boktyven")

    @override_settings(BOKTYVEN_API_TOKEN="test-secret")
    @patch.object(extra, "_request")
    def test_boktyven_filters_and_verified_details(self, request):
        self.assertIn("boktyven", catalog.enabled_providers())
        request.return_value = {"results": [{"isbn": ISBN, "title": "La sombra del viento", "author": "Carlos Ruiz Zafón",
                                             "publicationYear": 2016, "coverUrl": "https://evil.example/tracker"},
                                            {"isbn": "9780140328721", "title": "Matilda"}]}
        self.assertEqual(len(extra.boktyven_search(ISBN)["items"]), 1)
        self.assertEqual(len(extra.boktyven_search("Zafón", "author")["items"]), 1)
        item = extra.boktyven_details({"source_id": ISBN})
        self.assertEqual(item["cover_url"], "")
        self.assertEqual(item["publication_date"], "2016")
        request.reset_mock()
        self.assertEqual(extra.boktyven_search("libro", page=2)["items"], [])
        request.assert_not_called()


class NewProviderFlowTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)

    def token(self, item):
        request = RequestFactory().get("/")
        request.user = self.user
        return _sign(request, item)

    def test_new_provider_preview_store_and_attribution(self):
        with patch.object(extra, "_request", return_value=BNE_XML):
            item = extra.bne_search(ISBN)["items"][0]
            response = self.client.get(reverse("catalog_preview"), {"selection": self.token(item)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Biblioteca Nacional de España")
        data = response.context["item"]
        from .catalog_store import store_edition
        edition = store_edition(data)
        self.assertEqual(edition.sources.get().provider, "bne")
        self.assertEqual(edition.isbn, ISBN)

    def test_provider_selector_and_author_options(self):
        response = self.client.get(reverse("catalog_search"))
        self.assertContains(response, 'value="bne"')
        self.assertContains(response, 'value="bookbrainz"')
        self.assertNotContains(response, 'value="boktyven"')
        selection = {"provider": "bookbrainz", "kind": "author", "source_id": BBID, "title": "Autora"}
        with patch.object(extra, "bookbrainz_options", return_value=[]):
            response = self.client.get(reverse("catalog_preview"), {"selection": self.token(selection)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "BookBrainz")

    @override_settings(BOKTYVEN_API_TOKEN="server-only-secret")
    def test_token_is_only_sent_as_server_header(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"results": []}'
        with patch.object(catalog.cache, "get", side_effect=lambda key, default=None: default), patch.object(catalog.cache, "add", return_value=True), \
             patch.object(catalog.cache, "set"), patch.object(catalog.cache, "delete"), \
             patch.object(catalog, "urlopen", return_value=response) as remote:
            self.assertEqual(catalog._request("/books/search", {"q": "libro"}, "boktyven"), {"results": []})
        request = remote.call_args.args[0]
        self.assertEqual(request.get_header("X-access-token"), "server-only-secret")
        self.assertNotIn("server-only-secret", request.full_url)
        page = self.client.get(reverse("catalog_search"))
        self.assertContains(page, 'value="boktyven"')
        self.assertNotContains(page, "server-only-secret")
