import React from 'react';
import AnalyticsDashboardTemplate from '../components/layout/AnalyticsDashboardTemplate';

const mockRainFetch = () => {
  return {
    total: '120 mm',
    intensity: 'Heavy',
    lastRain: '2 days ago',
    forecast: 'Light',
    series: Array.from({ length: 30 }).map((_, i) => ({
      date: `Oct ${i + 1}`,
      value: Math.floor(Math.random() * 20), // Random rainfall 0-20mm
    }))
  };
};

const cardsConfig = [
  { title: 'Total Rainfall', dataKey: 'total', trend: '+15%', color: 'blue' },
  { title: 'Intensity', dataKey: 'intensity', trend: null, statusKey: 'intensity', color: 'blue' },
  { title: 'Last Rainfall', dataKey: 'lastRain', trend: null, color: 'slate' },
  { title: 'Next 7 Days Forecast', dataKey: 'forecast', trend: null, color: 'yellow' },
];

const chartConfig = {
  dataKey: 'value',
  color: '#3b82f6', // Blue
  yLabel: 'Rainfall (mm)'
};

const RainfallDashboard = () => {
  return (
    <AnalyticsDashboardTemplate
      title="Rainfall Dashboard"
      fetchFn={mockRainFetch}
      cardsConfig={cardsConfig}
      chartConfig={chartConfig}
    />
  );
};

export default RainfallDashboard;
