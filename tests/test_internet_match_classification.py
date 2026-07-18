from __future__ import annotations

import unittest

from apps.api.orbika_console_api.postgres_store import _is_internet_match_option


class InternetMatchClassificationTests(unittest.TestCase):
    def test_source_type_internet_search_is_treated_as_internet(self):
        self.assertTrue(_is_internet_match_option({"source_type": "internet_search"}))

    def test_web_validated_match_type_is_treated_as_internet(self):
        self.assertTrue(_is_internet_match_option({"match_type": "web_validated"}))

    def test_category_only_match_type_is_not_treated_as_internet(self):
        self.assertFalse(_is_internet_match_option({"match_type": "category_only"}))

    def test_non_dict_is_not_treated_as_internet(self):
        self.assertFalse(_is_internet_match_option("not-a-dict"))


if __name__ == "__main__":
    unittest.main()
