import React, { useState, useEffect } from 'react';
import Card from '../common/Card';
import DashboardLoadingSkeleton from '../common/DashboardLoadingSkeleton';
import TrendLineChart from '../charts/TrendLineChart';
import TrendBarChart from '../charts/TrendBarChart';
import { Calendar, Info } from 'lucide-react';

const toDateInput = (value) => {
  if (!value) return null;
  if (typeof value === 'string') {
    const match = value.match(/^(\d{4}-\d{2}-\d{2})/);
    if (match) return match[1];
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
};

const AnalyticsDashboardTemplate = ({ 
  title, 
  fetchFn, 
  cardsConfig, 
  chartConfig,
  datasetId,
  location,
  locations = [],
  onLocationChange,
  dateBounds = null,
  chartNote = null,
  summaryNote = null,
  sourceLabel = null,
  datasetOptions = null,
  onDatasetChange,
  windowDays = 30,
  aboutLabel = 'About this forecast',
  legendItems = null,
  banner = null,
  renderExtra = null,
}) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [dateRange, setDateRange] = useState({ 
    from: toDateInput(new Date(Date.now() - 30 * 86400000)),
    to: toDateInput(new Date()),
  });

  useEffect(() => {
    if (!dateBounds?.latest) return;
    const latest = toDateInput(dateBounds.latest);
    if (!latest) return;
    const latestDate = new Date(`${latest}T00:00:00`);
    const windowStart = new Date(latestDate.getTime() - windowDays * 86400000);
    const first = toDateInput(dateBounds.first);
    const from = first && new Date(`${first}T00:00:00`) > windowStart ? first : toDateInput(windowStart);
    setDateRange({ from, to: latest });
  }, [dateBounds, windowDays]);

  useEffect(() => {
    let active = true;
    const loadData = async () => {
      setLoading(true);
      setError(null);
      try {
        let result;
        if (typeof fetchFn === 'function') {
          result = await fetchFn(datasetId, dateRange.from, dateRange.to);
        } else {
          result = fetchFn;
        }
        if (active) setData(result);
      } catch (err) {
        if (active) setError(err.message);
      } finally {
        if (active) setLoading(false);
      }
    };
    loadData();
    return () => { active = false; };
  }, [datasetId, location, dateRange]);

  const cardsGridClass = cardsConfig.length >= 6 ? 'lg:grid-cols-6' : cardsConfig.length > 4 ? 'lg:grid-cols-5' : 'lg:grid-cols-4';

  if (loading) {
    return <DashboardLoadingSkeleton cardCount={cardsConfig.length} />;
  }

  if (error) {
    return (
      <div className="glass-card p-6 rounded-2xl text-center">
        <p className="text-red-600">Error loading data: {error}</p>
        <p className="text-sm text-slate-500 mt-2">Make sure backend is running at {import.meta.env.VITE_API_URL}</p>
      </div>
    );
  }

  const cardValues = cardsConfig.map(card => ({
    ...card,
    title: card.titleKey && data ? (data[card.titleKey] ?? card.title) : card.title,
    value: data ? (data[card.dataKey] ?? data[card.title.toLowerCase().replace(/\s+/g, '')] ?? '-') : '-',
    trend: card.trend || (data ? data[card.trendKey] : null),
    status: data ? data[card.statusKey] : null,
    color: typeof card.color === 'function' ? card.color(data) : card.color,
    caption: card.captionKey && data ? (data[card.captionKey] ?? card.caption ?? null) : (card.caption || null),
  }));

  const chartData = data?.series || (data ? formatSeriesData(data) : []);
  const resolvedChartConfig = typeof chartConfig === 'function' ? chartConfig(data) : chartConfig;
  const resolvedSummary = data?.summaryNote || summaryNote;
  const aboutContent = data?.chartNote || chartNote;
  const extraContent = typeof renderExtra === 'function' ? renderExtra(data) : renderExtra;
  const datasetLabel = datasetOptions?.find(option => option.id === datasetId)?.label
    || (datasetId ? `${datasetId.slice(0, 8)}...` : 'N/A');

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{title}</h1>
          <p className="text-slate-600 mt-1">
            {location ? `${location} - ` : ''}Dataset: {datasetLabel}
          </p>
        </div>
        
        <div className="flex items-center gap-2 glass-card rounded-xl p-2 px-4 shadow-sm animate-fade-in-up">
          {datasetOptions && datasetOptions.length > 0 && (
            <>
              <select
                value={datasetId || ''}
                onChange={(e) => onDatasetChange && onDatasetChange(e.target.value)}
                className="text-sm text-slate-700 bg-transparent outline-none max-w-[220px]"
                title="Dataset shown on this page"
              >
                {datasetOptions.map((option) => (
                  <option key={option.id} value={option.id}>{option.label}</option>
                ))}
              </select>
              <span className="text-slate-300">|</span>
            </>
          )}
          {locations.length > 0 && (
            <>
              <select
                value={location || ''}
                onChange={(e) => onLocationChange && onLocationChange(e.target.value)}
                className="text-sm text-slate-700 bg-transparent outline-none max-w-[160px]"
              >
                {locations.map((loc) => (
                  <option key={loc} value={loc}>{loc}</option>
                ))}
              </select>
              <span className="text-slate-300">|</span>
            </>
          )}
          <Calendar className="w-4 h-4 text-slate-500" />
          <input 
            type="date" 
            value={dateRange.from}
            onChange={(e) => setDateRange({...dateRange, from: e.target.value})}
            className="text-sm text-slate-700 bg-transparent outline-none"
          />
          <span className="text-slate-400">to</span>
          <input 
            type="date" 
            value={dateRange.to}
            onChange={(e) => setDateRange({...dateRange, to: e.target.value})}
            className="text-sm text-slate-700 bg-transparent outline-none"
          />
        </div>
      </div>

      {banner}

      {/* Cards Grid */}
      <div className={`grid grid-cols-1 md:grid-cols-2 ${cardsGridClass} gap-6`}>
        {cardValues.map((card, idx) => (
          <Card 
            key={idx}
            title={card.title}
            value={card.value}
            trend={card.trend}
            status={card.status}
            color={card.color}
            trendLabel={card.trendLabel}
            trendTone={card.trendTone}
            caption={card.caption}
            onClick={card.onClick}
          />
        ))}
      </div>

      {extraContent}

      {/* Main Chart */}
      <div className="glass-card p-6 rounded-2xl animate-fade-in-up" style={{ animationDelay: '200ms' }}>
        <div className="flex justify-between items-center mb-4 gap-3 flex-wrap">
          <h2 className="text-lg font-bold text-slate-800">Historical Trend</h2>
          {legendItems && (
            <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
              <span className="text-slate-400">Lower is better:</span>
              {legendItems.map(item => (
                <span key={item.label} className={`px-1.5 py-0.5 rounded border font-medium ${item.className}`}>{item.label}</span>
              ))}
            </div>
          )}
        </div>
        {resolvedChartConfig.variant === 'bar' ? (
          <TrendBarChart
            data={chartData}
            dataKey={resolvedChartConfig.dataKey}
            color={resolvedChartConfig.color}
            yLabel={resolvedChartConfig.yLabel}
            tooltipName={resolvedChartConfig.tooltipName}
            unit={resolvedChartConfig.unit}
            timeAxis={resolvedChartConfig.timeAxis}
          />
        ) : (
          <TrendLineChart 
            data={chartData} 
            dataKey={resolvedChartConfig.dataKey}
            color={resolvedChartConfig.color}
            yLabel={resolvedChartConfig.yLabel}
            tooltipName={resolvedChartConfig.tooltipName}
            unit={resolvedChartConfig.unit}
            extraLines={resolvedChartConfig.extraLines}
            timeAxis={resolvedChartConfig.timeAxis}
          />
        )}
        {(resolvedSummary || aboutContent || sourceLabel) && (
          <div className="mt-3 text-xs text-slate-400">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
              {resolvedSummary ? (
                <>
                  <span>{resolvedSummary}</span>
                  {aboutContent && (
                    <button
                      type="button"
                      onClick={() => setAboutOpen(open => !open)}
                      className="inline-flex items-center gap-1 text-slate-400 hover:text-slate-600 transition-colors sm:shrink-0"
                    >
                      <Info className="w-3.5 h-3.5" />
                      {aboutOpen ? 'Hide details' : aboutLabel}
                    </button>
                  )}
                </>
              ) : (
                <>
                  {aboutContent && <span>{aboutContent}</span>}
                  {sourceLabel && <span className="sm:text-right">{sourceLabel}</span>}
                </>
              )}
            </div>
            {aboutOpen && aboutContent && (
              <div className="mt-2 border-t border-slate-100 pt-2 leading-relaxed">
                {aboutContent}
              </div>
            )}
          </div>
        )}
      </div>

      {data?.breakdown && (
        <div className="glass-card p-6 rounded-2xl animate-fade-in-up" style={{ animationDelay: '250ms' }}>
          {data.breakdown}
        </div>
      )}
    </div>
  );
};

function formatSeriesData(data) {
  if (Array.isArray(data)) {
    return data.map(d => ({
      date: d.timestamp ? new Date(d.timestamp).toLocaleDateString() : d.date,
      value: d.value ?? d.aqi ?? d[Object.keys(d).find(k => typeof d[k] === 'number')],
    }));
  }
  return [];
}

export default AnalyticsDashboardTemplate;
