import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.json"
        self.config = {
            "DATABASE_URL": "dbname=calendar_test",
            "SECRET_KEY": "test-key-" * 5,
            "CORS_ORIGINS": "https://frontend.example",
        }

    def write_config(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def test_file_configures_app_instead_of_environment(self):
        self.write_config(self.config)
        with patch("app.CONFIG_PATH", self.path), patch.dict(os.environ, {
            "DATABASE_URL": "dbname=wrong",
            "SECRET_KEY": "wrong",
            "CORS_ORIGINS": "https://wrong.example",
        }):
            app = create_app()
        self.assertEqual(app.config["DATABASE_URL"], self.config["DATABASE_URL"])
        self.assertEqual(app.config["SECRET_KEY"], self.config["SECRET_KEY"])
        response = app.test_client().get("/api/me", headers={"Origin": "https://frontend.example"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "https://frontend.example")

    def test_missing_and_invalid_file_errors_are_explicit(self):
        with patch("app.CONFIG_PATH", self.path):
            with self.assertRaisesRegex(RuntimeError, "No existe"):
                create_app()
            self.path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "JSON válido"):
                create_app()
            self.write_config([])
            with self.assertRaisesRegex(RuntimeError, "objeto JSON"):
                create_app()
            self.path.write_bytes(b"\xff")
            with self.assertRaisesRegex(RuntimeError, "UTF-8"):
                create_app()

    def test_invalid_settings_are_rejected(self):
        for field, value in (
            ("DATABASE_URL", ""), ("DATABASE_URL", 42),
            ("SECRET_KEY", "short"), ("SECRET_KEY", None),
            ("CORS_ORIGINS", []),
        ):
            with self.subTest(field=field, value=value):
                self.write_config({**self.config, field: value})
                with patch("app.CONFIG_PATH", self.path), self.assertRaisesRegex(RuntimeError, field):
                    create_app()

    def test_explicit_test_config_does_not_require_a_file(self):
        with patch("app.CONFIG_PATH", self.path):
            app = create_app({**self.config, "TESTING": True})
        self.assertTrue(app.config["TESTING"])

    def test_empty_cors_disables_cross_origin_headers(self):
        self.write_config({**self.config, "CORS_ORIGINS": ""})
        with patch("app.CONFIG_PATH", self.path):
            app = create_app()
        response = app.test_client().get("/api/me", headers={"Origin": "https://frontend.example"})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)


if __name__ == "__main__":
    unittest.main()
