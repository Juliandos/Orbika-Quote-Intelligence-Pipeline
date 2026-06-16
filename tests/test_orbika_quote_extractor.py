import unittest

from tools.orbika_quote_extractor import (
    has_access_denied_marketplace_modal,
    is_interstitial_page,
    is_signed_out_shell,
    parse_args,
    parse_orbika_quote_html,
    quote_read_flag_active,
    quote_page_empty,
    quote_page_loaded,
    quote_page_ready,
)


HTML_FIXTURE = """
<manual-purchase>
  <div class="div-info-aviso">
    <span class="aviso">Aviso # <span class="num-aviso">428482</span></span>
    <span class="fecha">Fecha del aviso: <span class="fecha-aviso">05/06/26</span></span>
  </div>
  <div class="div-contentAviso">
    <span class="titulo-dato subtitulo">Marca:</span><span class="valor-dato p-t16">KIA</span>
    <span class="titulo-dato subtitulo">Línea:</span><span class="valor-dato p-t16">sportage [3] [fl]</span>
    <span class="titulo-dato subtitulo">Versión:</span><span class="valor-dato p-t16">revolution tp 2000cc 1ab abs</span>
    <span class="titulo-dato subtitulo">Año:</span><span class="valor-dato p-t16">2016</span>
    <span class="titulo-dato subtitulo">Placa:</span><span class="valor-dato p-t16">HHW977</span>
    <span class="titulo-dato subtitulo">VIN:</span><span class="valor-dato ajust-pading p-t16">KNAPB81ABF7721560</span>
  </div>
  <div class="div-down">
    <span class="titulo-taller subtitulo"> Taller de entrega: </span>
    <span class="nombre-taller">Team Car Movi </span>
    <span class="titulo-dato subtitulo">Nombre comercial:</span><span class="valor-dato p-t16">Team Car Movi</span>
    <span class="titulo-dato subtitulo">Nit:</span><span class="valor-dato p-t16">901293598-7</span>
    <span class="titulo-dato subtitulo">Ciudad:</span><span class="valor-dato p-t16">MEDELLIN</span>
    <span class="titulo-dato_sec subtitulo">Dirección:</span><span class="valor-dato">Carrera 43F # 17-605, centro automotriz medellin</span>
    <span class="titulo-dato_sec subtitulo">Teléfono:</span><span class="valor-dato">1111111</span>
    <span class="titulo-dato_sec subtitulo">E-mail:</span><span class="valor-dato">No disponible</span>
  </div>
</manual-purchase>
<quote-replacement>
  <label class="tr-hd-lb mb-0">Capo</label>
  <span class="tr-tituloInput">Referencia</span></div><div class="tr-cl-div2 relative"><button>664003W001</button>
  <span class="sbc-success-text">Código de referencia validado con éxito.</span>
  <span class="tr-tituloInput">Cant.</span></div><div class="tr-cl-div2 "><span class="txtCantidad ">1</span>
  <span class="tr-tituloInput">Precio bruto unidad</span></div><div class="tr-cl-div2"><input value="">
  <span class="tr-tituloInput">Tiempo de entrega</span></div><div class="tr-cl-div2 relative"><input value=""><div class="div-symbolDias"><span>Días</span></div>
  <span class="tr-tituloInput">Descuento</span></div><div class="tr-cl-div2 relative"><input value="2"><div class="div-symbolPorcent"><span>%</span></div>
  <span class="tr-tituloInput">Calidad</span></div><div class="tr-cl-div2"><button><span class="calidadSeleccionada">GENUINO</span></button>
  <span class="tr-tituloInput">Valor total</span></div><div class="tr-cl-div2 "><span class="subtitulo txtCantidad">$0.00</span>
  <span class="txt-obervacion"> Agregar observación </span>
  <button class="btn-rechazar btn_2" type="button" id="btn-rechazar-0"><span>Rechazar</span></button>
</quote-replacement>
<quote-replacement>
  <label class="tr-hd-lb mb-0">Rodamiento delantero derecho</label>
  <span class="tr-tituloInput">Referencia</span></div><div class="tr-cl-div2 relative"><input value="">
  <span class="tr-tituloInput">Cant.</span></div><div class="tr-cl-div2 "><span class="txtCantidad ">1</span>
</quote-replacement>
<div id="footer-quote">
  <span class="sb-text-cadetblue mr-3">Repuestos cotizados</span><span class="sbc-text-dsteelblue mx-3">0</span>
  <span class="sb-text-cadetblue mx-3">Total cotización</span><span class="sbc-text-dsteelblue mx-3">$0.00</span>
</div>
"""


class OrbikaQuoteExtractorTests(unittest.TestCase):
    class FakeLocator:
        def __init__(self, count: int) -> None:
            self._count = count

        def count(self) -> int:
            return self._count

    class FakePage:
        def __init__(self, url: str, selector_counts: dict[str, int] | None = None) -> None:
            self.url = url
            self._selector_counts = selector_counts or {}

        def locator(self, selector: str) -> "OrbikaQuoteExtractorTests.FakeLocator":
            return OrbikaQuoteExtractorTests.FakeLocator(self._selector_counts.get(selector, 0))

    def test_detects_ready_quote_page(self) -> None:
        self.assertTrue(quote_page_ready(HTML_FIXTURE))

    def test_parses_notice_vehicle_workshop_and_parts(self) -> None:
        result = parse_orbika_quote_html(
            html=HTML_FIXTURE,
            quote_url="https://orbika.example.invalid/quote/1",
            retries_used=1,
        )

        self.assertEqual(result.load_status, "loaded")
        self.assertEqual(result.aviso_id, "428482")
        self.assertEqual(result.fecha_aviso, "05/06/26")
        self.assertEqual(result.marca, "KIA")
        self.assertEqual(result.linea, "sportage [3] [fl]")
        self.assertEqual(result.version, "revolution tp 2000cc 1ab abs")
        self.assertEqual(result.ano, "2016")
        self.assertEqual(result.placa, "HHW977")
        self.assertEqual(result.vin, "KNAPB81ABF7721560")
        self.assertEqual(result.taller_entrega, "Team Car Movi")
        self.assertEqual(result.nombre_comercial, "Team Car Movi")
        self.assertEqual(result.nit, "901293598-7")
        self.assertEqual(result.ciudad, "MEDELLIN")
        self.assertEqual(result.telefono, "1111111")
        self.assertEqual(result.email, "No disponible")
        self.assertEqual(result.repuestos_count, 2)
        self.assertEqual(result.repuestos_cotizados, "0")
        self.assertEqual(result.total_cotizacion, "$0.00")
        self.assertEqual(result.parts[0].name, "Capo")
        self.assertEqual(result.parts[0].reference, "664003W001")
        self.assertIsNone(result.parts[0].reference_input_value)
        self.assertEqual(result.parts[0].reference_button_text, "664003W001")
        self.assertEqual(result.parts[0].reference_source, "button_text")
        self.assertEqual(result.parts[0].reference_validation_text, "Código de referencia validado con éxito.")
        self.assertTrue(result.parts[0].reference_validation_visible)
        self.assertEqual(
            result.parts[0].visible_dom_values["reference_validation"],
            "Código de referencia validado con éxito.",
        )
        self.assertTrue(result.parts[0].rejected_button_present)
        self.assertEqual(result.parts[1].raw_status, "partial_missing_reference_quantity")

    def test_marks_partial_when_key_blocks_are_missing(self) -> None:
        result = parse_orbika_quote_html(
            html="<html><body><manual-purchase></manual-purchase></body></html>",
            quote_url="https://orbika.example.invalid/quote/2",
            retries_used=2,
        )

        self.assertEqual(result.load_status, "partial")
        self.assertTrue(any("Notice ID" in warning for warning in result.warnings))
        self.assertTrue(any("quote-replacement" in warning for warning in result.warnings))

    def test_treats_quote_shell_with_footer_but_without_parts_as_ready(self) -> None:
        html = """
        <manual-purchase>
          <div class="div-info-aviso">
            <span class="aviso">Aviso # <span class="num-aviso">57310</span></span>
            <span class="fecha">Fecha del aviso: <span class="fecha-aviso">07/06/26</span></span>
          </div>
          <div class="div-contentAviso">
            <span class="titulo-dato subtitulo">Marca:</span><span class="valor-dato p-t16">FORD</span>
            <span class="titulo-dato subtitulo">Línea:</span><span class="valor-dato p-t16">EDGE [2]</span>
          </div>
          <div class="div-down">
            <span class="titulo-taller subtitulo"> Taller de entrega: </span>
            <span class="nombre-taller">El Roble Motor - Med</span>
          </div>
        </manual-purchase>
        <div id="footer-quote">
          <span class="sb-text-cadetblue mr-3">Repuestos cotizados</span><span class="sbc-text-dsteelblue mx-3">0</span>
          <span class="sb-text-cadetblue mx-3">Total cotización</span><span class="sbc-text-dsteelblue mx-3">$0.00</span>
        </div>
        """

        result = parse_orbika_quote_html(
            html=html,
            quote_url="https://orbika.example.invalid/quote/4",
            retries_used=0,
        )

        self.assertTrue(quote_page_loaded(html))
        self.assertTrue(quote_page_ready(html))
        self.assertFalse(quote_page_empty(html))
        self.assertEqual(result.load_status, "loaded")
        self.assertEqual(result.aviso_id, "57310")
        self.assertEqual(result.repuestos_count, 0)

    def test_detects_visibly_empty_quote_shell(self) -> None:
        html = """
        <manual-purchase>
          <div class="div-info-aviso">
            <span class="aviso">Aviso # <span class="num-aviso"></span></span>
            <span class="fecha">Fecha del aviso: <span class="fecha-aviso"></span></span>
          </div>
          <div class="div-contentAviso">
            <span class="titulo-dato subtitulo">Marca:</span>
            <span class="titulo-dato subtitulo">Línea:</span>
            <span class="titulo-dato subtitulo">Versión:</span>
            <span class="titulo-dato subtitulo">Año:</span>
            <span class="titulo-dato subtitulo">Placa:</span>
            <span class="titulo-dato subtitulo">VIN:</span>
          </div>
          <div class="div-down">
            <span class="titulo-dato subtitulo">Nombre comercial:</span>
            <span class="titulo-dato subtitulo">Ciudad:</span>
            <span class="titulo-dato_sec subtitulo">Teléfono:</span>
          </div>
        </manual-purchase>
        <div id="footer-quote">
          <span class="sb-text-cadetblue mx-3">Total cotización</span><span class="sbc-text-dsteelblue mx-3">$0.00</span>
        </div>
        """

        self.assertTrue(quote_page_loaded(html))
        self.assertTrue(quote_page_empty(html))

    def test_detects_marketplace_and_role_pages_as_interstitial(self) -> None:
        marketplace = self.FakePage("https://orbika.subocol.com/web/guest/marketplace")
        role_page = self.FakePage("https://orbika.subocol.com/web/guest/roles")

        self.assertTrue(is_interstitial_page(marketplace, "<html><body>Welcome</body></html>"))
        self.assertTrue(
            is_interstitial_page(
                role_page,
                "<html><body><h1>Seleccionar organización y rol</h1></body></html>",
            )
        )

    def test_quote_read_flag_requires_real_quote_not_marketplace(self) -> None:
        marketplace = self.FakePage("https://orbika.subocol.com/web/guest/marketplace")
        quote_page = self.FakePage("https://orbika.subocol.com/web/guest/external/quote?token=abc")

        self.assertFalse(
            quote_read_flag_active(
                marketplace,
                "<html><body><manual-purchase></manual-purchase></body></html>",
            )
        )
        self.assertTrue(quote_read_flag_active(quote_page, HTML_FIXTURE))

    def test_marketplace_access_denied_popup_is_interstitial_not_login(self) -> None:
        html = """
        <html>
          <body class="signed-out public-page">
            <a id="sign-in" class="ingresar">Acceder</a>
            <div class="modal-content">
              <h2>¡Actualmente no tienes permisos de acceso!</h2>
              <p>Contacta al administrador para solicitar el ingreso</p>
            </div>
          </body>
        </html>
        """
        marketplace = self.FakePage(
            "https://orbika.subocol.com/web/guest/marketplace",
            {
                "#sign-in": 1,
                "a.ingresar": 1,
                "a:has-text('Acceder')": 1,
            },
        )

        self.assertTrue(has_access_denied_marketplace_modal(html))
        self.assertTrue(is_interstitial_page(marketplace, html))
        self.assertFalse(is_signed_out_shell(marketplace, html))
        self.assertTrue(
            is_signed_out_shell(
                marketplace,
                html,
                allow_access_denied_modal=True,
            )
        )

    def test_parses_dynamic_input_attrs_and_hidden_validation_visibility(self) -> None:
        html = """
        <manual-purchase>
          <span class="num-aviso">500001</span>
        </manual-purchase>
        <quote-replacement>
          <label class="tr-hd-lb">Guardafango</label>
          <span class="tr-tituloInput">Referencia</span></div>
          <div><input value='REF-123' id='referencia-0'></div>
          <span class='sbc-success-text' style='display: none'>Código validado</span>
          <span class="tr-tituloInput">Cant.</span></div><div><span class="txtCantidad">2</span></div>
          <span class="tr-tituloInput">Precio bruto unidad</span></div>
          <div><input value="$10.000" id="precioBruto-0"></div>
          <span class="tr-tituloInput">Tiempo de entrega</span></div>
          <div><input value="3" id="dias-0"></div>
          <span class="tr-tituloInput">Descuento</span></div>
          <div><input value="5" id="descuentoAdi-0"></div>
          <span class="tr-tituloInput">Calidad</span></div>
          <div><button><span class="calidadSeleccionada">ORIGINAL</span></button></div>
          <span class="tr-tituloInput">Valor total</span></div>
          <div><span class="subtitulo txtCantidad">$19.000</span></div>
        </quote-replacement>
        """

        result = parse_orbika_quote_html(
            html=html,
            quote_url="https://orbika.example.invalid/quote/3",
            retries_used=0,
        )

        part = result.parts[0]
        self.assertEqual(part.reference, "REF-123")
        self.assertEqual(part.reference_input_value, "REF-123")
        self.assertEqual(part.reference_source, "input_value")
        self.assertEqual(part.quantity, 2)
        self.assertEqual(part.unit_gross_price, "$10.000")
        self.assertEqual(part.delivery_days, "3")
        self.assertEqual(part.discount, "5")
        self.assertEqual(part.quality, "ORIGINAL")
        self.assertEqual(part.total_value, "$19.000")
        self.assertEqual(part.reference_validation_text, "Código validado")
        self.assertFalse(part.reference_validation_visible)
        self.assertEqual(part.visible_dom_values["reference_input_value"], "REF-123")
        self.assertEqual(part.visible_dom_values["reference_validation_visible"], "false")

    def test_parse_args_disables_login_fallback_by_default(self) -> None:
        args = parse_args(["--quote-url", "https://orbika.example.invalid/quote/1"])
        self.assertFalse(args.allow_login_fallback)

    def test_parse_args_enables_login_fallback_explicitly(self) -> None:
        args = parse_args(
            [
                "--quote-url",
                "https://orbika.example.invalid/quote/1",
                "--allow-login-fallback",
            ]
        )
        self.assertTrue(args.allow_login_fallback)


if __name__ == "__main__":
    unittest.main()
