import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import AnalyticsDashboardTemplate from '../components/layout/AnalyticsDashboardTemplate';
import DashboardLoadingSkeleton from '../components/common/DashboardLoadingSkeleton';
import { useDatasetFor } from '../hooks/useDatasetFor';
import {
  fetchTemperatureData,
  fetchTemperatureSummary,
  fetchDatasetDateRange,
  fetchAnomalies,
  fetchForecasts,
  computeTempSummaryCards,
  buildSourceLabel,
  datasetDisplayLabel,
} from '../lib/api';

const cardsConfig = [
  { title: 'Current (Latest Day)', dataKey: 'currentTemp', trendKey: 'currentTrend', trendLabel: 'vs previous day', trendTone: 'direction', color: 'orange' },
  { title: 'Minimum (Lowest Daily Min)', dataKey: 'min', trendKey: 'minTrend', trendLabel: 'vs previous day', trendTone: 'direction', color: 'blue' },
  { title: 'Maximum (Highest Daily Max)', dataKey: 'max', trendKey: 'maxTrend', trendLabel: 'vs previous day', trendTone: 'direction', color: 'red' },
  { title: 'Average (Derived Daily Mean)', dataKey: 'avg', trendKey: 'avgTrend', trendLabel: 'vs previous 7 days', trendTone: 'direction', color: 'yellow' },
  { title: 'Temperature Anomalies', dataKey: 'anomalies', color: 'red', caption: '3σ vs seasonal norm · selected range' },
];

const DERIVED_MEAN_NOTE = 'Mean is derived per day as (min + max) / 2 — an approximation, not a measured daily mean.';
const ANOMALY_NOTE = 'Red dots mark days flagged by the residual anomaly detector (robust z > 3 on the seasonal residual); they are unusual days, not necessarily sensor errors.';

const FORECAST_LINE = { dataKey: 'forecast', name: 'Forecast (7-day)', color: '#8b5cf6' };
const FORECAST_BAND_LINES = [
  { dataKey: 'forecast_low', name: 'Forecast low (80%)', color: '#ddd6fe', legendType: 'none' },
  { dataKey: 'forecast_high', name: 'Forecast high (80%)', color: '#ddd6fe', legendType: 'none' },
];
const ANOMALY_LINE = { dataKey: 'anomaly_point', name: 'Temperature anomaly', color: '#dc2626', dotOnly: true, legendType: 'circle' };

const MODEL_LABELS = {
  HarmonicRegression: 'seasonal harmonic regression',
  SimpleExponentialSmoothing: 'exponential smoothing',
};

const isoDateKey = (timestamp) => {
  if (!timestamp) return null;
  const match = String(timestamp).match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : null;
};

const chartConfig = (data) => ({
  dataKey: 'value',
  color: '#ef4444',
  yLabel: 'Temperature (°C)',
  tooltipName: 'Mean (derived)',
  unit: '°C',
  timeAxis: true,
  extraLines: [
    { dataKey: 'min', name: 'Min', color: '#93c5fd' },
    { dataKey: 'max', name: 'Max', color: '#fca5a5' },
    ...(data?.hasAnomalyPoints ? [ANOMALY_LINE] : []),
    ...(data?.hasForecast ? [...FORECAST_BAND_LINES, FORECAST_LINE] : []),
  ],
});

const EMPTY_CARDS = { currentTemp: '-', min: '-', max: '-', avg: '-', anomalies: 0 };

const TemperatureDashboard = () => {
  const navigate = useNavigate();
  const {
    datasets,
    selectedId: datasetId,
    setSelectedId,
    selected: datasetMeta,
    loading: datasetsLoading,
  } = useDatasetFor('temperature');
  const [location, setLocation] = useState(null);
  const [locations, setLocations] = useState([]);
  const [dateBounds, setDateBounds] = useState(null);
  const [summaryLoaded, setSummaryLoaded] = useState(false);

  useEffect(() => {
    if (!datasetId) return;
    setSummaryLoaded(false);
    Promise.all([
      fetchTemperatureSummary(datasetId),
      fetchDatasetDateRange(datasetId).catch(() => null),
    ])
      .then(([summary, bounds]) => {
        if (Array.isArray(summary) && summary.length > 0) {
          const locs = summary.map(r => r.location);
          setLocations(locs);
          setLocation(prev => (locs.includes(prev) ? prev : locs[0]));
        }
        setDateBounds(bounds);
      })
      .catch(console.error)
      .finally(() => setSummaryLoaded(true));
  }, [datasetId]);

  const fetchTempDataForTemplate = async (id, from, to) => {
    if (!id) return { ...EMPTY_CARDS, series: [] };

    const [tempData, anomalies, forecasts] = await Promise.all([
      fetchTemperatureData(id, location, from, to),
      fetchAnomalies(id, {
        location,
        parameter: 'temperature',
        onlyAnomalies: true,
        startDate: from,
        endDate: to,
      }).catch(() => []),
      fetchForecasts(id, { location, parameter: 'temperature' }).catch(() => []),
    ]);

    const flaggedAnomalies = (Array.isArray(anomalies) ? anomalies : []).filter(a => a.is_anomaly);
    const anomalyDates = new Set(flaggedAnomalies.map(a => isoDateKey(a.timestamp)).filter(Boolean));

    if (!Array.isArray(tempData) || tempData.length === 0) {
      return { ...EMPTY_CARDS, anomalies: flaggedAnomalies.length, series: [] };
    }

    const cards = computeTempSummaryCards(tempData);
    const series = [...tempData]
      .reverse()
      .map(d => {
        const date = d.timestamp ? new Date(d.timestamp).toLocaleDateString() : '';
        const dateKey = isoDateKey(d.timestamp);
        return {
          ts: d.timestamp ? new Date(d.timestamp).getTime() : null,
          date,
          value: d.temperature,
          min: d.temp_min,
          max: d.temp_max,
          anomaly_point: dateKey && anomalyDates.has(dateKey) ? d.temperature : null,
        };
      })
      .filter(d => d.value !== null && d.value !== undefined && !Number.isNaN(d.value));

    const hasAnomalyPoints = series.some(d => d.anomaly_point !== null && d.anomaly_point !== undefined);

    const forecast = Array.isArray(forecasts) && forecasts.length > 0 ? forecasts[0] : null;
    const sourceShort = buildSourceLabel(datasetMeta, dateBounds);
    let forecastNote = null;
    let forecastSummary = null;
    const methodDetails = [];
    if (forecast?.predictions?.length && series.length > 0) {
      const lastPoint = series[series.length - 1];
      series.push({
        ...lastPoint,
        forecast: lastPoint.value,
        forecast_low: lastPoint.value,
        forecast_high: lastPoint.value,
      });
      for (const point of forecast.predictions) {
        series.push({
          ts: point.timestamp ? new Date(point.timestamp).getTime() : null,
          date: point.timestamp ? new Date(point.timestamp).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '',
          forecast: point.predicted_value,
          forecast_low: point.lower_bound,
          forecast_high: point.upper_bound,
        });
      }
      const label = forecast.metrics?.model_note || MODEL_LABELS[forecast.model_used] || forecast.model_used;
      const metrics = forecast.metrics || {};
      forecastSummary = metrics.mae !== null && metrics.mae !== undefined
        ? `7-day forecast, MAE ${metrics.mae}°C`
        : '7-day forecast';
      methodDetails.push(`Model: ${label}.`);
      if (metrics.mae !== null && metrics.mae !== undefined && metrics.baseline_persistence_mae !== null && metrics.baseline_persistence_mae !== undefined) {
        methodDetails.push(
          `Evaluated by rolling origin (${metrics.rolling_origins} origins × 7-day horizon): MAE ${metrics.mae}°C vs persistence ${metrics.baseline_persistence_mae}°C and last-7-mean ${metrics.baseline_last7_mean_mae}°C.`
        );
      }
      const horizon = metrics.horizon_mae;
      const horizonBaseline = metrics.horizon_persistence_mae;
      if (Array.isArray(horizon) && Array.isArray(horizonBaseline) && horizon.length > 0) {
        let lastLoss = -1;
        horizon.forEach((value, index) => {
          if (horizonBaseline[index] !== undefined && value >= horizonBaseline[index]) lastLoss = index;
        });
        const winsFrom = lastLoss === -1 ? 1 : (lastLoss < horizon.length - 1 ? lastLoss + 2 : null);
        const horizonText = `MAE by horizon, day 1→7 (model): ${horizon.map(v => v.toFixed(2)).join(', ')}°C; persistence: ${horizonBaseline.map(v => v.toFixed(2)).join(', ')}°C.`;
        methodDetails.push(
          `${horizonText}${winsFrom ? ` Model wins from day ${winsFrom} onward.` : ' Persistence wins at every horizon.'}`
        );
      }
      if (metrics.interval_coverage_pct !== null && metrics.interval_coverage_pct !== undefined) {
        methodDetails.push(
          `80% prediction intervals are calibrated per horizon on the rolling-origin errors (measured coverage ${metrics.interval_coverage_pct}%, so uncertainty widens with lead time).`
        );
      }
      forecastNote = 'Dashed line; prediction interval on hover.';
    }

    return {
      ...cards,
      anomalies: flaggedAnomalies.length,
      series,
      hasForecast: Boolean(forecastNote),
      hasAnomalyPoints,
      summaryNote: [sourceShort, forecastSummary].filter(Boolean).join(' · '),
      chartNote: [
        ...methodDetails,
        hasAnomalyPoints ? ANOMALY_NOTE : null,
        DERIVED_MEAN_NOTE,
      ].filter(Boolean).join(' '),
    };
  };

  if (datasetsLoading) {
    return <DashboardLoadingSkeleton cardCount={cardsConfig.length} label="Loading temperature data" />;
  }

  if (!datasetId) {
    return (
      <div className="glass-card p-12 rounded-2xl text-center">
        <p className="text-slate-600">No temperature dataset uploaded yet.</p>
        <p className="text-sm text-slate-500 mt-2">Datasets containing temperature columns appear here — upload one from the Upload page.</p>
      </div>
    );
  }

  if (!summaryLoaded) {
    return <DashboardLoadingSkeleton cardCount={cardsConfig.length} label="Loading temperature data" />;
  }

  const cardConfig = cardsConfig.map(card =>
    card.dataKey === 'anomalies' && datasetId
      ? { ...card, onClick: () => navigate(`/anomalies?dataset_id=${datasetId}&parameter=temperature`) }
      : card
  );

  return (
    <AnalyticsDashboardTemplate
      key={datasetId}
      title="Temperature Dashboard"
      fetchFn={fetchTempDataForTemplate}
      cardsConfig={cardConfig}
      chartConfig={chartConfig}
      datasetId={datasetId}
      location={location}
      locations={locations}
      onLocationChange={setLocation}
      dateBounds={dateBounds}
      datasetOptions={datasets.map(d => ({ id: d.id, label: datasetDisplayLabel(d) }))}
      onDatasetChange={setSelectedId}
    />
  );
};

export default TemperatureDashboard;
