import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.web_demo import WebDemoMiddleware


class WebDemoTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.add_middleware(WebDemoMiddleware)

        @app.get('/health')
        def health():
            return {'ok': True, 'private': 'device details'}

        self.client = TestClient(app)

    def test_website_refuses_hardware_runtime(self):
        with patch('app.web_demo.RUNTIME_PROFILE', 'xline_ws3'):
            self.assertEqual(self.client.get('/health', headers={'X-XLine-Web-Demo': '1'}).status_code, 503)
            self.assertEqual(self.client.get('/health').status_code, 200)

    def test_website_health_is_minimal_on_virtual_backend(self):
        with patch('app.web_demo.RUNTIME_PROFILE', 'virtual_sim'):
            response = self.client.get('/health', headers={'X-XLine-Web-Demo': '1'})
            self.assertEqual(response.json(), {'ok': True, 'mode': 'web_cad', 'runtime_profile': 'virtual_sim'})


if __name__ == '__main__':
    unittest.main()
