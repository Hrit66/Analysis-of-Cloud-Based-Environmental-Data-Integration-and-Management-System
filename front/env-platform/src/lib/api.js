const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export async function fetchAQISummary(datasetId) {
  const res = await fetch(`${API_BASE}/analytics/aqi/${datasetId}/summary`);
  if (!res.ok) throw new Error('Failed to fetch AQI summary');
  return res.json();
}

export async function fetchAQIData(datasetId, location, startDate, endDate) {
  const params = new URLSearchParams();
  if (location) params.append('location', location);
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  params.append('limit', '1000');
  
  const res = await fetch(`${API_BASE}/analytics/aqi/${datasetId}?${params}`);
  if (!res.ok) throw new Error('Failed to fetch AQI data');
  return res.json();
}

export async function fetchAnomalies(datasetId, options = {}) {
  const params = new URLSearchParams();
  if (options.location) params.append('location', options.location);
  if (options.parameter) params.append('parameter', options.parameter);
  if (options.onlyAnomalies !== undefined) params.append('only_anomalies', options.onlyAnomalies);
  params.append('limit', '1000');
  
  const res = await fetch(`${API_BASE}/analytics/anomalies/${datasetId}?${params}`);
  if (!res.ok) throw new Error('Failed to fetch anomalies');
  return res.json();
}

export async function fetchAnomalySummary(datasetId) {
  const res = await fetch(`${API_BASE}/analytics/anomalies/${datasetId}/summary`);
  if (!res.ok) throw new Error('Failed to fetch anomaly summary');
  return res.json();
}

export async function fetchForecasts(datasetId, options = {}) {
  const params = new URLSearchParams();
  if (options.location) params.append('location', options.location);
  if (options.parameter) params.append('parameter', options.parameter);
  
  const res = await fetch(`${API_BASE}/analytics/forecasts/${datasetId}?${params}`);
  if (!res.ok) throw new Error('Failed to fetch forecasts');
  return res.json();
}

export async function fetchTrends(datasetId, location, parameter, days = 30) {
  const res = await fetch(`${API_BASE}/analytics/trends/${datasetId}?location=${location}&parameter=${parameter}&days=${days}`);
  if (!res.ok) throw new Error('Failed to fetch trends');
  return res.json();
}

export async function fetchDatasets() {
  const res = await fetch(`${API_BASE}/datasets`);
  if (!res.ok) throw new Error('Failed to fetch datasets');
  return res.json();
}

export async function uploadDataset(file, datasetType = 'air_quality') {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('dataset_type', datasetType);
  
  const res = await fetch(`${API_BASE}/datasets/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) throw new Error('Failed to upload dataset');
  return res.json();
}

export async function getDatasetStatus(datasetId) {
  const res = await fetch(`${API_BASE}/datasets/${datasetId}/status`);
  if (!res.ok) throw new Error('Failed to fetch dataset status');
  return res.json();
}

export async function deleteDataset(datasetId) {
  const res = await fetch(`${API_BASE}/datasets/${datasetId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to delete dataset');
  return res.json();
}

export function formatAQIDataForChart(aqiData, parameter = 'aqi') {
  if (!aqiData || !Array.isArray(aqiData)) return [];
  return aqiData
    .filter(d => d[parameter] !== null && d[parameter] !== undefined)
    .map(d => ({
      date: new Date(d.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      value: d[parameter],
      timestamp: d.timestamp,
    }))
    .reverse();
}

export function computeAQISummaryCards(aqiData) {
  if (!aqiData || !Array.isArray(aqiData) || aqiData.length === 0) {
    return {
      currentAQI: '-',
      category: '-',
      dominantPollutant: '-',
      avgChange: '-',
      anomalies: 0,
    };
  }
  
  const latest = aqiData[0];
  const values = aqiData.map(d => d.aqi).filter(v => v !== null);
  const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
  const prevAvg = values.length > 1 
    ? values.slice(1).reduce((a, b) => a + b, 0) / (values.length - 1)
    : avg;
  const change = prevAvg ? ((avg - prevAvg) / prevAvg * 100).toFixed(1) : 0;
  
  return {
    currentAQI: Math.round(latest.aqi),
    category: latest.aqi_category,
    dominantPollutant: latest.dominant_pollutant?.toUpperCase() || '-',
    avgChange: `${change >= 0 ? '+' : ''}${change}%`,
    anomalies: 0,
  };
}