import unittest

from tools.disfal_catalog_extractor import (
    normalize_service_slug,
    parse_amortiguadores_series,
    parse_brand_landing_pages,
    parse_service_family_links,
    parse_series_heading,
    taxonomy_for_service_slug,
)


HOME_HTML = """
<nav>
  <a href="https://www.disfal.com/services/amortiguadores/">Amortiguadores</a>
  <a href="https://www.disfal.com/services/correas/">Correas</a>
  <a href="https://www.disfal.com/services/liquido-de-frenos-colombia/">Liquido de frenos</a>
  <a href="https://www.disfal.com/amortiguadores-paxis-en-colombia/">Paxis</a>
  <a href="https://www.disfal.com/repuestos-monroe-colombia/">Monroe</a>
  <a href="https://www.disfal.com/repuestos-dayco-colombia/">Dayco</a>
</nav>
"""

AMORTIGUADORES_HTML = """
<section>
  <h2>Amortiguadores</h2>
  <h2>PAXIS</h2>
  <img data-src="https://www.disfal.com/wp-content/uploads/paxis.png" />
  <h2>MONROE MONRO-MATIC PLUS: Serie 31000 - 32000 - 33000</h2>
  <img src="https://www.disfal.com/wp-content/uploads/monroe-monro-matic-plus.jpg" />
  <h2>MONROE GAS MAGNUM: Serie 34000</h2>
  <h2>AMORTIGUADORES RANCHO: Serie RS</h2>
  <h2>Amortiguadores Preguntas Frecuentes</h2>
</section>
"""


class DisfalCatalogExtractorTests(unittest.TestCase):
    def test_parse_service_family_links_extracts_public_families(self) -> None:
        families = parse_service_family_links(HOME_HTML)

        self.assertEqual(len(families), 3)
        self.assertEqual(families[0].family_name, "Amortiguadores")
        self.assertEqual(families[0].taxonomy_label, "suspension_steering")
        self.assertEqual(families[2].family_slug, "liquido-de-frenos")

    def test_parse_brand_landing_pages_extracts_known_public_brand_links(self) -> None:
        brands = parse_brand_landing_pages(HOME_HTML)

        self.assertEqual(len(brands), 3)
        self.assertEqual(brands[0].brand_name, "PAXIS")
        self.assertEqual(brands[1].brand_name, "MONROE")
        self.assertEqual(brands[2].brand_url, "https://www.disfal.com/repuestos-dayco-colombia/")

    def test_parse_series_heading_understands_monroe_and_rancho_formats(self) -> None:
        self.assertEqual(
            parse_series_heading("MONROE GAS MAGNUM: Serie 34000"),
            ("MONROE", "GAS MAGNUM", "Serie 34000"),
        )
        self.assertEqual(
            parse_series_heading("AMORTIGUADORES RANCHO: Serie RS"),
            ("RANCHO", "AMORTIGUADORES RANCHO", "Serie RS"),
        )
        self.assertEqual(parse_series_heading("PAXIS"), ("PAXIS", None, None))
        self.assertIsNone(parse_series_heading("Amortiguadores Preguntas Frecuentes"))

    def test_parse_amortiguadores_series_extracts_partial_verification_entries(self) -> None:
        entries = parse_amortiguadores_series(
            AMORTIGUADORES_HTML,
            "https://www.disfal.com/services/amortiguadores/",
        )

        self.assertEqual(len(entries), 4)
        self.assertEqual(entries[0].brand_name, "PAXIS")
        self.assertEqual(entries[1].commercial_line, "MONRO-MATIC PLUS")
        self.assertEqual(entries[1].series_label, "Serie 31000 - 32000 - 33000")
        self.assertEqual(entries[1].image_url, "https://www.disfal.com/wp-content/uploads/monroe-monro-matic-plus.jpg")
        self.assertTrue(entries[2].requires_manual_confirmation)

    def test_normalize_service_slug_removes_colombia_suffix(self) -> None:
        self.assertEqual(
            normalize_service_slug("https://www.disfal.com/services/liquido-de-frenos-colombia/"),
            "liquido-de-frenos",
        )
        self.assertEqual(taxonomy_for_service_slug("crucetas"), "driveline")


if __name__ == "__main__":
    unittest.main()
