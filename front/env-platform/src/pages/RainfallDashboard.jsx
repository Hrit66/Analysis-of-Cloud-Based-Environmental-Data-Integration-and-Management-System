import React, { useState, useEffect } from 'react';
import AnalyticsDashboardTemplate from '../components/layout/AnalyticsDashboardTemplate';
import DashboardLoadingSkeleton from '../components/common/DashboardLoadingSkeleton';
import RainOutlookPanel from '../components/rain/RainOutlookPanel';
import { useDatasetFor } from '../hooks/useDatasetFor';
import { fetchRainfallData, fetchRainfallSummary, fetchRainfallOutlook, fetchDatasetDateRange, fetchForecasts, computeRainfallSummaryCards, buildSourceLabel, datasetDisplayLabel, datasetHistoryYears, rainChanceUncertaintyPct, MIN_RAIN_CLIMATOLOGY_YEARS } from '../lib/api';

const cardsConfig = [
  { title: 'Latest Rainfall', dataKey: 'latest', color: 'blue' },
  { title: 'Total Rainfall', dataKey: 'total', color: 'blue' },
  { title: 'Wettest Day', dataKey: 'wettest', color: 'yellow' },
  { title: 'Rainy Days', dataKey: 'rainyDays', caption: 'days ≥ 1 mm', color: 'slate' },
  { title: 'Rain Chance (next 7 days)', dataKey: 'rainChance', captionKey: 'rainChanceCaption', color: 'blue' },
];

const chartConfig = {
  variant: 'bar',
  dataKey: 'value',
  color: '#3b82f6',
  yLabel: 'Rainfall (mm)',
  tooltipName: 'Rainfall',
  unit: ' mm',
  timeAxis: true,
};

const EMPTY_CARDS = { latest: '-', total: '-', wettest: '-', rainyDays: '-', rainChance: '-', rainChanceCaption: null };

const RainfallDashboard = () => {
  const {
    datasets,
    selectedId: datasetId,
    setSelectedId,
    selected: datasetMeta,
    loading: datasetsLoading,
  } = useDatasetFor('rainfall');
  const [location, setLocation] = useState(null);
  const [locations, setLocations] = useState([]);
  const [dateBounds, setDateBounds] = useState(null);
  const [summaryLoaded, setSummaryLoaded] = useState(false);

  useEffect(() => {
    if (!datasetId) return;
    setSummaryLoaded(false);
    Promise.all([
      fetchRainfallSummary(datasetId),
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

  const fetchRainfallDataForTemplate = async (id, from, to) => {
    if (!id) return { ...EMPTY_CARDS, series: [] };

    const [rainData, forecasts, outlook] = await Promise.all([
      fetchRainfallData(id, location, from, to),
      fetchForecasts(id, { location, parameter: 'precipitation' }).catch(() => []),
      fetchRainfallOutlook(id, location).catch(() => null),
    ]);

    const sourceShort = buildSourceLabel(datasetMeta, dateBounds);
    const forecast = Array.isArray(forecasts) && forecasts.length > 0 ? forecasts[0] : null;
    const metrics = forecast?.metrics || {};
    const minYears = outlook?.min_years ?? metrics.rain_climatology_min_years ?? MIN_RAIN_CLIMATOLOGY_YEARS;
    const climatologyYears = outlook?.years_observed ?? metrics.rain_climatology_years ?? datasetHistoryYears(dateBounds);
    const threshold = outlook?.threshold_mm ?? metrics.rain_climatology_threshold_mm ?? 1;
    const yearsLabel = (years) => (Number.isInteger(years) ? `${years}` : years.toFixed(1));

    let rainChance = '-';
    let rainChanceCaption = climatologyYears !== null && climatologyYears < minYears
      ? `needs ≥ ${minYears} years of history (this dataset has ${yearsLabel(climatologyYears)})`
      : 'no forecast available';
    let summaryNote = sourceShort;
    let aboutNote = null;

    if (forecast?.predictions?.length) {
      summaryNote = `${sourceShort} · next-7-day rain outlook`;
      aboutNote = metrics.limitation || null;
      if (metrics.week_rain_probability_pct !== null && metrics.week_rain_probability_pct !== undefined) {
        rainChance = `${metrics.week_rain_probability_pct}%`;
        rainChanceCaption = `≥ ${threshold} mm on any day · ${metrics.rain_climatology_wet_years} of ${metrics.rain_climatology_years} years`;
        const uncertainty = rainChanceUncertaintyPct(metrics.rain_climatology_years, metrics.rain_climatology_wet_years);
        const climatologyNote = `Rain chance is the observed frequency over ${metrics.rain_climatology_years} years (${metrics.rain_climatology_wet_years} of them had a ≥ ${threshold} mm day in this calendar week); it captures the clustering of wet spells that a daily probability misses.${uncertainty ? ` As a climatological estimate it is uncertain by about ±${uncertainty} percentage points (95% confidence).` : ''}`;
        aboutNote = [aboutNote, climatologyNote].filter(Boolean).join(' ');
      } else {
        const probabilities = forecast.predictions
          .map(p => p.rain_probability)
          .filter(v => v !== null && v !== undefined);
        if (probabilities.length > 0) {
          const average = probabilities.reduce((sum, value) => sum + value, 0) / probabilities.length;
          rainChance = `${Math.round(average * 100)}%`;
          rainChanceCaption = `daily chance · ≥ ${threshold} mm`;
        }
      }
    }

    if (outlook) {
      const outlookWeek = outlook.week_probability_pct ?? outlook.week_probability_estimate_pct;
      if (outlookWeek !== null && outlookWeek !== undefined) {
        rainChance = `${outlookWeek}%`;
        const estimateOnly = outlook.week_probability_pct === null;
        rainChanceCaption = estimateOnly
          ? `${yearsLabel(climatologyYears)}-yr estimate · ≥ ${threshold} mm any day`
          : `≥ ${threshold} mm any day · ${outlook.wet_years} of ${outlook.years_observed} years`;
      }
      summaryNote = `${sourceShort} · probability-only rain outlook`;
      aboutNote = outlook.note || aboutNote;
    }

    if (!Array.isArray(rainData) || rainData.length === 0) {
      return { ...EMPTY_CARDS, rainChance, rainChanceCaption, rainOutlook: outlook, series: [], summaryNote, chartNote: aboutNote };
    }

    const cards = computeRainfallSummaryCards(rainData);
    const series = [...rainData]
      .reverse()
      .map(d => ({
        ts: d.timestamp ? new Date(d.timestamp).getTime() : null,
        date: d.timestamp ? new Date(d.timestamp).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '',
        value: d.precipitation,
      }))
      .filter(d => d.value !== null && d.value !== undefined && !Number.isNaN(d.value));

    return {
      ...cards,
      rainChance,
      rainChanceCaption,
      rainOutlook: outlook,
      series,
      summaryNote,
      chartNote: aboutNote,
    };
  };

  if (datasetsLoading) {
    return <DashboardLoadingSkeleton cardCount={cardsConfig.length} label="Loading rainfall data" />;
  }

  if (!datasetId) {
    return (
      <div className="glass-card p-12 rounded-2xl text-center">
        <p className="text-slate-600">No rainfall dataset uploaded yet.</p>
        <p className="text-sm text-slate-500 mt-2">Datasets containing a rainfall column appear here — upload one from the Upload page.</p>
      </div>
    );
  }

  if (!summaryLoaded) {
    return <DashboardLoadingSkeleton cardCount={cardsConfig.length} label="Loading rainfall data" />;
  }

  return (
    <AnalyticsDashboardTemplate
      key={datasetId}
      title="Rainfall Dashboard"
      fetchFn={fetchRainfallDataForTemplate}
      cardsConfig={cardsConfig}
      chartConfig={chartConfig}
      datasetId={datasetId}
      location={location}
      locations={locations}
      onLocationChange={setLocation}
      dateBounds={dateBounds}
      datasetOptions={datasets.map(d => ({ id: d.id, label: datasetDisplayLabel(d) }))}
      onDatasetChange={setSelectedId}
      aboutLabel="About this outlook"
      renderExtra={(data) => <RainOutlookPanel outlook={data?.rainOutlook} />}
    />
  );
};

export default RainfallDashboard;
