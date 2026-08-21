import React, { useState, useEffect } from 'react';
import Card from '../common/Card';
import TrendLineChart from '../charts/TrendLineChart';
import { Calendar } from 'lucide-react';

const AnalyticsDashboardTemplate = ({ title, fetchFn, cardsConfig, chartConfig }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dateRange, setDateRange] = useState({ from: '2023-10-10', to: '2023-10-17' });

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      // Simulate API fetch delay
      setTimeout(() => {
        const mockData = fetchFn();
        setData(mockData);
        setLoading(false);
      }, 800);
    };
    loadData();
  }, [fetchFn, dateRange]);

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

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{title}</h1>
          <p className="text-slate-600 mt-1">Delhi Station - Dataset: Delhi_AQI_2023.csv</p>
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
        {cardsConfig.map((card, idx) => (
          <Card 
            key={idx}
            title={card.title}
            value={data ? data[card.dataKey] : '-'}
            trend={card.trend}
            status={data ? data[card.statusKey] : null}
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
          data={data ? data.series : []} 
          dataKey={chartConfig.dataKey}
          color={chartConfig.color}
          yLabel={chartConfig.yLabel}
        />
      </div>
    </div>
  );
};

export default AnalyticsDashboardTemplate;
