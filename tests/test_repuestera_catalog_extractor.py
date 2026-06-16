import unittest

from tools.repuestera_catalog_extractor import (
    build_catalog_page_url,
    infer_match,
    parse_category_carousel,
    parse_max_page_number,
    parse_product_cards,
)


SHOP_HTML = """
<link rel="next" href="https://repuestera.com.co/shop/page/2/" />
<div class="elementor-widget-container">
  <div class="elementor-jet-woo-categories jet-woo-builder">
    <div class="jet-woo-categories__item swiper-slide">
      <div class="jet-woo-categories__inner-box">
        <div class="jet-woo-categories-thumbnail__wrap">
          <div class="jet-woo-category-thumbnail">
            <a href="https://repuestera.com.co/categoria-producto/accesorios/" rel="bookmark">
              <img src="https://repuestera.com.co/wp-content/uploads/accesorios.png" alt="" />
            </a>
          </div>
        </div>
        <div class="jet-woo-categories-content">
          <h4 class="jet-woo-category-title">
            <a href="https://repuestera.com.co/categoria-producto/accesorios/" class="jet-woo-category-title__link">Accesorios</a>
          </h4>
        </div>
      </div>
    </div>
    <div class="jet-woo-categories__item swiper-slide">
      <div class="jet-woo-categories__inner-box">
        <div class="jet-woo-categories-thumbnail__wrap">
          <div class="jet-woo-category-thumbnail">
            <a href="https://repuestera.com.co/categoria-producto/suspension/" rel="bookmark">
              <img src="https://repuestera.com.co/wp-content/uploads/suspension.png" alt="" />
            </a>
          </div>
        </div>
        <div class="jet-woo-categories-content">
          <h4 class="jet-woo-category-title">
            <a href="https://repuestera.com.co/categoria-producto/suspension/" class="jet-woo-category-title__link">Suspensión</a>
          </h4>
        </div>
      </div>
    </div>
  </div>
</div>
<div id="productos" data-pages="8"></div>
<div class="jet-listing-grid__item jet-listing-dynamic-post-3149 jet-equal-columns" data-post-id="3149">
  <div class="jet-listing jet-listing-dynamic-image">
    <a href="https://repuestera.com.co/producto/bomba-agua-tucson/" class="jet-listing-dynamic-image__link">
      <img src="https://repuestera.com.co/wp-content/uploads/25100-23022.png" class="jet-listing-dynamic-image__img attachment-full size-full" alt="BOMBA AGUA TUCSON 2.0 GASOLINA" />
    </a>
  </div>
  <div class="jet-listing-dynamic-field__content">25100-23022</div>
  <div class="jet-listing-dynamic-field__content">BOMBA AGUA TUCSON 2.0 GASOLINA</div>
  <span class="jet-listing-dynamic-terms__link">Mobis</span>
  <span class="jet-listing-dynamic-terms__link">Sistema de refrigeración</span>
  <a class="elementor-button elementor-button-link elementor-size-sm" href="https://repuestera.com.co/producto/bomba-agua-tucson/">
    <span class="elementor-button-text">Ver detalles</span>
  </a>
</div>
<div class="jet-listing-grid__item jet-listing-dynamic-post-5008 jet-equal-columns" data-post-id="5008">
  <div class="jet-listing jet-listing-dynamic-image">
    <a href="https://repuestera.com.co/producto/filtro-aire-tucson/" class="jet-listing-dynamic-image__link">
      <img src="https://repuestera.com.co/wp-content/uploads/28113-2S000.png" class="jet-listing-dynamic-image__img attachment-full size-full" alt="FILTRO AIRE TUCSON" />
    </a>
  </div>
  <div class="jet-listing-dynamic-field__content">28113-2S000</div>
  <div class="jet-listing-dynamic-field__content">FILTRO AIRE TUCSON</div>
  <span class="jet-listing-dynamic-terms__link">Hyundai</span>
  <span class="jet-listing-dynamic-terms__link">Filtración</span>
  <a class="elementor-button elementor-button-link elementor-size-sm" href="https://repuestera.com.co/producto/filtro-aire-tucson/">
    <span class="elementor-button-text">Ver detalles</span>
  </a>
</div>
"""

SHOP_HTML_FIELD_FALLBACK = """
<div class="jet-listing-grid__item jet-listing-dynamic-post-5009 jet-equal-columns" data-post-id="5009">
  <div class="jet-listing jet-listing-dynamic-image">
    <a href="https://repuestera.com.co/producto/filtro-aire-santa-fe-2-2-kia-sportage-gran-carnival-2-2-sorento-2-4/" class="jet-listing-dynamic-image__link">
      <img src="https://repuestera.com.co/wp-content/uploads/28113-N9000.png" class="jet-listing-dynamic-image__img attachment-full size-full" alt="FILTRO AIRE SANTA FE 2.2/KIA SPORTAGE/GRAN CARNIVAL 2.2/SORENTO 2.4" />
    </a>
  </div>
  <div class="jet-listing-dynamic-field__content">28113-N9000</div>
  <div class="jet-listing-dynamic-field__content">FILTRO AIRE SANTA FE 2.2/KIA SPORTAGE/GRAN CARNIVAL 2.2/SORENTO 2.4</div>
  <div class="jet-listing-dynamic-field__content">MOBIS</div>
  <div class="jet-listing-dynamic-field__content">FILTRACIÓN</div>
  <a class="elementor-button elementor-button-link elementor-size-sm" href="https://repuestera.com.co/producto/filtro-aire-santa-fe-2-2-kia-sportage-gran-carnival-2-2-sorento-2-4/">
    <span class="elementor-button-text">Ver detalles</span>
  </a>
</div>
"""


class RepuesteraCatalogExtractorTests(unittest.TestCase):
    def test_parse_category_carousel_extracts_visible_entries(self) -> None:
        categories = parse_category_carousel(SHOP_HTML)

        self.assertEqual(len(categories), 2)
        self.assertEqual(categories[0].category_name, "Accesorios")
        self.assertEqual(categories[1].category_url, "https://repuestera.com.co/categoria-producto/suspension/")

    def test_parse_product_cards_extracts_initial_info_and_detail_link(self) -> None:
        products = parse_product_cards(
            SHOP_HTML,
            source_page_url="https://repuestera.com.co/shop/",
            page_number=1,
        )

        self.assertEqual(len(products), 2)
        first = products[0]
        self.assertEqual(first.post_id, "3149")
        self.assertEqual(first.reference, "25100-23022")
        self.assertEqual(first.product_name, "BOMBA AGUA TUCSON 2.0 GASOLINA")
        self.assertEqual(first.brand, "Mobis")
        self.assertEqual(first.category_name, "Sistema de refrigeración")
        self.assertEqual(first.detail_url, "https://repuestera.com.co/producto/bomba-agua-tucson/")
        self.assertEqual(first.match_type, "exact_reference")

    def test_parse_product_cards_uses_dynamic_field_fallback_for_brand_and_category(self) -> None:
        products = parse_product_cards(
            SHOP_HTML_FIELD_FALLBACK,
            source_page_url="https://repuestera.com.co/shop/",
            page_number=1,
        )

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].brand, "MOBIS")
        self.assertEqual(products[0].category_name, "FILTRACIÓN")

    def test_parse_max_page_number_prefers_highest_public_signal(self) -> None:
        self.assertEqual(parse_max_page_number(SHOP_HTML), 8)

    def test_build_catalog_page_url_handles_page_one_and_pagination(self) -> None:
        self.assertEqual(build_catalog_page_url(1), "https://repuestera.com.co/shop/")
        self.assertEqual(build_catalog_page_url(3), "https://repuestera.com.co/shop/page/3/")

    def test_infer_match_downgrades_when_reference_is_missing(self) -> None:
        self.assertEqual(
            infer_match(None, "FILTRO AIRE TUCSON", "Hyundai", "Filtración"),
            ("category_only", "medium"),
        )
        self.assertEqual(
            infer_match(None, "", None, None),
            ("manual_confirmation_required", "low"),
        )


if __name__ == "__main__":
    unittest.main()
