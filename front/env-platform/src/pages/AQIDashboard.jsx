import React from 'react';
import AnalyticsDashboardTemplate from '../components/layout/AnalyticsDashboardTemplate';

const mockAQIFetch = () => {
  return {
    currentAQI: 142,
    category: 'Moderate',
    dominantPollutant: 'PM2.5',
    avgChange: '+5%',
    series: Array.from({ length: 30 }).map((_, i) => ({
      date: `Oct ${i + 1}`,
      value: Math.floor(Math.random() * 100) + 100, // Random between 100-200
    }))
  };
};

const cardsConfig = [
  { title: 'Current AQI', dataKey: 'currentAQI', trend: '+5%', statusKey: 'category', color: 'orange' },
  { title: 'Dominant Pollutant', dataKey: 'dominantPollutant', trend: null, color: 'blue' },
  { title: '24h Change', dataKey: 'avgChange', trend: '+5%', color: 'yellow' },
  { title: 'Active Anomalies', dataKey: 'anomalies', trend: '2 New', color: 'red' }, // Mock stat
];

const chartConfig = {
  dataKey: 'value',
  color: '#f97316', // Orange
  yLabel: 'Air Quality Index'
};

const AQIDashboard = () => {
  return (
    <AnalyticsDashboardTemplate
      title="Air Quality (AQI) Dashboard"
      fetchFn={mockAQIFetch}
      cardsConfig={cardsConfig}
      chartConfig={chartConfig}
    />
  );
};

export default AQIDashboard;
