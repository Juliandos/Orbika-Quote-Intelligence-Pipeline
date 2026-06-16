import unittest

from tools.partcar_catalog_extractor import (
    build_catalog_page_url,
    infer_taxonomy,
    parse_next_page_number,
    parse_product_cards,
)


PAGE_ONE_HTML = """
<html>
  <head>
    <link rel="next" href="https://www.partcar.com.co/importacion-1?dynamic_page=2"/>
  </head>
  <body>
    <div role="listitem" class="_FiCX">
      <a data-testid="linkElement" href="https://www.partcar.com.co/importacion-1/farola-mazda-323-1988-2004-derecha-tyc">
        <img src="https://www.autolatas.co/cat/3178.jpg" alt="323" />
      </a>
      <h2><span><span>Farola Derecha Para Mazda 323 Modelos 1988 A 2004 Tyc</span></span></h2>
      <p><span><span>3178</span></span></p>
    </div>
    <div role="listitem" class="_FiCX">
      <a data-testid="linkElement" href="https://www.partcar.com.co/importacion-1/espejo-chevrolet-spark-izquierdo">
        <img src="https://www.autolatas.co/cat/4500.jpg" alt="Spark" />
      </a>
      <h2><span><span>Espejo Izquierdo Para Chevrolet Spark</span></span></h2>
      <p><span><span>4500</span></span></p>
    </div>
  </body>
</html>
"""


class PartcarCatalogExtractorTests(unittest.TestCase):
    def test_parse_product_cards_extracts_listing_fields(self) -> None:
        products = parse_product_cards(
            PAGE_ONE_HTML,
            source_page_url="https://www.partcar.com.co/importacion-1",
            page_number=1,
        )

        self.assertEqual(len(products), 2)
        self.assertEqual(products[0].product_name, "Farola Derecha Para Mazda 323 Modelos 1988 A 2004 Tyc")
        self.assertEqual(products[0].supplier_item_code, "3178")
        self.assertEqual(
            products[0].detail_url,
            "https://www.partcar.com.co/importacion-1/farola-mazda-323-1988-2004-derecha-tyc",
        )
        self.assertEqual(products[0].taxonomy_label, "lighting_headlamps")
        self.assertEqual(products[1].taxonomy_label, "mirrors")

    def test_parse_next_page_number_reads_public_dynamic_page_link(self) -> None:
        self.assertEqual(parse_next_page_number(PAGE_ONE_HTML), 2)
        self.assertIsNone(parse_next_page_number("<html></html>"))

    def test_build_catalog_page_url_uses_dynamic_page_pattern(self) -> None:
        self.assertEqual(build_catalog_page_url(1), "https://www.partcar.com.co/importacion-1")
        self.assertEqual(
            build_catalog_page_url(3),
            "https://www.partcar.com.co/importacion-1?dynamic_page=3",
        )

    def test_infer_taxonomy_maps_visible_title_keywords(self) -> None:
        self.assertEqual(infer_taxonomy("Farola Izquierda Para Hyundai Atos")[0], "lighting_headlamps")
        self.assertEqual(infer_taxonomy("Stop Derecho Para Mazda 626")[0], "lighting_tail_lamps")
        self.assertEqual(infer_taxonomy("Parachoque Delantero")[0], "body_exterior")
        self.assertEqual(infer_taxonomy("Pieza Especial Desconocida")[0], "manual_review")


if __name__ == "__main__":
    unittest.main()
