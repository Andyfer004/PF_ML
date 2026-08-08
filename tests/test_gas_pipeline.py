import unittest
from datetime import date

from src.external_data import construir_contexto_externo
from src.gas_pipeline import calcular_estimados, comparar


class PriceValidationTests(unittest.TestCase):
    def test_estimados_desde_super(self) -> None:
        regular, super_price, vpower = calcular_estimados(150.0, 3.938)
        self.assertEqual((regular, super_price, vpower), (37.09, 38.09, 38.59))

    def test_diferencia_por_redondeo_enciende_flag(self) -> None:
        difference, flag = comparar(41.08, 41.09)
        self.assertEqual(difference, -0.01)
        self.assertEqual(flag, 1)

    def test_precio_fuera_de_tolerancia_apaga_flag(self) -> None:
        difference, flag = comparar(41.00, 41.09)
        self.assertEqual(difference, -0.09)
        self.assertEqual(flag, 0)

    def test_valor_faltante_apaga_flag(self) -> None:
        self.assertEqual(comparar(None, 41.09), (None, 0))


class ExternalContextTests(unittest.TestCase):
    def test_contexto_solo_usa_datos_anteriores(self) -> None:
        market = [
            {"fecha": date(2026, 7, 1), "brent_usd_barril": 70.0, "wti_usd_barril": 66.0},
            {"fecha": date(2026, 7, 8), "brent_usd_barril": 77.0, "wti_usd_barril": 72.0},
            {"fecha": date(2026, 7, 10), "brent_usd_barril": 90.0, "wti_usd_barril": 85.0},
        ]
        events = [
            {
                "fecha_inicio": date(2026, 7, 5),
                "fecha_fin": date(2026, 7, 5),
                "tipo_evento": "OPEP",
                "descripcion": "Ajuste de produccion",
                "impacto_esperado": "BAJA",
                "importancia": 3,
                "fuente_url": "https://example.test/opec",
            },
            {
                "fecha_inicio": date(2026, 7, 10),
                "fecha_fin": date(2026, 7, 10),
                "tipo_evento": "CONFLICTO",
                "descripcion": "Evento futuro",
                "impacto_esperado": "SUBE",
                "importancia": 3,
                "fuente_url": "https://example.test/future",
            },
        ]

        context = construir_contexto_externo(date(2026, 7, 9), market, events, "CACHE")

        self.assertEqual(context.fecha_mercado, "2026-07-08")
        self.assertEqual(context.brent_usd_barril, 77.0)
        self.assertEqual(context.variacion_brent_7d_pct, 10.0)
        self.assertEqual(context.eventos_relevantes_cantidad, 1)
        self.assertEqual(context.tipos_evento, "OPEP")
        self.assertNotIn("Evento futuro", context.eventos_resumen)


if __name__ == "__main__":
    unittest.main()
