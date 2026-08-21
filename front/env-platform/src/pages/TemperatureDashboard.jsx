import React from 'react';
import AnalyticsDashboardTemplate from '../components/layout/AnalyticsDashboardTemplate';

const mockTempFetch = () => {
  return {
    currentTemp: '32°C',
    min: '24°C',
    max: '35°C',
    avg: '29°C',
    series: Array.from({ length: 30 }).map((_, i) => ({
      date: `Oct ${i + 1}`,
      value: Math.floor(Math.random() * 10) + 25, // Random temp between 25-35
    }))
  };
};

const cardsConfig = [
  { title: 'Current Temperature', dataKey: 'currentTemp', trend: '+1°C', color: 'orange' },
  { title: 'Today\'s Min', dataKey: 'min', trend: null, color: 'blue' },
  { title: 'Today\'s Max', dataKey: 'max', trend: null, color: 'red' },
  { title: 'Weekly Average', dataKey: 'avg', trend: '-0.5°C', color: 'yellow' },
];

const chartConfig = {
  dataKey: 'value',
  color: '#ef4444', // Red
  yLabel: 'Temperature (°C)'
};

const TemperatureDashboard = () => {
  return (
    <AnalyticsDashboardTemplate
      title="Temperature Dashboard"
      fetchFn={mockTempFetch}
      cardsConfig={cardsConfig}
      chartConfig={chartConfig}
    />
  );
};

export default TemperatureDashboard;
