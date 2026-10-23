export const TERMINAL_JOB_STATUSES = new Set(['completed', 'failed', 'cancelled']);

const BASE_STAGES = [
  { key: 'uploading', label: 'Uploading' },
  { key: 'reading_file', label: 'Reading file' },
  { key: 'detecting_type', label: 'Detecting type' },
  { key: 'removing_duplicate_headers', label: 'Removing duplicate headers and empty columns' },
  { key: 'converting_missing_values', label: 'Converting missing-value markers' },
  { key: 'checking_ranges', label: 'Checking plausible ranges' },
  { key: 'removing_duplicate_station_dates', label: 'Removing duplicate station-dates' },
  { key: 'normalizing_timestamps', label: 'Normalizing timestamps' },
  { key: 'calculating_index', label: 'Calculating AQI/WQI' },
  { key: 'saving', label: 'Saving' },
  { key: 'checking_forecast', label: 'Checking forecast readiness' },
  { key: 'done', label: 'Done' },
];

const MERGING_STAGE = { key: 'merging_files', label: 'Merging files' };

const clampPercent = (value) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(100, Math.round(numeric)));
};

export function isTerminalStatus(status) {
  return TERMINAL_JOB_STATUSES.has(status);
}

export function stagesForMode(mode, datasetType) {
  const stages = BASE_STAGES.map((stage) => ({ ...stage }));
  if (mode === 'imd') {
    stages.splice(2, 0, { ...MERGING_STAGE });
  }
  if (datasetType === 'water_quality') {
    const item = stages.find((stage) => stage.key === 'calculating_index');
    if (item) item.label = 'Calculating WQI';
  } else if (datasetType === 'temperature' || datasetType === 'rainfall') {
    const item = stages.find((stage) => stage.key === 'calculating_index');
    if (item) item.label = 'Calculating derived values';
  }
  return stages;
}

export function stageStates(stages, currentKey, status) {
  const currentIndex = stages.findIndex((stage) => stage.key === currentKey);
  return stages.map((stage, index) => {
    if (status === 'completed') return 'done';
    if (currentIndex === -1) return 'pending';
    if (index < currentIndex) return 'done';
    if (index === currentIndex) {
      return status === 'failed' || status === 'cancelled' ? 'failed' : 'active';
    }
    return 'pending';
  });
}

export function nextBarPercent(previous, { phase, status, percent, uploadPercent }) {
  const before = clampPercent(previous);
  let target = 0;
  if (phase === 'completed' || status === 'completed') {
    target = 100;
  } else if (phase === 'uploading') {
    target = Math.min(10, clampPercent(uploadPercent));
  } else {
    target = Math.min(99, clampPercent(percent ?? 10));
  }
  return Math.max(before, target);
}

export function pollDelay(elapsedMs) {
  return Number(elapsedMs) > 30_000 ? 2_500 : 1_000;
}

export function formatElapsed(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }
  return `${minutes}:${String(secs).padStart(2, '0')}`;
}

export function formatCount(value) {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? numeric.toLocaleString() : '0';
}
