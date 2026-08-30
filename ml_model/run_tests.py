"""
Full end-to-end test suite for ml_model/
Runs without pytest – just: python run_tests.py
"""
import sys, traceback, json
sys.path.insert(0, ".")

PASS = []
FAIL = []

def test(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  [PASS] {name}")
    except Exception as e:
        FAIL.append(name)
        print(f"  [FAIL] {name}")
        print(f"         {type(e).__name__}: {e}")
        traceback.print_exc()

# ── Import check ─────────────────────────────────────────────────────────────
def t_imports():
    from serving.inference import calculate_aqi, calculate_wqi, detect_anomalies, forecast
    from shared.data_split import chronological_split, walk_forward_splits
    from shared.features import build_feature_matrix, add_lag_features, add_rolling_features
    from shared.metrics import regression_metrics, classification_metrics, ks_drift_test

# ── AQI ML Prediction ────────────────────────────────────────────────────────
def t_predict_aqi_ml():
    from serving.inference import predict_aqi
    r = predict_aqi({"pm25": 55.0, "no2": 80.0, "pm10": 100.0})
    assert "aqi" in r
    assert "category" in r
    assert "confidence" in r
    assert "class_probabilities" in r
    assert r["model_type"] == "XGBoost (ML)"

# ── WQI ML Prediction ────────────────────────────────────────────────────────
def t_predict_wqi_ml():
    from serving.inference import predict_wqi
    r = predict_wqi({"pH": 7.2, "turbidity": 2.5, "TDS": 320.0, "DO": 6.5})
    assert "wqi" in r
    assert "category" in r
    assert "confidence" in r
    assert "class_probabilities" in r
    assert r["model_type"] == "XGBoost (ML)"

# ── Chronological split no-shuffle ───────────────────────────────────────────
def t_chronological_split():
    import pandas as pd, numpy as np
    from shared.data_split import chronological_split
    dates = pd.date_range("2023-01-01", periods=100, freq="h")
    df = pd.DataFrame({"measured_at": dates, "pm25": np.random.rand(100), "target": np.arange(100)})
    X_tr, X_te, y_tr, y_te = chronological_split(df, "target", "measured_at", test_ratio=0.2)
    # Last train timestamp must be before first test timestamp
    assert y_tr.max() < y_te.min(), "Training data leaks into test set!"
    assert len(X_tr) == 80
    assert len(X_te) == 20

# ── Feature engineering: no PerformanceWarning ───────────────────────────────
def t_feature_engineering():
    import pandas as pd, numpy as np, warnings
    from shared.features import build_feature_matrix
    dates = pd.date_range("2023-01-01", periods=200, freq="h")
    df = pd.DataFrame({"measured_at": dates, "pm25": np.random.rand(200)*100, "no2": np.random.rand(200)*50})
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning = exception
        df_feat = build_feature_matrix(df, pollutant_cols=["pm25", "no2"], timestamp_col="measured_at",
                                        lags=[1, 2, 3], windows=[3, 6])
    assert df_feat.shape[0] == 200
    assert "pm25_lag1" in df_feat.columns
    assert "pm25_roll3_mean" in df_feat.columns
    assert "hour_sin" in df_feat.columns

# ── Anomaly ML inference ──────────────────────────────────────────────────────
def t_detect_anomalies():
    from serving.inference import detect_anomalies
    results = detect_anomalies("station_test", "pm25")
    assert isinstance(results, list)
    for r in results:
        assert r["is_anomaly"] is True
        assert "anomaly_score" in r

# ── Forecast ML inference ─────────────────────────────────────────────────────
def t_forecast_24h():
    from serving.inference import forecast
    preds = forecast("station_test", "pm25", hours=24)
    assert len(preds) == 24
    assert all("predicted" in p for p in preds)
    assert all(p["lower_ci"] <= p["predicted"] <= p["upper_ci"] for p in preds)

def t_forecast_72h():
    from serving.inference import forecast
    preds = forecast("station_test", "pm25", hours=72)
    assert len(preds) == 72

# ── Metrics correctness ────────────────────────────────────────────────────────
def t_regression_metrics():
    import numpy as np
    from shared.metrics import regression_metrics
    y_true = [1, 2, 3, 4, 5]
    y_pred = [1, 2, 3, 4, 5]  # perfect prediction
    m = regression_metrics(y_true, y_pred)
    assert m["mae"] == 0.0
    assert m["rmse"] == 0.0
    assert m["r2"] == 1.0

def t_ks_drift():
    import numpy as np, pandas as pd
    from shared.metrics import ks_drift_test
    rng = np.random.default_rng(0)
    ref = pd.DataFrame({"x": rng.normal(0, 1, 500), "y": rng.normal(5, 2, 500)})
    # same distribution = no drift
    cur_same = pd.DataFrame({"x": rng.normal(0, 1, 200), "y": rng.normal(5, 2, 200)})
    report_no = ks_drift_test(ref, cur_same)
    # heavily shifted = drift
    cur_shift = pd.DataFrame({"x": rng.normal(10, 1, 200), "y": rng.normal(50, 2, 200)})
    report_yes = ks_drift_test(ref, cur_shift)
    assert not report_no["overall_drift_detected"], "Same distribution should not trigger drift"
    assert report_yes["overall_drift_detected"], "Heavily shifted distribution should trigger drift"

# ── Model registry versioning ─────────────────────────────────────────────────
def t_registry_versions():
    from anomaly.model_registry import list_versions, latest_version
    versions = list_versions()
    assert len(versions) >= 1, "At least one anomaly model must be registered"
    latest = latest_version()
    assert latest is not None
    print(f"         Latest anomaly version: {latest}")

# ── FastAPI endpoint imports ───────────────────────────────────────────────────
def t_api_import():
    from serving.api import app
    assert app.title == "Environmental ML Inference API"
    routes = [r.path for r in app.routes]
    for expected in ["/health", "/aqi", "/wqi", "/forecast", "/anomaly"]:
        assert expected in routes, f"Missing route: {expected}"

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  ML MODULE – FULL TEST SUITE")
print("="*65)

test("imports",              t_imports)
test("predict_aqi_ml",       t_predict_aqi_ml)
test("predict_wqi_ml",       t_predict_wqi_ml)
test("chronological_split",  t_chronological_split)
test("feature_engineering",  t_feature_engineering)
test("detect_anomalies",     t_detect_anomalies)
test("forecast_24h",         t_forecast_24h)
test("forecast_72h",         t_forecast_72h)
test("regression_metrics",   t_regression_metrics)
test("ks_drift_test",        t_ks_drift)
test("registry_versions",    t_registry_versions)
test("api_routes",           t_api_import)

print()
print("="*65)
print(f"  RESULTS: {len(PASS)} PASSED  |  {len(FAIL)} FAILED")
print("="*65)
if FAIL:
    print("  FAILED tests:", FAIL)
    sys.exit(1)
else:
    print("  ALL TESTS PASSED")
    sys.exit(0)
