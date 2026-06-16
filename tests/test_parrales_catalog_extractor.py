import unittest

from tools.parrales_catalog_extractor import (
    assign_category_names,
    enrich_taxonomy_from_listing_products,
    parse_filter_taxonomy,
    parse_listing_products,
    parse_price_to_int,
    parse_product_detail,
    split_category_slugs,
    ListingProduct,
)


LISTING_HTML = """
<div class="filters">
  <a href="https://parrales.com.co/product-category/pitos/">Pitos</a> (41)
  <a href="https://parrales.com.co/product-category/de-reversa/">De reversa</a> (8)
</div>
<ul class="products-loop row grid clearfix">
  <li class="item post-23891 product type-product product_brand-vektra product_cat-de-reversa product_cat-pitos sale">
    <div class="item-detail">
      <div class="item-img products-thumb">
        <a href="https://parrales.com.co/product/pito-12v-60v-reversa-18w-vkh-9101jn-910107090810/">
          <div class="product-thumb-hover">
            <img src="https://parrales.com.co/wp-content/uploads/example.png" alt="">
          </div>
        </a>
        <div class="sale-off">-30%</div>
      </div>
      <div class="item-content products-content">
        <h4><a href="https://parrales.com.co/product/pito-12v-60v-reversa-18w-vkh-9101jn-910107090810/" title="Alarma de Retroceso Vektra Tipo Pollak – Universal 12V-60V 18W">Alarma de Retroceso Vektra Tipo Pollak – Universal 12V-60V 18W</a></h4>
        <span class="item-price"><del aria-hidden="true"><span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol">&#36;</span>&nbsp;50.000</bdi></span></del><ins aria-hidden="true"><span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol">&#36;</span>&nbsp;35.000</bdi></span></ins></span>
        <div class="item-description">MARCA: VEKTRA REF: VKH-9101 WATTS: 18w VOLTAJE: 12v-60v</div>
        <div class="item-bottom clearfix">
          <a href="/tienda/?add-to-cart=23891" data-product_id="23891" data-product_sku="JN-9101" class="button product_type_simple add_to_cart_button ajax_add_to_cart">Añadir al carrito</a>
        </div>
      </div>
    </div>
  </li>
</ul>
"""


DETAIL_HTML = """
<h1 class="product_title entry-title">Alarma de Retroceso Vektra Tipo Pollak – Universal 12V-60V 18W</h1>
<div class="woocommerce-product-details__short-description">
  <p>MARCA: VEKTRA<br />
  REF: VKH-9101</p>
  <p>WATTS: 18w</p>
  <p>VOLTAJE: 12v-60v</p>
</div>
<p class="price"><del aria-hidden="true"><span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol">&#36;</span>&nbsp;50.000</bdi></span></del> <span class="screen-reader-text">Original price was: &#036;&nbsp;50.000.</span><ins aria-hidden="true"><span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol">&#36;</span>&nbsp;35.000</bdi></span></ins><span class="screen-reader-text">Current price is: &#036;&nbsp;35.000.</span></p>
<meta itemprop="price" content="35000" />
<meta itemprop="priceCurrency" content="COP" />
<meta property="og:image" content="https://parrales.com.co/wp-content/uploads/example.png" />
<div class="product-info product_meta">
  <span class="sku_wrapper">SKU: <span class="sku" itemprop="sku">JN-9101</span></span>
</div>
<div class="item-brand">
  <span>Product by: </span>
  <a href="https://parrales.com.co/product_brand/vektra/">Vektra</a>
</div>
<div class="tab-pane active" id="tab-description">
  <h2>Descripción</h2>
  <p>La alarma sirve para camiones y buses.</p>
  <ul>
    <li><p><strong>Marca:</strong> Vektra</p></li>
    <li><p><strong>Referencia:</strong> VKH-9101</p></li>
    <li><p><strong>Potencia:</strong> 18W</p></li>
    <li><p><strong>Compatibilidad:</strong> Autos, buses, camiones</p></li>
  </ul>
</div>
"""


class ParralesCatalogExtractorTests(unittest.TestCase):
    def test_parse_price_to_int_handles_cop_values(self) -> None:
        self.assertEqual(parse_price_to_int("$ 110.392"), 110392)
        self.assertEqual(parse_price_to_int("35.000"), 35000)
        self.assertIsNone(parse_price_to_int(""))

    def test_parse_listing_products_extracts_individual_products(self) -> None:
        taxonomy = parse_filter_taxonomy(LISTING_HTML)

        products = parse_listing_products(LISTING_HTML, taxonomy)

        self.assertEqual(len(products), 1)
        product = products[0]
        self.assertEqual(product.product_id, "23891")
        self.assertEqual(product.sku, "JN-9101")
        self.assertEqual(product.category_name, "Pitos")
        self.assertEqual(product.subcategory_name, "De reversa")
        self.assertEqual(product.price_current, 35000)
        self.assertEqual(product.price_original, 50000)
        self.assertTrue(product.on_sale)
        self.assertEqual(product.listing_attributes["marca"], "VEKTRA")

    def test_parse_filter_taxonomy_reads_relative_product_category_urls(self) -> None:
        taxonomy = parse_filter_taxonomy(LISTING_HTML)

        self.assertEqual(taxonomy["pitos"], "Pitos")
        self.assertEqual(taxonomy["de-reversa"], "De reversa")

    def test_enrich_taxonomy_from_listing_products_falls_back_to_css_categories(self) -> None:
        products = parse_listing_products(LISTING_HTML, {})

        taxonomy = enrich_taxonomy_from_listing_products({}, products)

        self.assertEqual(taxonomy["pitos"], "Pitos")
        self.assertEqual(taxonomy["de-reversa"], "De Reversa")

    def test_parse_product_detail_extracts_brand_reference_sku_and_description(self) -> None:
        taxonomy = parse_filter_taxonomy(LISTING_HTML)
        listing_product = parse_listing_products(LISTING_HTML, taxonomy)[0]

        extracted = parse_product_detail(DETAIL_HTML, listing_product)

        self.assertEqual(extracted.brand, "Vektra")
        self.assertEqual(extracted.reference, "VKH-9101")
        self.assertEqual(extracted.sku, "JN-9101")
        self.assertEqual(extracted.price_current, 35000)
        self.assertEqual(extracted.price_original, 50000)
        self.assertEqual(extracted.match_type, "exact_reference")
        self.assertIn("camiones", extracted.description.lower())

    def test_category_slug_assignment_prefers_known_top_level_category(self) -> None:
        taxonomy = {"pitos": "Pitos", "de-reversa": "De reversa"}

        category_slug, category_name, subcategory_slug, subcategory_name = assign_category_names(
            split_category_slugs("product_cat-de-reversa product_cat-pitos"),
            taxonomy,
        )

        self.assertEqual(category_slug, "pitos")
        self.assertEqual(category_name, "Pitos")
        self.assertEqual(subcategory_slug, "de-reversa")
        self.assertEqual(subcategory_name, "De reversa")


if __name__ == "__main__":
    unittest.main()
