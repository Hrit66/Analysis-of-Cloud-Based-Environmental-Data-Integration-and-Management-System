import React, { useState, useEffect } from 'react';
import AnalyticsDashboardTemplate from '../components/layout/AnalyticsDashboardTemplate';
import { fetchAQISummary, fetchAQIData, computeAQISummaryCards } from '../lib/api';

const cardsConfig = [
  { title: 'Current AQI', dataKey: 'currentAQI', statusKey: 'category', color: 'orange' },
  { title: 'Dominant Pollutant', dataKey: 'dominantPollutant', color: 'blue' },
  { title: '24h Change', dataKey: 'avgChange', color: 'yellow' },
  { title: 'Active Anomalies', dataKey: 'anomalies', color: 'red' },
];

const chartConfig = {
  dataKey: 'value',
  color: '#f97316',
  yLabel: 'Air Quality Index'
};

const AQIDashboard = () => {
  const [datasetId, setDatasetId] = useState(null);
  const [location, setLocation] = useState(null);
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    fetch(`${import.meta.env.VITE_API_URL}/datasets?status=COMPLETED`)
      .then(r => r.json())
      .then(data => {
        if (data.length > 0) {
          setDatasetId(data[0].id);
        }
      });
  }, []);

  useEffect(() => {
    if (!datasetId) return;
    fetchAQISummary(datasetId)
      .then(data => {
        if (data.length > 0) {
          setSummary(data[0]);
          setLocation(data[0].location);
        }
      })
      .catch(console.error);
  }, [datasetId]);

  const fetchAQIDataForTemplate = async (id) => {
    if (!id) return null;
    const aqiData = await fetchAQIData(id, location);
    return computeAQISummaryCards(aqiData);
  };

  if (!datasetId) {
    return (
      <div className="glass-card p-12 rounded-2xl text-center">
        <p className="text-slate-600">No completed datasets found.</p>
        <p className="text-sm text-slate-500 mt-2">Upload a dataset first from the Upload page.</p>
      </div>
    );
  }

  return (
    <AnalyticsDashboardTemplate
      title="Air Quality (AQI) Dashboard"
      fetchFn={fetchAQIDataForTemplate}
      cardsConfig={cardsConfig}
      chartConfig={chartConfig}
      apiEndpoint="aqi"
      datasetId={datasetId}
      location={location || summary?.location}
    />
  );
};

export default AQIDashboard;
