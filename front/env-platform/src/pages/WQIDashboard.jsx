import React from 'react';
import AnalyticsDashboardTemplate from '../components/layout/AnalyticsDashboardTemplate';

const mockWQIFetch = () => {
  return {
    pH: 7.2,
    do: '6.5 mg/L',
    turbidity: '12 NTU',
    category: 'Good',
    series: Array.from({ length: 30 }).map((_, i) => ({
      date: `Oct ${i + 1}`,
      value: (Math.random() * 2 + 6).toFixed(1), // Random pH between 6-8
    }))
  };
};

const cardsConfig = [
  { title: 'Current pH Level', dataKey: 'pH', trend: null, statusKey: 'category', color: 'green' },
  { title: 'Dissolved Oxygen (DO)', dataKey: 'do', trend: '-2%', color: 'blue' },
  { title: 'Turbidity', dataKey: 'turbidity', trend: '+1%', color: 'yellow' },
  { title: 'Active Anomalies', dataKey: 'anomalies', trend: '0 New', color: 'slate' },
];

const chartConfig = {
  dataKey: 'value',
  color: '#0ea5e9', // Light Blue
  yLabel: 'pH Level'
};

const WQIDashboard = () => {
  return (
    <AnalyticsDashboardTemplate
      title="Water Quality (WQI) Dashboard"
      fetchFn={mockWQIFetch}
      cardsConfig={cardsConfig}
      chartConfig={chartConfig}
    />
  );
};

export default WQIDashboard;
