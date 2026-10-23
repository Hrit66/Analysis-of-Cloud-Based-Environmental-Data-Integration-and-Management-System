import axios from 'axios';

export const API_BASE = import.meta.env.DEV
  ? '/api'
  : import.meta.env.VITE_API_URL || '/api';

let refreshPromise = null;
const REFRESH_LOCK = 'env-platform-auth-refresh';
const authChannel = typeof BroadcastChannel !== 'undefined'
  ? new BroadcastChannel('env-platform-auth')
  : null;

if (authChannel) {
  authChannel.onmessage = (event) => {
    if (event.data?.type === 'access-token' && event.data.token) {
      localStorage.setItem('token', event.data.token);
    }
  };
}

async function performRefresh() {
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    });
    if (!res.ok) return null;
    const data = await res.json();
    localStorage.setItem('token', data.access_token);
    authChannel?.postMessage({ type: 'access-token', token: data.access_token });
    return data.access_token;
  } catch {
    return null;
  }
}

export async function refreshAccessToken() {
  if (refreshPromise) return refreshPromise;
  const baseline = localStorage.getItem('token');
  const run = async () => {
    const refreshIfStillStale = async () => {
      const current = localStorage.getItem('token');
      if (current && current !== baseline) return current;
      return performRefresh();
    };
    if (typeof navigator !== 'undefined' && navigator.locks?.request) {
      return navigator.locks.request(REFRESH_LOCK, refreshIfStillStale);
    }
    return refreshIfStillStale();
  };
  refreshPromise = run().catch(() => null).finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

export async function authFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem('token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let res = await fetch(url, { ...options, headers, credentials: 'include' });
  if (res.status === 401 && !options._retried) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      headers.set('Authorization', `Bearer ${refreshed}`);
      res = await fetch(url, { ...options, headers, credentials: 'include', _retried: true });
    }
  }
  return res;
}

export async function fetchAQISummary(datasetId) {
  const res = await authFetch(`${API_BASE}/analytics/aqi/${datasetId}/summary`);
  if (!res.ok) throw new Error('Failed to fetch AQI summary');
  return res.json();
}

export async function fetchAQIData(datasetId, location, startDate, endDate) {
  const params = new URLSearchParams();
  if (location) params.append('location', location);
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  params.append('limit', '1000');
  
  const res = await authFetch(`${API_BASE}/analytics/aqi/${datasetId}?${params}`);
  if (!res.ok) throw new Error('Failed to fetch AQI data');
  const data = await res.json();
  return data.items || data;
}

export async function fetchAnomalies(datasetId, options = {}) {
  const params = new URLSearchParams();
  if (options.location) params.append('location', options.location);
  if (options.parameter) params.append('parameter', options.parameter);
  if (options.onlyAnomalies !== undefined) params.append('only_anomalies', options.onlyAnomalies);
  if (options.startDate) params.append('start_date', options.startDate);
  if (options.endDate) params.append('end_date', options.endDate);
  params.append('limit', '1000');
  
  const res = await authFetch(`${API_BASE}/analytics/anomalies/${datasetId}?${params}`);
  if (!res.ok) throw new Error('Failed to fetch anomalies');
  const data = await res.json();
  return data.items || data;
}

export async function fetchAnomalySummary(datasetId, startDate, endDate, location) {
  const params = new URLSearchParams();
  if (startDate) params.append('start_date', `${startDate}T00:00:00`);
  if (endDate) params.append('end_date', `${endDate}T23:59:59.999999`);
  if (location) params.append('location', location);
  const query = params.toString();
  const res = await authFetch(
    `${API_BASE}/analytics/anomalies/${datasetId}/summary${query ? `?${query}` : ''}`
  );
  if (!res.ok) throw new Error('Failed to fetch anomaly summary');
  return res.json();
}

export async function fetchForecasts(datasetId, options = {}) {
  const params = new URLSearchParams();
  if (options.location) params.append('location', options.location);
  if (options.parameter) params.append('parameter', options.parameter);
  
  const res = await authFetch(`${API_BASE}/analytics/forecasts/${datasetId}?${params}`);
  if (!res.ok) throw new Error('Failed to fetch forecasts');
  const data = await res.json();
  return data.items || data;
}

export async function fetchTrends(datasetId, location, parameter, days = 30) {
  const res = await authFetch(`${API_BASE}/analytics/trends/${datasetId}?location=${location}&parameter=${parameter}&days=${days}`);
  if (!res.ok) throw new Error('Failed to fetch trends');
  return res.json();
}

export function authHeaders(extra = {}) {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('token') : null;
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

const reportError = async (res, fallback) => {
  let message = fallback;
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') message = body.detail;
  } catch {
    // response was not JSON
  }
  const error = new Error(message);
  error.status = res.status;
  const retryAfter = res.headers.get('retry-after');
  if (retryAfter) error.retryAfter = Number(retryAfter);
  return error;
};

const reportPayload = ({ datasetIds, dataTypes, from, to }) => {
  const payload = {
    dataset_ids: datasetIds && datasetIds.length > 0 ? datasetIds : 'all',
    data_types: dataTypes || [],
  };
  if (from) payload.from = `${from}T00:00:00`;
  if (to) payload.to = `${to}T00:00:00`;
  return payload;
};

const filenameFromDisposition = (res, fallback) => {
  const header = res.headers.get('content-disposition') || '';
  const match = header.match(/filename="?([^";]+)"?/);
  return match ? match[1] : fallback;
};

export async function previewReport(options) {
  const res = await authFetch(`${API_BASE}/reports/preview`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(reportPayload(options)),
  });
  if (!res.ok) throw await reportError(res, 'Failed to load report preview');
  return res.json();
}

export async function exportReport(options) {
  const res = await authFetch(`${API_BASE}/reports/export`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ ...reportPayload(options), format: options.format || 'xlsx' }),
  });
  if (res.status === 202) return { job: await res.json() };
  if (!res.ok) throw await reportError(res, 'Report export failed');
  const extension = options.format === 'csv' ? 'csv.zip' : options.format || 'xlsx';
  return {
    blob: await res.blob(),
    filename: filenameFromDisposition(res, `envplatform_report.${extension}`),
  };
}

export async function fetchReportJob(jobId) {
  const res = await authFetch(`${API_BASE}/reports/jobs/${jobId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw await reportError(res, 'Failed to check report status');
  return res.json();
}

export async function downloadReportJob(jobId, format) {
  const res = await authFetch(`${API_BASE}/reports/jobs/${jobId}/download`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw await reportError(res, 'Failed to download report');
  const extension = format === 'csv' ? 'csv.zip' : format || 'xlsx';
  return {
    blob: await res.blob(),
    filename: filenameFromDisposition(res, `envplatform_report.${extension}`),
  };
}

export async function fetchMyQuota() {
  const res = await authFetch(`${API_BASE}/auth/me/usage`);
  if (!res.ok) throw new Error('Failed to fetch quota');
  return res.json();
}

export async function fetchDatasets() {
  const res = await authFetch(`${API_BASE}/datasets`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to fetch datasets');
  const data = await res.json();
  // Handle both old format (array) and new paginated format (items array)
  return data.items || data;
}

const uploadFailure = (error, fallback) => {
  const detail = error?.response?.data?.detail;
  const wrapped = new Error(typeof detail === 'string' ? detail : fallback);
  wrapped.status = error?.response?.status;
  return wrapped;
};

async function postFormWithProgress(path, formData, onUploadProgress) {
  const send = (token) => axios.post(`${API_BASE}${path}`, formData, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    onUploadProgress: (event) => {
      if (!onUploadProgress) return;
      const total = Number(event.total || 0);
      onUploadProgress(total > 0 ? Math.min(1, event.loaded / total) : 0);
    },
  });

  try {
    return await send(typeof localStorage !== 'undefined' ? localStorage.getItem('token') : null);
  } catch (error) {
    if (error?.response?.status === 401) {
      const refreshed = await refreshAccessToken();
      if (refreshed) return send(refreshed);
    }
    throw error;
  }
}

export async function uploadDataset(file, datasetType = 'air_quality', options = {}) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('dataset_type', datasetType);
  if (options.sourceTag) formData.append('source_tag', options.sourceTag);

  try {
    const res = await postFormWithProgress(
      '/datasets/upload', formData, options.onUploadProgress
    );
    return res.data;
  } catch (error) {
    throw uploadFailure(error, 'Failed to upload dataset');
  }
}

export async function uploadIMDFiles(files, location, options = {}) {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  if (location) formData.append('location', location);
  if (options.sourceTag) formData.append('source_tag', options.sourceTag);

  try {
    const res = await postFormWithProgress(
      '/datasets/upload-imd', formData, options.onUploadProgress
    );
    return res.data;
  } catch (error) {
    throw uploadFailure(error, 'Failed to upload IMD files');
  }
}

export async function uploadRiverSummaryFiles(files, location, options = {}) {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  if (location) formData.append('location', location);
  if (options.sourceTag) formData.append('source_tag', options.sourceTag);

  try {
    const res = await postFormWithProgress(
      '/datasets/upload-river-summary', formData, options.onUploadProgress
    );
    return res.data;
  } catch (error) {
    throw uploadFailure(error, 'Failed to upload river summary files');
  }
}

export async function getDatasetStatus(datasetId) {
  const res = await authFetch(`${API_BASE}/datasets/${datasetId}/status`);
  if (!res.ok) throw new Error('Failed to fetch dataset status');
  return res.json();
}

export async function fetchDataset(datasetId) {
  const res = await authFetch(`${API_BASE}/datasets/${datasetId}`);
  if (!res.ok) throw await reportError(res, 'Failed to fetch dataset');
  return res.json();
}

export async function fetchDatasetJob(jobId, timeoutMs = 10000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await authFetch(`${API_BASE}/datasets/jobs/${jobId}`, {
      signal: controller.signal,
    });
    if (!res.ok) throw await reportError(res, 'Failed to fetch processing progress');
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

export async function cancelDatasetJob(jobId) {
  const res = await authFetch(`${API_BASE}/datasets/jobs/${jobId}/cancel`, {
    method: 'POST',
  });
  if (!res.ok) throw await reportError(res, 'Failed to cancel processing');
  return res.json();
}

export async function deleteDataset(datasetId) {
  const res = await authFetch(`${API_BASE}/datasets/${datasetId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw await reportError(res, 'Failed to delete dataset');
  return res.json();
}

export async function renameDataset(datasetId, displayName) {
  const res = await authFetch(`${API_BASE}/datasets/${datasetId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!res.ok) throw new Error('Failed to rename dataset');
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

const AQI_CATEGORY_BANDS = [
  [0, 50, 'Good'],
  [50, 100, 'Satisfactory'],
  [100, 200, 'Moderate'],
  [200, 300, 'Poor'],
  [300, 400, 'Very Poor'],
  [400, 500, 'Severe'],
];

export function aqiCategoryFor(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  const numeric = Number(value);
  if (numeric < 0) return '-';
  return AQI_CATEGORY_BANDS.find(([, high]) => numeric <= high)?.[2] || 'Severe';
}

const formatLatestDate = (timestamp) => {
  if (!timestamp) return '';
  const raw = String(timestamp);
  const dateOnly = raw.match(/^(\d{4}-\d{2}-\d{2})/)?.[1];
  const date = dateOnly ? new Date(`${dateOnly}T12:00:00+05:30`) : new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
};

export function computeAQISummaryCards(aqiData) {
  const empty = {
    currentAQI: '-',
    category: '-',
    dominantPollutant: '-',
    pmAqi: '-',
    avgChange: '-',
    anomalies: 0,
    latestTitle: 'Latest AQI',
    latestDateLabel: '',
    pmAqiCaption: 'needs PM2.5 or PM10 sub-index',
  };
  if (!aqiData || !Array.isArray(aqiData) || aqiData.length === 0) {
    return empty;
  }
  
  const valid = aqiData.filter(d => d.aqi !== null && d.aqi !== undefined && !Number.isNaN(d.aqi));
  if (valid.length === 0) {
    return empty;
  }
  
  const byDay = new Map();
  for (const d of valid) {
    const day = new Date(d.timestamp).toISOString().split('T')[0];
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(d.aqi);
  }
  const days = [...byDay.keys()].sort();
  const mean = (arr) => arr.reduce((a, b) => a + b, 0) / arr.length;
  
  const latest = valid.reduce((a, b) => (new Date(b.timestamp) > new Date(a.timestamp) ? b : a));
  
  let change = 0;
  if (days.length > 1) {
    // Compare the same integers the AQI card shows (178 vs 193), so the
    // displayed percentage cannot disagree with the displayed values.
    const latestDayMean = Math.round(mean(byDay.get(days[days.length - 1])));
    const prevDayMean = Math.round(mean(byDay.get(days[days.length - 2])));
    change = prevDayMean ? ((latestDayMean - prevDayMean) / prevDayMean) * 100 : 0;
  }
  const roundedChange = Math.round((change + Number.EPSILON) * 10) / 10;
  
  const pm25 = latest.sub_indices?.pm25;
  const pm10 = latest.sub_indices?.pm10;
  const pmValues = [pm25, pm10].filter(v => v !== null && v !== undefined && !Number.isNaN(v));
  const pmAqi = pmValues.length > 0 ? Math.round(Math.max(...pmValues)) : '-';
  const pmParts = [
    pm25 !== null && pm25 !== undefined ? `PM2.5 ${Math.round(pm25 * 10) / 10}` : null,
    pm10 !== null && pm10 !== undefined ? `PM10 ${Math.round(pm10 * 10) / 10}` : null,
  ].filter(Boolean);

  return {
    currentAQI: Math.round(latest.aqi),
    category: latest.aqi_category,
    dominantPollutant: latest.dominant_pollutant?.toUpperCase() || '-',
    pmAqi,
    pmAqiCaption: pmParts.length > 0 ? `max sub-index · ${pmParts.join(' / ')}` : 'needs PM2.5 or PM10 sub-index',
    avgChange: `${roundedChange >= 0 ? '+' : ''}${roundedChange.toFixed(1)}%`,
    anomalies: 0,
    latestTitle: latest ? `Latest AQI · ${formatLatestDate(latest.timestamp)}` : 'Latest AQI',
    latestDateLabel: formatLatestDate(latest.timestamp),
  };
}

export async function fetchTemperatureData(datasetId, location, startDate, endDate) {
  const params = new URLSearchParams();
  if (location) params.append('location', location);
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  params.append('limit', '1000');
  
  const res = await authFetch(`${API_BASE}/analytics/temperature/${datasetId}?${params}`);
  if (!res.ok) throw new Error('Failed to fetch temperature data');
  return res.json();
}

export async function fetchTemperatureSummary(datasetId, location) {
  const params = new URLSearchParams();
  if (location) params.append('location', location);
  
  const res = await authFetch(`${API_BASE}/analytics/temperature/${datasetId}/summary?${params}`);
  if (!res.ok) throw new Error('Failed to fetch temperature summary');
  return res.json();
}

export async function fetchDatasetDateRange(datasetId) {
  const res = await authFetch(`${API_BASE}/analytics/date-range/${datasetId}`);
  if (!res.ok) throw new Error('Failed to fetch dataset date range');
  return res.json();
}

export const MIN_RAIN_CLIMATOLOGY_YEARS = 10;

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function datasetDisplayLabel(dataset) {
  if (!dataset) return '';
  if (dataset.display_name) return dataset.display_name;
  const filename = dataset.filename || dataset.id;
  const isImd = Boolean(dataset.cleaning_report?.source_format?.startsWith('imd')) || filename.startsWith('IMD:');
  if (isImd) {
    const clean = filename.replace(/^IMD:\s*/, '');
    const years = clean.match(/(\d{4})_(\d{4})/);
    const place = clean.match(/(?:rain|temp|weather)_([a-z]+)/i);
    const placeName = place ? place[1][0].toUpperCase() + place[1].slice(1) : null;
    return ['IMD', placeName, years ? `${years[1]}–${years[2]}` : null].filter(Boolean).join(' · ');
  }
  return filename.replace(/\.(csv|json|xlsx|xls|parquet)$/i, '');
}

export function formatCoverage(bounds) {
  const label = (value) => {
    const match = String(value || '').match(/^(\d{4})-(\d{2})/);
    if (!match) return null;
    const month = MONTH_NAMES[Number(match[2]) - 1];
    return month ? `${month} ${match[1]}` : null;
  };
  const first = label(bounds?.first);
  const latest = label(bounds?.latest);
  if (!first || !latest) return null;
  return `${first} – ${latest}`;
}

export function datasetHistoryYears(bounds) {
  const first = new Date(bounds?.first || NaN);
  const latest = new Date(bounds?.latest || NaN);
  if (Number.isNaN(first.getTime()) || Number.isNaN(latest.getTime())) return null;
  return (latest - first) / (365.25 * 86400000);
}

export function rainChanceUncertaintyPct(years, wetYears) {
  if (!years || wetYears === null || wetYears === undefined || years < 2) return null;
  const p = wetYears / years;
  const standardError = Math.sqrt((p * (1 - p)) / years);
  return Math.max(1, Math.round(1.96 * standardError * 100));
}

export function buildSourceLabel(datasetMeta, bounds) {
  const isImd = Boolean(datasetMeta?.cleaning_report?.source_format?.startsWith('imd'));
  const rows = datasetMeta?.row_count ? `${datasetMeta.row_count.toLocaleString()} rows` : null;
  const coverage = formatCoverage(bounds);
  return [isImd ? 'Source: IMD 1° grid' : 'Source: uploaded dataset', rows, coverage].filter(Boolean).join(' · ');
}

export function computeTempSummaryCards(tempData) {
  if (!tempData || !Array.isArray(tempData) || tempData.length === 0) {
    return { currentTemp: '-', min: '-', max: '-', avg: '-' };
  }
  
  const valid = tempData.filter(d => d.temperature !== null && d.temperature !== undefined && !Number.isNaN(d.temperature));
  if (valid.length === 0) {
    return { currentTemp: '-', min: '-', max: '-', avg: '-' };
  }
  
  const latest = valid[0];
  const previous = valid[1];
  const values = valid.map(d => d.temperature);
  const avg = values.reduce((a, b) => a + b, 0) / values.length;
  
  const minCandidates = valid.map(d => d.temp_min).filter(v => v !== null && v !== undefined && !Number.isNaN(v));
  const maxCandidates = valid.map(d => d.temp_max).filter(v => v !== null && v !== undefined && !Number.isNaN(v));
  const min = minCandidates.length ? Math.min(...minCandidates) : Math.min(...values);
  const max = maxCandidates.length ? Math.max(...maxCandidates) : Math.max(...values);
  
  const delta = (current, prev) => {
    if (current === null || current === undefined || prev === null || prev === undefined) return null;
    if (Number.isNaN(current) || Number.isNaN(prev)) return null;
    const d = Math.round((current - prev) * 10) / 10;
    if (d === 0) return '0.0°C';
    return `${d > 0 ? '+' : ''}${d.toFixed(1)}°C`;
  };
  
  const mean = (arr) => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
  const lastWeek = mean(values.slice(0, 7));
  const prevWeek = mean(values.slice(7, 14));
  
  return {
    currentTemp: `${latest.temperature.toFixed(1)}°C`,
    currentTrend: delta(latest.temperature, previous?.temperature),
    min: `${min.toFixed(1)}°C`,
    minTrend: delta(latest.temp_min, previous?.temp_min),
    max: `${max.toFixed(1)}°C`,
    maxTrend: delta(latest.temp_max, previous?.temp_max),
    avg: `${avg.toFixed(1)}°C`,
    avgTrend: delta(lastWeek, prevWeek),
  };
}

export async function fetchRainfallData(datasetId, location, startDate, endDate) {
  const params = new URLSearchParams();
  if (location) params.append('location', location);
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  params.append('limit', '1000');
  
  const res = await authFetch(`${API_BASE}/analytics/rainfall/${datasetId}?${params}`);
  if (!res.ok) throw new Error('Failed to fetch rainfall data');
  return res.json();
}

export async function fetchRainfallSummary(datasetId, location) {
  const params = new URLSearchParams();
  if (location) params.append('location', location);
  
  const res = await authFetch(`${API_BASE}/analytics/rainfall/${datasetId}/summary?${params}`);
  if (!res.ok) throw new Error('Failed to fetch rainfall summary');
  return res.json();
}

export async function fetchRainfallOutlook(datasetId, location) {
  const params = new URLSearchParams();
  if (location) params.append('location', location);
  
  const res = await authFetch(`${API_BASE}/analytics/rainfall/${datasetId}/outlook?${params}`);
  if (!res.ok) throw new Error('Failed to fetch rainfall outlook');
  return res.json();
}

export function computeRainfallSummaryCards(rainfallData) {
  if (!rainfallData || !Array.isArray(rainfallData) || rainfallData.length === 0) {
    return { latest: '-', total: '-', wettest: '-', rainyDays: '-' };
  }
  
  const valid = rainfallData.filter(d => d.precipitation !== null && d.precipitation !== undefined && !Number.isNaN(d.precipitation));
  if (valid.length === 0) {
    return { latest: '-', total: '-', wettest: '-', rainyDays: '-' };
  }
  
  const latest = valid[0];
  const values = valid.map(d => d.precipitation);
  const total = values.reduce((a, b) => a + b, 0);
  const wettest = Math.max(...values);
  const rainyDays = values.filter(v => v >= 1.0).length;
  
  return {
    latest: `${latest.precipitation.toFixed(1)} mm`,
    total: `${total.toFixed(1)} mm`,
    wettest: `${wettest.toFixed(1)} mm`,
    rainyDays: `${rainyDays}`,
  };
}

export async function fetchWQIData(datasetId, location, startDate, endDate) {
  const params = new URLSearchParams();
  if (location) params.append('location', location);
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  params.append('limit', '1000');
  
  const res = await authFetch(`${API_BASE}/analytics/wqi/${datasetId}?${params}`);
  if (!res.ok) throw new Error('Failed to fetch WQI data');
  return res.json();
}

export async function fetchWQISummary(datasetId, location, startDate, endDate) {
  const params = new URLSearchParams();
  if (location) params.append('location', location);
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  
  const res = await authFetch(`${API_BASE}/analytics/wqi/${datasetId}/summary?${params}`);
  if (!res.ok) throw new Error('Failed to fetch WQI summary');
  return res.json();
}

export async function fetchWQITrend(datasetId, location, startDate, endDate) {
  const params = new URLSearchParams();
  params.append('location', location);
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);

  const res = await authFetch(`${API_BASE}/analytics/wqi/${datasetId}/trend?${params}`);
  if (!res.ok) throw new Error('Failed to fetch WQI trend');
  return res.json();
}

// Notifications API
export async function fetchNotifications(params = {}) {
  const searchParams = new URLSearchParams();
  if (params.unread_only) searchParams.set('unread_only', 'true');
  if (params.cursor) searchParams.set('cursor', params.cursor);
  if (params.limit) searchParams.set('limit', params.limit.toString());
  
  const res = await authFetch(`${API_BASE}/notifications?${searchParams}`);
  if (!res.ok) throw new Error('Failed to fetch notifications');
  return res.json();
}

export async function fetchUnreadCount() {
  const res = await authFetch(`${API_BASE}/notifications/unread-count`);
  if (!res.ok) throw new Error('Failed to fetch unread count');
  return res.json();
}

export async function markNotificationRead(notificationId) {
  const res = await authFetch(`${API_BASE}/notifications/${notificationId}/read`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to mark notification as read');
  return res.json();
}

export async function markAllNotificationsRead() {
  const res = await authFetch(`${API_BASE}/notifications/read-all`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to mark all notifications as read');
  return res.json();
}

export async function deleteNotification(notificationId) {
  const res = await authFetch(`${API_BASE}/notifications/${notificationId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to delete notification');
  return res.json();
}

export async function fetchNotificationPreferences() {
  const res = await authFetch(`${API_BASE}/notifications/preferences`);
  if (!res.ok) throw new Error('Failed to fetch notification preferences');
  return res.json();
}

export async function updateNotificationPreferences(updates) {
  const res = await authFetch(`${API_BASE}/notifications/preferences`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error('Failed to update notification preferences');
  return res.json();
}
