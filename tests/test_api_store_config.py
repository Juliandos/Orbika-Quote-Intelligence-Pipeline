from __future__ import annotations

import importlib
import os
import sys
import unittest


class ApiStoreConfigTests(unittest.TestCase):
    def load_config(self, **env):
        keys = ("DATABASE_URL", "ORBIKA_API_STORE")
        original = {key: os.environ.get(key) for key in keys}
        try:
            for key in keys:
                os.environ.pop(key, None)
            for key, value in env.items():
                if value is not None:
                    os.environ[key] = value
            sys.modules.pop("apps.api.orbika_console_api.config", None)
            return importlib.import_module("apps.api.orbika_console_api.config")
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            sys.modules.pop("apps.api.orbika_console_api.config", None)

    def test_defaults_to_postgres_when_database_url_exists(self):
        config = self.load_config(DATABASE_URL="postgresql://example")
        self.assertEqual(config.DEFAULT_API_STORE, "postgres")
        self.assertEqual(config.API_STORE, "postgres")

    def test_defaults_to_json_without_database_url(self):
        config = self.load_config()
        self.assertEqual(config.DEFAULT_API_STORE, "json")
        self.assertEqual(config.API_STORE, "json")

    def test_explicit_override_wins(self):
        config = self.load_config(DATABASE_URL="postgresql://example", ORBIKA_API_STORE="json")
        self.assertEqual(config.DEFAULT_API_STORE, "postgres")
        self.assertEqual(config.API_STORE, "json")


if __name__ == "__main__":
    unittest.main()
