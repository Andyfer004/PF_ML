import unittest

import pandas as pd

from src.predictor import FEATURES, build_tables, direction, forecast, historical_predictions, temporal_partition, train_predictor


def fixture(n=40):
    rows = []
    changes = [0.5, -0.6, 0.0, 0.3, -0.2]
    for fuel, offset in (("super", 0), ("regular", -1), ("diesel", 2)):
        price = 35 + offset
        for i, week in enumerate(pd.date_range("2024-01-02", periods=n, freq="7D")):
            price += changes[i % len(changes)]
            rows.append({"fecha": week.date().isoformat(), "combustible": fuel,
                         "precio_q_galon": round(price, 2), "ubicacion": "estacion"})
    return rows


class PredictorTests(unittest.TestCase):
    def test_historical_demo_uses_reserved_model_and_reproduces_test_metrics(self):
        from unittest.mock import patch
        model,report,tables=train_predictor(fixture(),as_of='2025-01-01')
        with patch.object(model,'predict_proba',side_effect=AssertionError('No usar reajuste de producción')):
            rows=historical_predictions(model,report,tables,'2026-11-24T19:00:00-06:00')
        self.assertEqual(len(rows),report['modelo_test']['n'])
        self.assertAlmostEqual(sum(r['acierto'] for r in rows)/len(rows),report['modelo_test']['accuracy'])
        self.assertAlmostEqual(sum(r['baseline_acierto'] for r in rows)/len(rows),report['baseline_test']['accuracy'])
        for row in rows:
            self.assertLess(row['entrenamiento_hasta'],row['semana_datos'])
            self.assertLess(row['fecha_corte_simulada'],row['semana'])
            self.assertEqual((pd.Timestamp(row['semana'])-pd.Timestamp(row['semana_datos'])).days,7)
            self.assertGreaterEqual(row['probabilidad'],0);self.assertLessEqual(row['probabilidad'],1)

    def test_historical_demo_does_not_use_target_labels_to_predict(self):
        model,report,tables=train_predictor(fixture(),as_of='2025-01-01')
        before=historical_predictions(model,report,tables,'2026-11-24T19:00:00-06:00')
        tables['evaluacion_temporal']=tables['evaluacion_temporal'].assign(objetivo='se_mantiene')
        after=historical_predictions(model,report,tables,'2026-11-24T19:00:00-06:00')
        self.assertEqual([(r['prediccion'],r['probabilidad']) for r in before],[(r['prediccion'],r['probabilidad']) for r in after])
        report['particiones']['validacion']['hasta']='2026-11-24'
        with self.assertRaisesRegex(ValueError,'posteriores'):
            historical_predictions(model,report,tables,'2026-11-24T19:00:00-06:00')

    def test_gap_never_becomes_next_week_target(self):
        rows = [{"fecha": d, "combustible": "super", "precio_q_galon": p}
                for d, p in (("2024-01-02", 30), ("2024-01-09", 31), ("2024-01-30", 40))]
        _, features, _ = build_tables(rows, as_of="2025-01-01")
        jan9 = features[features["semana"] == pd.Timestamp("2024-01-09")].iloc[0]
        self.assertTrue(pd.isna(jan9.objetivo))
        jan30 = features[features["semana"] == pd.Timestamp("2024-01-30")].iloc[0]
        self.assertTrue(pd.isna(jan30.cambio_1w))
        self.assertEqual(jan30.semanas_desde_ultima_observacion, 3)

    def test_future_mutation_does_not_change_earlier_features(self):
        rows = fixture()
        _, first, _ = build_tables(rows, as_of="2025-01-01")
        for row in rows:
            if row["fecha"] > "2024-06-01":
                row["precio_q_galon"] += 100
        _, second, _ = build_tables(rows, as_of="2025-01-01")
        mask = first["semana"] < "2024-06-01"
        pd.testing.assert_frame_equal(first.loc[mask, FEATURES], second.loc[mask, FEATURES])

    def test_split_keeps_all_fuels_of_a_week_together(self):
        _, _, data = build_tables(fixture(), as_of="2025-01-01")
        train, validation, test = temporal_partition(data)
        self.assertLess(train.semana_objetivo.max(), validation.semana_objetivo.min())
        self.assertLess(validation.semana_objetivo.max(), test.semana_objetivo.min())
        self.assertTrue(set(train.semana_objetivo).isdisjoint(test.semana_objetivo))

    def test_threshold_boundaries_and_future_rows(self):
        self.assertEqual(direction(pd.Series([-0.1, 0.1, 0.11])).tolist(), ["se_mantiene", "se_mantiene", "sube"])
        with self.assertRaisesRegex(ValueError, "futuras"):
            build_tables(fixture(), as_of="2024-01-01")

    def test_open_week_can_be_a_feature_but_never_a_training_label(self):
        rows = [row for row in fixture() if row["fecha"] <= "2024-03-06"]
        _, features, data = build_tables(rows, as_of="2024-03-06")
        self.assertTrue((features.semana == pd.Timestamp("2024-03-05")).any())
        self.assertFalse((data.semana_objetivo >= pd.Timestamp("2024-03-05")).any())

    def test_model_probability_and_stale_data(self):
        model, report, tables = train_predictor(fixture(), as_of="2025-01-01")
        self.assertEqual(set(report["por_combustible"]), {"diesel", "regular", "super"})
        result, blocked = forecast(model, tables["features_modelo"], as_of="2025-01-01")
        self.assertEqual(result, [])
        self.assertEqual(len(blocked), 3)
        last_target = tables["features_modelo"].semana_objetivo.max()
        result, _ = forecast(model, tables["features_modelo"], as_of=last_target-pd.Timedelta(days=1))
        self.assertEqual(len(result), 3)
        self.assertTrue(all(0 <= x["probabilidad"] <= 1 for x in result))


if __name__ == "__main__":
    unittest.main()

class HorizonTests(unittest.TestCase):
    def test_two_week_horizon_predicts_target_week_change_not_two_week_change(self):
        # +10 y luego -5: el cambio acumulado es positivo, pero la semana objetivo baja.
        rows=[{'fecha':d,'combustible':'super','precio_q_galon':v} for d,v in [('2024-01-02',30),('2024-01-09',40),('2024-01-16',35)]]
        _,features,_=build_tables(rows,as_of='2024-02-01',horizon_weeks=2)
        first=features[features.semana==pd.Timestamp('2024-01-02')].iloc[0]
        self.assertEqual(first.semana_objetivo,pd.Timestamp('2024-01-16'))
        self.assertEqual(first.objetivo,'baja')
    def test_adaptive_horizon_is_bounded_and_requires_all_three_fuels(self):
        from src.predictor import horizon_for_next_week
        rows=[{'fecha':'2026-11-10','combustible':f} for f in ('super','regular','diesel')]
        self.assertEqual(horizon_for_next_week(rows,'2026-11-20'),2)
        self.assertEqual(horizon_for_next_week(rows,'2026-12-10'),1)
        self.assertEqual(horizon_for_next_week(rows[:1],'2026-11-20'),1)

    def test_current_tuesday_is_not_published_as_next_week(self):
        model,report,tables=train_predictor(fixture(),as_of='2025-01-01')
        target=tables['features_modelo'].semana_objetivo.max()
        result,blocked=forecast(model,tables['features_modelo'],as_of=target)
        self.assertEqual(result,[]);self.assertEqual(len(blocked),3)
    def test_model_and_feature_horizons_must_match(self):
        model,report,tables=train_predictor(fixture(),as_of='2025-01-01',horizon_weeks=2)
        _,features,_=build_tables(fixture(),as_of='2025-01-01',horizon_weeks=1)
        with self.assertRaisesRegex(ValueError,'horizonte'):forecast(model,features,as_of='2025-01-01')
    def test_temporal_partitions_purge_labels_unavailable_at_next_fold_features(self):
        _,_,data=build_tables(fixture(60),as_of='2026-11-20',horizon_weeks=2)
        train,validation,test=temporal_partition(data)
        self.assertLessEqual((train.semana_objetivo+pd.Timedelta(days=7)).max(),validation.semana.min())
        self.assertLessEqual((validation.semana_objetivo+pd.Timedelta(days=7)).max(),test.semana.min())
