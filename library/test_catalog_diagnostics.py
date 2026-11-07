from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch
from django.urls import reverse
from . import catalog
from .tests import AppTestCase


class CatalogDiagnosticsTests(AppTestCase):
    def test_request_logs_timeout_and_http_status_without_query_or_token(self):
        for error, detail in [(URLError(TimeoutError()), 'TimeoutError'),
                              (HTTPError('https://example.invalid/?q=PRIVATE_QUERY',429,'rate limit',{'Retry-After':'12'},None), "'http_status': 429")]:
            with self.subTest(error=type(error).__name__):
                with patch.object(catalog, 'urlopen', side_effect=error), patch.object(catalog.time, 'sleep'):
                    with self.assertLogs('library.catalog',level='WARNING') as logs:
                        with self.assertRaises(catalog.CatalogError):
                            catalog._request('/search.json',{'q':'PRIVATE_QUERY'})
                text=' '.join(logs.output)
                self.assertIn(detail,text)
                self.assertIn('provider=openlibrary',text)
                self.assertIn('elapsed_ms=',text)
                self.assertNotIn('PRIVATE_QUERY',text)
                self.assertNotIn('https://',text)

    def test_malformed_response_is_logged_but_not_response_body(self):
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'PRIVATE_RESPONSE'
        with patch.object(catalog,'urlopen',return_value=response):
            with self.assertLogs('library.catalog',level='WARNING') as logs:
                with self.assertRaises(catalog.CatalogError):
                    catalog._request('/search.json',{'q':'test'})
        self.assertIn('JSONDecodeError',' '.join(logs.output))
        self.assertNotIn('PRIVATE_RESPONSE',' '.join(logs.output))

    def test_rate_limit_honors_retry_after_without_another_network_request(self):
        error=HTTPError('https://example.invalid/',429,'rate limit',{'Retry-After':'1800'},None)
        with patch.object(catalog,'urlopen',side_effect=error) as remote, patch.object(catalog.time,'sleep'):
            with self.assertRaises(catalog.CatalogError):
                catalog._request('/search.json',{'q':'first'})
            with self.assertLogs('library.catalog',level='WARNING') as logs:
                with self.assertRaises(catalog.CatalogError):
                    catalog._request('/search.json',{'q':'another'})
        remote.assert_called_once()
        self.assertIn('rate_limit_cooldown',' '.join(logs.output))

    def test_partial_failure_uses_one_temporary_friendly_notification(self):
        self.client.force_login(self.make_user())
        with patch.object(catalog,'search',return_value={'items':[],'total':0,'has_next':False,'warnings':[],
                          'failed_providers':['openlibrary','inventaire'],'unavailable':False}):
            response=self.client.get(reverse('catalog_search'),{'q':'test','source':'openlibrary'})
        self.assertContains(response,'Algunas estanterías están tardando en abrir.')
        self.assertContains(response,'data-toast data-level="20"',count=1)
        self.assertContains(response,'data-toast-close')
        self.assertNotContains(response,'Open Library no ha respondido')
        self.assertNotContains(response,'Inventaire no ha respondido')
        self.assertEqual(response.status_code,200)

    def test_total_failure_has_persistent_retry_and_no_partial_toast(self):
        self.client.force_login(self.make_user())
        with patch.object(catalog,'search',return_value={'items':[],'total':0,'has_next':False,'warnings':[],
                          'failed_providers':['openlibrary'],'unavailable':True}):
            response=self.client.get(reverse('catalog_search'),{'q':'test','source':'openlibrary'})
        self.assertContains(response,'Reintentar búsqueda',status_code=503)
        self.assertNotContains(response,'Algunas estanterías',status_code=503)
