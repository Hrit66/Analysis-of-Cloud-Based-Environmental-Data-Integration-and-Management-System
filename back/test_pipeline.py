import asyncio
import pandas as pd
from app.services.pipeline_interface import parse_file, clean_dataframe, dataframe_to_records
from app.services.aqi_calculator import compute_aqi_for_record
from app.services.anomaly_detector import detect_anomalies, get_anomaly_summary
from app.services.forecaster import generate_multi_location_forecast


def test_pipeline():
    print("Testing parse_file...")
    df = parse_file("sample_air_quality.csv", "air_quality")
    print(f"Raw shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    print(df.head())
    print()
    
    print("Testing clean_dataframe...")
    cleaned_df, report = clean_dataframe(df, "air_quality")
    print(f"Cleaned shape: {cleaned_df.shape}")
    print(f"Columns: {list(cleaned_df.columns)}")
    print(f"Report: {report}")
    print(cleaned_df.head())
    print()
    
    print("Testing dataframe_to_records...")
    records = dataframe_to_records(cleaned_df, "test-dataset-id", "air_quality")
    print(f"Records count: {len(records)}")
    print(f"First record keys: {list(records[0].keys()) if records else 'none'}")
    print(f"First record timestamp type: {type(records[0]['timestamp']) if records else 'none'}")
    print()
    
    print("Testing AQI computation...")
    for record in records[:3]:
        aqi_result = compute_aqi_for_record(record)
        print(f"Location: {record['location']}, AQI: {aqi_result['aqi']}, Category: {aqi_result['aqi_category']}, Dominant: {aqi_result['dominant_pollutant']}")
    print()
    
    print("Testing anomaly detection...")
    anomalies = detect_anomalies(cleaned_df)
    print(f"Anomaly results: {len(anomalies)}")
    summary = get_anomaly_summary(anomalies)
    print(f"Summary: {summary}")
    print()
    
    print("Testing forecasting...")
    forecasts = generate_multi_location_forecast(cleaned_df, horizon=3)
    for f in forecasts:
        if 'error' not in f:
            print(f"Location: {f['location']}, Parameter: {f['parameter']}, Horizon: {f['forecast_horizon']}, Predictions: {len(f['predictions'])}")
            print(f"  Metrics: {f['metrics']}")
        else:
            print(f"Error for {f['location']}_{f['parameter']}: {f['error']}")


if __name__ == "__main__":
    test_pipeline()