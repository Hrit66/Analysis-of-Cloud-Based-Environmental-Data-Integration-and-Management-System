import React, { useState, useEffect } from 'react';
import Card from '../common/Card';
import TrendLineChart from '../charts/TrendLineChart';
import { Calendar } from 'lucide-react';

const AnalyticsDashboardTemplate = ({ 
  title, 
  fetchFn, 
  cardsConfig, 
  chartConfig,
  apiEndpoint,
  datasetId,
  location,
}) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dateRange, setDateRange] = useState({ 
    from: new Date(Date.now() - 30 * 86400000).toISOString().split('T')[0],
    to: new Date().toISOString().split('T')[0],
  });

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      setError(null);
      try {
        let result;
        if (apiEndpoint && datasetId) {
          if (apiEndpoint === 'aqi') {
            const [summary, trends] = await Promise.all([
              fetchFn(datasetId),
              fetch(`${import.meta.env.VITE_API_URL}/analytics/trends/${datasetId}?location=${location}&parameter=${chartConfig.dataKey || 'aqi'}&days=30`).then(r => r.json()),
            ]);
            result = {
              ...summary,
              series: trends.data || [],
            };
          } else if (apiEndpoint === 'anomalies') {
            result = await fetchFn(datasetId);
          } else {
            result = await fetchFn(datasetId);
          }
        } else if (typeof fetchFn === 'function') {
          result = fetchFn();
        } else {
          result = fetchFn;
        }
        setData(result);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [fetchFn, apiEndpoint, datasetId, location, chartConfig.dataKey, dateRange]);

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 bg-slate-200 rounded w-64"></div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {[1,2,3,4].map(i => <div key={i} className="h-32 bg-slate-200 rounded-xl"></div>)}
        </div>
        <div className="h-96 bg-slate-200 rounded-xl"></div>
      </div>
    );
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
    value: data ? (data[card.dataKey] ?? data[card.title.toLowerCase().replace(/\s+/g, '')] ?? '-') : '-',
    trend: card.trend || (data ? data[card.trendKey] : null),
    status: data ? data[card.statusKey] : null,
  }));

  const chartData = data?.series || (data ? formatSeriesData(data) : []);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{title}</h1>
          <p className="text-slate-600 mt-1">
            {location ? `${location} - ` : ''}Dataset: {datasetId ? datasetId.slice(0, 8) + '...' : 'N/A'}
          </p>
        </div>
        
        <div className="flex items-center gap-2 glass-card rounded-xl p-2 px-4 shadow-sm animate-fade-in-up">
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

      {/* Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {cardValues.map((card, idx) => (
          <Card 
            key={idx}
            title={card.title}
            value={card.value}
            trend={card.trend}
            status={card.status}
            color={card.color}
          />
        ))}
      </div>

      {/* Main Chart */}
      <div className="glass-card p-6 rounded-2xl animate-fade-in-up" style={{ animationDelay: '200ms' }}>
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-bold text-slate-800">Historical Trend</h2>
        </div>
        <TrendLineChart 
          data={chartData} 
          dataKey={chartConfig.dataKey}
          color={chartConfig.color}
          yLabel={chartConfig.yLabel}
        />
      </div>
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
