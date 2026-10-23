import React, { useState, useEffect } from 'react';
import { AlertTriangle } from 'lucide-react';
import AnalyticsDashboardTemplate from '../components/layout/AnalyticsDashboardTemplate';
import DashboardLoadingSkeleton from '../components/common/DashboardLoadingSkeleton';
import { useDatasetFor } from '../hooks/useDatasetFor';
import {
  fetchAQISummary,
  fetchAQIData,
  fetchAnomalySummary,
  fetchForecasts,
  fetchDatasetDateRange,
  computeAQISummaryCards,
  aqiCategoryFor,
  datasetDisplayLabel,
} from '../lib/api';

const cardsConfig = [
  {
    title: 'Latest AQI',
    titleKey: 'latestTitle',
    dataKey: 'currentAQI',
    statusKey: 'category',
    color: 'orange',
  },
  {
    title: 'PM-only AQI',
    dataKey: 'pmAqi',
    captionKey: 'pmAqiCaption',
    color: 'blue',
  },
  { title: 'Dominant Pollutant', dataKey: 'dominantPollutant', color: 'blue' },
  { title: 'Daily Change', dataKey: 'avgChange', color: 'yellow' },
  {
    title: 'Anomaly Days',
    dataKey: 'anomalies',
    color: 'red',
    captionKey: 'anomalyCaption',
  },
];

const FORECAST_LINE = { dataKey: 'forecast', name: 'AQI forecast (7-day)', color: '#8b5cf6' };
const FORECAST_BAND_LINES = [
  { dataKey: 'forecast_low', name: 'Forecast low (80%)', color: '#ddd6fe', legendType: 'none' },
  { dataKey: 'forecast_high', name: 'Forecast high (80%)', color: '#ddd6fe', legendType: 'none' },
];

const chartConfig = (data) => ({
  dataKey: 'value',
  color: '#f97316',
  yLabel: 'Air Quality Index (AQI)',
  tooltipName: 'AQI',
  timeAxis: true,
  extraLines: data?.hasForecast ? [...FORECAST_BAND_LINES, FORECAST_LINE] : [],
});

const EMPTY_CARDS = {
  currentAQI: '-',
  category: '-',
  dominantPollutant: '-',
  pmAqi: '-',
  avgChange: '-',
  anomalies: 0,
  latestTitle: 'Latest AQI',
  latestDateLabel: '',
  pmAqiCaption: 'needs PM2.5 or PM10 sub-index',
};

const AQI_PARAMS = [
  { key: 'pm25', label: 'PM2.5', unit: 'µg/m³' },
  { key: 'pm10', label: 'PM10', unit: 'µg/m³' },
  { key: 'no2', label: 'NO₂', unit: 'µg/m³' },
  { key: 'so2', label: 'SO₂', unit: 'µg/m³' },
  { key: 'co', label: 'CO', unit: 'µg/m³' },
  { key: 'o3', label: 'O₃', unit: 'µg/m³' },
];

const CATEGORY_CLASSES = {
  Good: 'bg-green-50 text-green-700 border-green-200',
  Satisfactory: 'bg-lime-50 text-lime-700 border-lime-200',
  Moderate: 'bg-yellow-50 text-yellow-700 border-yellow-200',
  Poor: 'bg-orange-50 text-orange-700 border-orange-200',
  'Very Poor': 'bg-red-50 text-red-700 border-red-200',
  Severe: 'bg-rose-100 text-rose-800 border-rose-300',
};

const formatNumber = (value, digits = 1) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString('en-IN', { maximumFractionDigits: digits });
};

const formatIstDate = (timestamp, includeWeekday = false, includeYear = false) => {
  if (!timestamp) return '';
  const raw = String(timestamp);
  const dateOnly = raw.match(/^(\d{4}-\d{2}-\d{2})/)?.[1];
  const isZoned = /(Z|[+-]\d{2}:\d{2})$/.test(raw);
  const date = dateOnly && !isZoned
    ? new Date(`${dateOnly}T12:00:00+05:30`)
    : new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata',
    ...(includeWeekday ? { weekday: 'short' } : {}),
    ...(includeYear ? { year: 'numeric' } : {}),
    day: 'numeric',
    month: 'short',
  });
};

const daysSince = (timestamp) => {
  if (!timestamp) return null;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return null;
  return Math.floor((Date.now() - date.getTime()) / 86400000);
};

const latestAqiRecord = (records) => {
  if (!Array.isArray(records)) return null;
  return [...records]
    .filter(record => record.aqi !== null && record.aqi !== undefined)
    .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
    .at(-1) || null;
};

const buildBreakdown = (record, dateLabel) => {
  if (!record) return null;
  const values = record.pollutant_values || record;
  const subIndices = record.sub_indices || {};
  const rows = AQI_PARAMS
    .filter(param => subIndices[param.key] !== null && subIndices[param.key] !== undefined)
    .map(param => ({
      ...param,
      value: values[param.key] ?? record[param.key],
      qi: Number(subIndices[param.key]),
    }))
    .sort((a, b) => b.qi - a.qi);
  const headline = Number(record.aqi);
  const pmOnly = Math.max(
    subIndices.pm25 ?? Number.NEGATIVE_INFINITY,
    subIndices.pm10 ?? Number.NEGATIVE_INFINITY
  );

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
        <h2 className="text-lg font-bold text-slate-800">AQI breakdown (latest sample)</h2>
        <span className="text-xs text-slate-500">
          {dateLabel} &middot; headline AQI {Math.round(headline)} {record.aqi_category ? `(${record.aqi_category})` : ''}
        </span>
      </div>
      {rows.length > 0 ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500 border-b border-slate-100">
              <th className="py-2 font-medium">Pollutant</th>
              <th className="py-2 font-medium text-right">Concentration</th>
              <th className="py-2 font-medium text-right">Sub-index Q<sub>i</sub></th>
              <th className="py-2 font-medium text-right">Category</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => {
              const category = aqiCategoryFor(row.qi);
              const width = Math.min(100, Math.max(2, row.qi / 500 * 100));
              return (
                <tr key={row.key} className="border-b border-slate-50">
                  <td className="py-2 text-slate-700">
                    {row.label}
                    {row.key === record.dominant_pollutant && (
                      <span className="ml-2 text-[10px] font-medium text-orange-600">dominant</span>
                    )}
                  </td>
                  <td className="py-2 text-right text-slate-700">
                    {formatNumber(row.value)} <span className="text-[10px] text-slate-400">{row.unit}</span>
                  </td>
                  <td className="py-2 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <div className="hidden sm:block w-24 h-1.5 bg-slate-100 rounded overflow-hidden">
                        <div
                          className={`h-1.5 rounded ${row.qi === headline ? 'bg-orange-500' : 'bg-sky-500'}`}
                          style={{ width: `${width}%` }}
                        />
                      </div>
                      <span className="font-medium text-slate-700">{formatNumber(row.qi, 2)}</span>
                    </div>
                  </td>
                  <td className="py-2 text-right">
                    <span className={`inline-flex px-2 py-0.5 rounded border text-[11px] font-medium ${CATEGORY_CLASSES[category] || 'bg-slate-50 text-slate-600 border-slate-200'}`}>
                      {category}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p className="text-sm text-slate-500">No pollutant sub-indices are available for this sample.</p>
      )}
      <p className="text-xs text-slate-500 mt-3">
        The headline CPCB AQI is the highest pollutant sub-index, not an average.
        {Number.isFinite(pmOnly) && ` PM-only AQI (max of PM2.5 / PM10) is ${Math.round(pmOnly)}; the headline also includes gases.`}
      </p>
      <p className="text-xs text-slate-400 mt-1">
        Sub-indices are colour-banded for readability, but only the maximum determines the category shown on the card.
        {record.sub_indices?.o3 !== undefined && ' O₃ uses the source daily maximum 8-hour concentration (o3_8h_max), not an instantaneous reading.'}
      </p>
    </div>
  );
};

const buildForecastPanel = (forecast, skipReason = null, lastObservation = null) => {
  const metrics = forecast?.metrics || {};
  const predictions = forecast?.predictions || [];
  const staleDays = daysSince(lastObservation);
  const lastObservationLabel = formatIstDate(lastObservation, false, true);

  if (predictions.length === 0) {
    return (
      <div className="mt-6 border-t border-slate-100 pt-4">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-bold text-slate-800">Forecast AQI</h2>
          <span className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-500">
            hidden unless validated
          </span>
        </div>
        <p className="mt-2 text-sm text-slate-500">
          {skipReason || 'No forecast is published for this station. A forecast is shown only when the seasonal model beats both persistence and the 7-day mean in rolling-origin testing, using at least two years of daily AQI data.'}
        </p>
      </div>
    );
  }

  const persistenceSkill = metrics.skill_vs_persistence_pct;
  const last7Skill = metrics.skill_vs_last7_mean_pct;
  const horizon = metrics.horizon_mae || [];
  const horizonPersistence = metrics.horizon_persistence_mae || [];
  const horizonLast7 = metrics.horizon_last7_mean_mae || [];

  return (
    <div className="mt-6 border-t border-slate-100 pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-bold text-slate-800">Forecast AQI</h2>
          <span className="rounded border border-violet-200 bg-violet-50 px-2 py-0.5 text-[10px] font-medium text-violet-700">
            modelled · not measured
          </span>
        </div>
        <span className="text-xs text-slate-500">
          Next {predictions.length} days after the last sample
          {lastObservationLabel ? ` (${lastObservationLabel})` : ''} · 80% range and CPCB category chances
        </span>
      </div>

      {staleDays !== null && staleDays > 2 && (
        <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Latest stored sample is {staleDays} days old ({lastObservationLabel}). Treat this as a
          historical forecast, not a current air-quality forecast.
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500 border-b border-slate-100">
              <th className="py-2 font-medium">Day</th>
              <th className="py-2 font-medium text-right">AQI</th>
              <th className="py-2 font-medium text-right">80% range</th>
              <th className="py-2 pl-4 font-medium">Category chances</th>
            </tr>
          </thead>
          <tbody>
            {predictions.map((point, index) => {
              const chances = Object.entries(point.category_probabilities || {})
                .filter(([, chance]) => Number(chance) > 0)
                .sort((a, b) => b[1] - a[1]);
              return (
                <tr key={point.timestamp || index} className="border-b border-slate-50">
                  <td className="py-2 text-slate-700">
                    <span className="font-medium">Day {index + 1}</span>
                    <span className="ml-2 text-xs text-slate-400">{formatIstDate(point.timestamp, true)}</span>
                  </td>
                  <td className="py-2 text-right font-semibold text-slate-800">
                    {Math.round(point.predicted_value)}
                  </td>
                  <td className="py-2 text-right text-slate-600">
                    {Math.round(point.lower_bound)}–{Math.round(point.upper_bound)}
                  </td>
                  <td className="py-2 pl-4">
                    <div className="flex flex-wrap gap-1">
                      {chances.map(([category, chance]) => (
                        <span
                          key={category}
                          className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-medium ${CATEGORY_CLASSES[category] || 'bg-slate-50 text-slate-600 border-slate-200'}`}
                        >
                          {category} {formatNumber(chance, 0)}%
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-slate-500">
        Seasonal trend plus a damped recent-residual term. Rolling-origin skill:
        {' '}{formatNumber(metrics.mae, 1)} MAE vs persistence {formatNumber(metrics.baseline_persistence_mae, 1)}
        {' '}and 7-day mean {formatNumber(metrics.baseline_last7_mean_mae, 1)}
        {persistenceSkill !== null && persistenceSkill !== undefined ? ` (${formatNumber(persistenceSkill, 1)}% / ${formatNumber(last7Skill, 1)}%)` : ''}.
        {' '}80% intervals are calibrated per horizon on the rolling errors
        {metrics.interval_coverage_pct !== null && metrics.interval_coverage_pct !== undefined
          ? ` (measured coverage ${formatNumber(metrics.interval_coverage_pct, 1)}%)`
          : ''}.
      </p>
      {horizon.length > 0 && (
        <p className="mt-1 text-[11px] text-slate-400">
          Day 1→7 MAE, model: {horizon.map(v => formatNumber(v, 1)).join(', ')};
          {' '}persistence: {horizonPersistence.map(v => formatNumber(v, 1)).join(', ')};
          {' '}7-day mean: {horizonLast7.map(v => formatNumber(v, 1)).join(', ')}.
        </p>
      )}
      <p className="mt-1 text-[11px] text-slate-400">
        Forecast of modelled AQI, derived from modelled pollutant concentrations. It is not an observed station AQI.
      </p>
    </div>
  );
};

const ModelledBanner = ({ dataset }) => {
  if (!dataset) return null;
  const o3Share = dataset.dominant_pollutant_share?.o3;
  const isModelled = dataset.data_nature === 'modelled' || (o3Share !== undefined && o3Share >= 0.8);
  if (!isModelled) return null;

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/90 p-4 text-amber-900 animate-fade-in-up">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
        <div>
          <p className="text-sm font-semibold">Modelled / reanalysis air-quality data</p>
          <p className="mt-1 text-xs leading-relaxed text-amber-800">
            This dataset is labelled <strong>modelled</strong>: the displayed AQI is calculated with CPCB
            sub-index breakpoints from modelled pollutant concentrations, not measured at a station.
            {' '}{dataset.data_nature_reason || 'Ozone dominates the pollutant mix, which is typical of modelled data.'}
          </p>
        </div>
      </div>
    </div>
  );
};

const AQIDashboard = () => {
  const {
    datasets,
    selectedId: datasetId,
    setSelectedId,
    selected: datasetMeta,
    loading: datasetsLoading,
  } = useDatasetFor('air_quality');
  const [location, setLocation] = useState(null);
  const [locations, setLocations] = useState([]);
  const [dateBounds, setDateBounds] = useState(null);
  const [summaryLoaded, setSummaryLoaded] = useState(false);

  useEffect(() => {
    if (!datasetId) return;
    setSummaryLoaded(false);
    Promise.all([
      fetchAQISummary(datasetId),
      fetchDatasetDateRange(datasetId).catch(() => null),
    ])
      .then(([summary, bounds]) => {
        if (Array.isArray(summary) && summary.length > 0) {
          const locs = summary.map(r => r.location).filter(Boolean);
          setLocations(locs);
          setLocation(prev => (locs.includes(prev) ? prev : locs[0]));
        }
        setDateBounds(bounds);
      })
      .catch(console.error)
      .finally(() => setSummaryLoaded(true));
  }, [datasetId]);

  const fetchAQIDataForTemplate = async (id, from, to) => {
    if (!id) return { ...EMPTY_CARDS, series: [] };

    const [aqiData, anomalySummary, forecasts] = await Promise.all([
      fetchAQIData(id, location, from, to),
      fetchAnomalySummary(id, from, to, location).catch(() => null),
      fetchForecasts(id, { location, parameter: 'aqi' }).catch(() => []),
    ]);
    if (!Array.isArray(aqiData) || aqiData.length === 0) {
      return { ...EMPTY_CARDS, series: [] };
    }

    const cards = computeAQISummaryCards(aqiData);
    const latest = latestAqiRecord(aqiData);

    const anomalies = anomalySummary?.totals?.anomaly_days ?? 0;
    const anomalyCaption = location
      ? 'unusual pollutant levels vs full station history'
      : 'station-days with unusual pollutant levels vs full history';

    const series = [...aqiData]
      .filter(d => d.timestamp)
      .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
      .map(d => ({
        ts: new Date(d.timestamp).getTime(),
        date: new Date(d.timestamp).toLocaleDateString(),
        value: d.aqi,
      }));

    const forecast = (Array.isArray(forecasts) ? forecasts : [])
      .find(item => item.parameter === 'aqi') || null;
    const skipReason = (datasetMeta?.forecast_skip_reasons || [])
      .find(item => item.location === location && item.parameter === 'aqi')
      ?.reason || null;
    let hasForecast = false;
    if (forecast?.predictions?.length && series.length > 0) {
      const lastPoint = series[series.length - 1];
      const firstPrediction = forecast.predictions[0];
      series.push({
        ...lastPoint,
        forecast: lastPoint.value ?? firstPrediction.predicted_value,
        forecast_low: lastPoint.value ?? firstPrediction.lower_bound,
        forecast_high: lastPoint.value ?? firstPrediction.upper_bound,
      });
      for (const point of forecast.predictions) {
        const timestamp = new Date(point.timestamp).getTime();
        series.push({
          ts: timestamp,
          date: new Date(point.timestamp).toLocaleDateString(),
          forecast: point.predicted_value,
          forecast_low: point.lower_bound,
          forecast_high: point.upper_bound,
        });
      }
      hasForecast = true;
    }

    return {
      ...cards,
      anomalies,
      anomalyCaption,
      series,
      hasForecast,
      breakdown: (
        <>
          {buildBreakdown(latest, cards.latestDateLabel)}
          {buildForecastPanel(forecast, skipReason, latest?.timestamp)}
        </>
      ),
    };
  };

  if (datasetsLoading) {
    return <DashboardLoadingSkeleton cardCount={cardsConfig.length} label="Loading air quality data" />;
  }

  if (!datasetId) {
    return (
      <div className="glass-card p-12 rounded-2xl text-center">
        <p className="text-slate-600">No air quality dataset uploaded yet.</p>
        <p className="text-sm text-slate-500 mt-2">Datasets containing pollutant columns appear here — upload one from the Upload page.</p>
      </div>
    );
  }

  if (!summaryLoaded) {
    return <DashboardLoadingSkeleton cardCount={cardsConfig.length} label="Loading air quality data" />;
  }

  return (
    <AnalyticsDashboardTemplate
      key={datasetId}
      title="Air Quality (AQI) Dashboard"
      banner={<ModelledBanner dataset={datasetMeta} />}
      fetchFn={fetchAQIDataForTemplate}
      cardsConfig={cardsConfig}
      chartConfig={chartConfig}
      datasetId={datasetId}
      location={location}
      locations={locations}
      onLocationChange={setLocation}
      dateBounds={dateBounds}
      summaryNote="AQI categories: Good 0-50, Satisfactory 51-100, Moderate 101-200, Poor 201-300, Very Poor 301-400, Severe 401-500."
      datasetOptions={datasets.map(d => ({ id: d.id, label: datasetDisplayLabel(d) }))}
      onDatasetChange={setSelectedId}
    />
  );
};

export default AQIDashboard;
