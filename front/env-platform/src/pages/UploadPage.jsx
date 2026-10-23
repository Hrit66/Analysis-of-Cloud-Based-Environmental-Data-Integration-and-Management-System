import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import FileDropzone from '../components/upload/FileDropzone';
import ProcessingProgress from '../components/upload/ProcessingProgress';
import { AlertCircle, CloudRain, Droplets, FileText } from 'lucide-react';
import {
  cancelDatasetJob,
  fetchDataset,
  fetchDatasetJob,
  fetchMyQuota,
  getDatasetStatus,
  uploadDataset,
  uploadIMDFiles,
  uploadRiverSummaryFiles,
} from '../lib/api';
import { isTerminalStatus, pollDelay } from '../lib/progress';

const typeMap = {
  'AQI': 'air_quality',
  'WQI': 'water_quality',
  'TEMP': 'temperature',
  'RAIN': 'rainfall',
};

const routeMap = {
  'air_quality': 'aqi',
  'water_quality': 'wqi',
  'temperature': 'temperature',
  'rainfall': 'rainfall',
};

const typeForDataset = {
  air_quality: 'AQI',
  water_quality: 'WQI',
  temperature: 'TEMP',
  rainfall: 'RAIN',
};

const STORAGE_KEY = 'envplatform.upload.job';
const DEFAULT_MAX_BYTES = 25 * 1024 * 1024;

const readStoredState = () => {
  try {
    return JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || 'null');
  } catch {
    return null;
  }
};

const storeState = (value) => {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Session storage can be unavailable in private-mode browsers.
  }
};

const clearStoredState = () => {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage errors.
  }
};

const storeTerminalState = (status, payload = {}) => {
  const stored = readStoredState();
  if (!stored) return;
  const next = {
    ...stored,
    phase: status,
    job_id: payload.job_id || stored.job_id,
    dataset_id: payload.dataset_id || stored.dataset_id,
    dataset_type: payload.dataset_type || stored.dataset_type,
  };
  if (status === 'completed') {
    next.duplicate = Boolean(payload.result?.duplicate ?? stored.duplicate);
    next.result = payload.result || stored.result || null;
    delete next.error;
  } else {
    next.error = payload.error_message
      || (status === 'cancelled' ? 'Processing cancelled' : 'Processing failed');
  }
  storeState(next);
};

const reportReadiness = (datasetType, skipReasons) => {
  const isWater = datasetType === 'water_quality';
  const unavailable = isWater ? 'Water outlook not available' : 'Daily forecast not available';
  if (!Array.isArray(skipReasons)) return `${unavailable}: not enough history yet`;
  if (skipReasons.length === 0) {
    return isWater ? 'Monthly water outlook ready' : 'Daily forecast ready';
  }
  const reason = skipReasons[0]?.reason;
  return `${unavailable}: ${reason || 'not enough history yet'}`;
};

const ModeTabs = ({ mode, onChange, disabled }) => (
  <div className="grid grid-cols-3 gap-2">
    <button
      type="button"
      onClick={() => onChange('standard')}
      disabled={disabled}
      className={`px-3 py-2 rounded-md text-sm font-medium border transition-colors ${
        mode === 'standard' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-600 border-slate-300 hover:bg-slate-50'
      } ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
    >
      Standard Dataset
    </button>
    <button
      type="button"
      onClick={() => onChange('imd')}
      disabled={disabled}
      className={`px-3 py-2 rounded-md text-sm font-medium border transition-colors flex items-center justify-center gap-2 ${
        mode === 'imd' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-600 border-slate-300 hover:bg-slate-50'
      } ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
    >
      <CloudRain className="w-4 h-4" /> IMD Weather Files
    </button>
    <button
      type="button"
      onClick={() => onChange('river')}
      disabled={disabled}
      className={`px-3 py-2 rounded-md text-sm font-medium border transition-colors flex items-center justify-center gap-2 ${
        mode === 'river' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-600 border-slate-300 hover:bg-slate-50'
      } ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
    >
      <Droplets className="w-4 h-4" /> River Year Summary
    </button>
  </div>
);

const DataNatureSelect = ({ value, onChange, disabled }) => (
  <div>
    <label className="block text-sm font-medium text-slate-700 mb-2">
      Data nature <span className="text-slate-400 font-normal">(optional)</span>
    </label>
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      className="w-full border border-slate-300 rounded-md p-2.5 focus:ring-blue-500 focus:border-blue-500 bg-white disabled:bg-slate-100 disabled:text-slate-500"
    >
      <option value="">Not sure</option>
      <option value="real">Real</option>
      <option value="synthetic">Synthetic</option>
      <option value="modelled">Modelled</option>
    </select>
  </div>
);

const UploadPage = () => {
  const [file, setFile] = useState(null);
  const [type, setType] = useState('AQI');
  const [mode, setMode] = useState('standard');
  const [bundleFiles, setBundleFiles] = useState([]);
  const [location, setLocation] = useState('');
  const [dataNature, setDataNature] = useState('');
  const [quota, setQuota] = useState(null);
  const [phase, setPhase] = useState('idle');
  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [startedAt, setStartedAt] = useState(null);
  const [resultType, setResultType] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [duplicate, setDuplicate] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const submittingRef = useRef(false);
  const navigate = useNavigate();

  const isBundle = mode !== 'standard';
  const isBusy = phase === 'uploading' || phase === 'processing';
  const canUpload = isBundle ? bundleFiles.length > 0 : Boolean(file);
  const maxUploadBytes = quota?.max_upload_bytes || quota?.storage_bytes || DEFAULT_MAX_BYTES;
  const limitMb = Math.max(1, Math.round(maxUploadBytes / (1024 * 1024)));

  useEffect(() => {
    fetchMyQuota()
      .then((data) => setQuota(data))
      .catch(() => {});
  }, []);

  const hydrateCompleted = useCallback(async (id, fallbackType) => {
    if (!id) {
      setPhase('failed');
      setError('Could not load the completed dataset.');
      return;
    }
    try {
      const [status, dataset] = await Promise.all([
        getDatasetStatus(id).catch(() => null),
        fetchDataset(id).catch(() => null),
      ]);
      if (status?.status === 'failed') {
        setPhase('failed');
        setError(status.error_message || 'Processing failed');
        return;
      }
      if (!status && !dataset) {
        throw new Error('Dataset not found');
      }
      const report = status?.cleaning_report || dataset?.cleaning_report || null;
      const rowsRead = report?.rows_read ?? dataset?.row_count ?? status?.row_count ?? 0;
      const rowsKept = report?.rows_kept ?? dataset?.row_count ?? status?.row_count ?? 0;
      const resolvedType = dataset?.dataset_type || fallbackType;
      const completedResult = {
        dataset_id: id,
        dataset_type: resolvedType,
        rows_read: rowsRead,
        rows_kept: rowsKept,
        rows_dropped: Math.max(0, Number(rowsRead) - Number(rowsKept)),
        source_tag: dataset?.source_tag || 'real',
        forecast_readiness: reportReadiness(resolvedType, dataset?.forecast_skip_reasons),
        cleaning_report: report,
      };
      setResult(completedResult);
      storeTerminalState('completed', {
        dataset_id: id,
        dataset_type: resolvedType,
        result: completedResult,
      });
      setPhase('completed');
      setError(null);
    } catch {
      storeTerminalState('failed', {
        dataset_id: id,
        error_message: 'Could not load the completed dataset. Check the Datasets page.',
      });
      setPhase('failed');
      setError('Could not load the completed dataset. Check the Datasets page.');
    }
  }, []);

  const applyJob = useCallback((data) => {
    setJob(data);
    if (data.dataset_type) setResultType(data.dataset_type);

    if (data.status === 'completed') {
      storeTerminalState('completed', data);
      setPhase('completed');
      setError(null);
      if (data.result) {
        setResult(data.result);
      } else if (data.dataset_id) {
        hydrateCompleted(data.dataset_id, data.dataset_type);
      }
      return;
    }
    if (data.status === 'failed') {
      storeTerminalState('failed', data);
      setPhase('failed');
      setError(data.error_message || 'Processing failed');
      return;
    }
    if (data.status === 'cancelled') {
      storeTerminalState('cancelled', data);
      setPhase('cancelled');
      setError('Processing cancelled');
    }
  }, [hydrateCompleted]);

  const recoverExpiredJob = useCallback(async () => {
    setJobId(null);
    const stored = readStoredState();
    if (!stored?.dataset_id) {
      setPhase('failed');
      setError('Processing status expired. Check the Datasets page.');
      return;
    }
    try {
      const status = await getDatasetStatus(stored.dataset_id);
      if (status.status === 'completed') {
        await hydrateCompleted(stored.dataset_id, stored.dataset_type);
        return;
      }
      if (status.status === 'failed') {
        setPhase('failed');
        setError(status.error_message || 'Processing failed');
        return;
      }
      setPhase('failed');
      setError('Processing status expired. Check the Datasets page for the latest status.');
    } catch {
      setPhase('failed');
      setError('Could not restore the processing status.');
    }
  }, [hydrateCompleted]);

  useEffect(() => {
    const stored = readStoredState();
    if (!stored) return;
    setMode(stored.mode || 'standard');
    setType(typeForDataset[stored.dataset_type] || 'AQI');
    setResultType(stored.dataset_type || null);
    setStartedAt(stored.started_at || null);
    if (stored.phase === 'completed' || stored.duplicate) {
      setDuplicate(Boolean(stored.duplicate));
      if (stored.result) setResult(stored.result);
      setPhase('completed');
      hydrateCompleted(stored.dataset_id, stored.dataset_type);
    } else if (stored.phase === 'failed' || stored.phase === 'cancelled') {
      setPhase(stored.phase);
      setError(stored.error || (stored.phase === 'cancelled' ? 'Processing cancelled' : 'Processing failed'));
    } else if (stored.job_id) {
      setPhase('processing');
      setJobId(stored.job_id);
    }
  }, [hydrateCompleted]);

  useEffect(() => {
    if (!jobId || phase !== 'processing') return undefined;
    let stopped = false;
    let timer = null;
    let requestSeq = 0;
    const started = Date.now();

    const schedule = (delay) => {
      if (!stopped) timer = window.setTimeout(poll, delay);
    };

    const poll = async () => {
      if (stopped) return;
      const seq = ++requestSeq;
      try {
        const data = await fetchDatasetJob(jobId);
        if (stopped || seq !== requestSeq) return;
        applyJob(data);
        if (isTerminalStatus(data.status)) return;
      } catch (pollError) {
        if (stopped || seq !== requestSeq) return;
        if (pollError?.status === 404) {
          stopped = true;
          await recoverExpiredJob();
          return;
        }
        console.error('Processing progress poll failed:', pollError);
      }
      if (stopped || seq !== requestSeq) return;
      schedule(pollDelay(Date.now() - started));
    };

    const resume = () => {
      window.clearTimeout(timer);
      poll();
    };

    poll();
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('focus', resume);
    window.addEventListener('online', resume);
    window.addEventListener('pageshow', resume);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', resume);
      window.removeEventListener('focus', resume);
      window.removeEventListener('online', resume);
      window.removeEventListener('pageshow', resume);
    };
  }, [jobId, phase, applyJob, recoverExpiredJob]);

  const handleDrop = (uploaded) => {
    if (isBundle) {
      setBundleFiles((previous) => {
        const names = new Set(previous.map((item) => item.name));
        return [...previous, ...uploaded.filter((item) => !names.has(item.name))];
      });
    } else {
      setFile(uploaded);
    }
    setError(null);
  };

  const removeBundleFile = (name) => {
    setBundleFiles((previous) => previous.filter((item) => item.name !== name));
  };

  const switchMode = (nextMode) => {
    setMode(nextMode);
    setFile(null);
    setBundleFiles([]);
    setError(null);
  };

  const resetForm = () => {
    clearStoredState();
    setMode('standard');
    setType('AQI');
    setFile(null);
    setBundleFiles([]);
    setLocation('');
    setDataNature('');
    setPhase('idle');
    setJobId(null);
    setJob(null);
    setUploadPercent(0);
    setStartedAt(null);
    setResultType(null);
    setResult(null);
    setError(null);
    setDuplicate(false);
    setCancelling(false);
  };

  const resetFileOnly = () => {
    clearStoredState();
    setFile(null);
    setBundleFiles([]);
    setPhase('idle');
    setJobId(null);
    setJob(null);
    setUploadPercent(0);
    setStartedAt(null);
    setResultType(null);
    setResult(null);
    setError(null);
    setDuplicate(false);
    setCancelling(false);
  };

  const handleUpload = async () => {
    if (submittingRef.current || isBusy || !canUpload) return;
    submittingRef.current = true;
    const now = new Date().toISOString();
    setPhase('uploading');
    setJob(null);
    setJobId(null);
    setUploadPercent(0);
    setStartedAt(now);
    setResultType(null);
    setResult(null);
    setError(null);
    setDuplicate(false);
    setCancelling(false);

    const options = {
      sourceTag: dataNature || undefined,
      onUploadProgress: (fraction) => setUploadPercent(Math.round(fraction * 10)),
    };

    try {
      let response;
      if (isBundle) {
        response = mode === 'river'
          ? await uploadRiverSummaryFiles(bundleFiles, location.trim() || undefined, options)
          : await uploadIMDFiles(bundleFiles, location.trim() || undefined, options);
      } else {
        response = await uploadDataset(file, typeMap[type], options);
      }

      const resolvedType = response.dataset_type || (
        mode === 'river' ? 'water_quality' : typeMap[type]
      );
      setResultType(resolvedType);

      const stored = {
        job_id: response.job_id || null,
        dataset_id: response.dataset_id,
        dataset_type: resolvedType,
        mode,
        started_at: now,
        file_count: isBundle ? bundleFiles.length : 1,
      };

      if (response.duplicate || !response.job_id) {
        setDuplicate(true);
        storeState({ ...stored, phase: 'completed', duplicate: true });
        await hydrateCompleted(response.dataset_id, resolvedType);
        return;
      }

      storeState(stored);
      setJobId(response.job_id);
      setJob({
        job_id: response.job_id,
        dataset_id: response.dataset_id,
        status: 'processing',
        stage_key: 'reading_file',
        stage_label: 'Reading file',
        percent: 10,
        counts: { rows_read: 0, rows_kept: 0, rows_dropped: 0 },
      });
      setPhase('processing');
    } catch (uploadError) {
      clearStoredState();
      setPhase('failed');
      setError(uploadError.message || 'Upload failed');
    } finally {
      submittingRef.current = false;
    }
  };

  const handleCancel = async () => {
    if (!jobId || cancelling) return;
    setCancelling(true);
    try {
      const data = await cancelDatasetJob(jobId);
      applyJob(data);
    } catch (cancelError) {
      console.error('Failed to cancel processing:', cancelError);
    } finally {
      setCancelling(false);
    }
  };

  const handleRetry = () => {
    if (canUpload) {
      handleUpload();
    } else {
      resetFileOnly();
    }
  };

  const handleOpenDashboard = () => {
    const resolved = resultType || result?.dataset_type || typeMap[type];
    navigate(`/${routeMap[resolved] || 'aqi'}`);
  };

  const processingDatasetType = resultType || typeMap[type];
  const progressProps = {
    phase,
    job,
    uploadPercent,
    startedAt,
    mode,
    datasetType: processingDatasetType,
    fileCount: isBundle ? bundleFiles.length : 1,
    error,
    result,
    duplicate,
    cancelling,
    onCancel: jobId ? handleCancel : undefined,
    onUploadAnother: resetForm,
    onRetry: handleRetry,
    onChooseFile: resetFileOnly,
    onOpenDashboard: handleOpenDashboard,
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Upload Dataset</h1>
        <p className="text-slate-600 mt-1">Upload environmental data for analysis and prediction.</p>
      </div>

      <div className="glass-panel p-8 rounded-2xl space-y-6 animate-fade-in-up">
        {phase === 'idle' && (
          <>
            <ModeTabs mode={mode} onChange={switchMode} />

            {mode === 'standard' ? (
              <>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Dataset Type</label>
                  <select
                    value={type}
                    onChange={(event) => setType(event.target.value)}
                    className="w-full border border-slate-300 rounded-md p-2.5 focus:ring-blue-500 focus:border-blue-500 bg-white"
                  >
                    <option value="AQI">Air Quality (AQI)</option>
                    <option value="WQI">Water Quality (WQI)</option>
                    <option value="TEMP">Temperature</option>
                    <option value="RAIN">Rainfall</option>
                  </select>
                </div>

                <DataNatureSelect value={dataNature} onChange={setDataNature} />

                {!file ? (
                  <FileDropzone
                    onDrop={handleDrop}
                    maxSize={maxUploadBytes}
                    hint={null}
                  />
                ) : (
                  <div className="border border-white/50 rounded-xl p-4 flex items-center justify-between bg-white/40 backdrop-blur-sm">
                    <div className="flex items-center gap-3">
                      <FileText className="text-blue-500 w-8 h-8" />
                      <div>
                        <p className="font-medium text-slate-800">{file.name}</p>
                        <p className="text-xs text-slate-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setFile(null)}
                      className="text-sm text-red-600 hover:text-red-700 font-medium"
                    >
                      Remove
                    </button>
                  </div>
                )}

                <p className="text-xs text-slate-500">
                  CSV, XLSX, XLS or JSON, max {limitMb} MB
                </p>
              </>
            ) : (
              <>
                {mode === 'imd' ? (
                  <div className="flex items-start gap-2 text-sm text-slate-600 bg-blue-50/60 border border-blue-100 rounded-lg p-3">
                    <CloudRain className="w-4 h-4 text-blue-500 mt-0.5 shrink-0" />
                    <span>
                      IMD publishes rainfall and temperature grids without a real-time API, so its daily files are
                      imported here. Rain, tmax and tmin files are merged on date automatically; the daily mean
                      temperature is derived as (tmin + tmax) / 2.
                    </span>
                  </div>
                ) : (
                  <div className="flex items-start gap-2 text-sm text-slate-600 bg-cyan-50/60 border border-cyan-100 rounded-lg p-3">
                    <Droplets className="w-4 h-4 text-cyan-600 mt-0.5 shrink-0" />
                    <span>
                      CPCB annual river reports publish one row per river and year ("Name of the River", "Year",
                      pH, DO, BOD…). Upload the summary sheet here — each river-year becomes a July 1 water-quality
                      record and the WQI is computed per record.
                    </span>
                  </div>
                )}

                <FileDropzone
                  onDrop={handleDrop}
                  multiple
                  maxSize={maxUploadBytes}
                  hint={null}
                />

                {bundleFiles.length > 0 && (
                  <div className="space-y-2">
                    {bundleFiles.map((item) => (
                      <div key={item.name} className="border border-white/50 rounded-xl p-3 flex items-center justify-between bg-white/40 backdrop-blur-sm">
                        <div className="flex items-center gap-3">
                          <FileText className="text-blue-500 w-6 h-6" />
                          <div>
                            <p className="font-medium text-slate-800 text-sm">{item.name}</p>
                            <p className="text-xs text-slate-500">{(item.size / 1024 / 1024).toFixed(2)} MB</p>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeBundleFile(item.name)}
                          className="text-sm text-red-600 hover:text-red-700 font-medium"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <p className="text-xs text-slate-500">
                  CSV, XLSX or XLS, max {limitMb} MB each
                </p>

                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">
                    Location <span className="text-slate-400 font-normal">(optional{mode === 'river' ? ' — river names are used by default' : ''})</span>
                  </label>
                  <input
                    value={location}
                    onChange={(event) => setLocation(event.target.value)}
                    placeholder={mode === 'river' ? 'e.g. Tamil Nadu rivers' : 'e.g. Bengaluru'}
                    className="w-full border border-slate-300 rounded-md p-2.5 focus:ring-blue-500 focus:border-blue-500 bg-white"
                  />
                </div>

                <DataNatureSelect value={dataNature} onChange={setDataNature} />
              </>
            )}

            {error && (
              <div className="flex items-center gap-2 text-red-600 bg-red-50 p-3 rounded-lg">
                <AlertCircle className="w-4 h-4" />
                <span className="text-sm">{error}</span>
              </div>
            )}

            <div className="flex justify-end pt-4">
              <button
                type="button"
                onClick={handleUpload}
                disabled={!canUpload}
                className={`px-4 py-2 rounded-md font-medium text-white transition-colors ${
                  canUpload ? 'bg-blue-600 hover:bg-blue-700' : 'bg-slate-300 cursor-not-allowed'
                }`}
              >
                {mode === 'imd' ? 'Merge & Process' : mode === 'river' ? 'Import & Process' : 'Upload & Process'}
              </button>
            </div>
          </>
        )}

        {isBusy && (
          <>
            <ModeTabs mode={mode} onChange={switchMode} disabled />
            {!isBundle && (
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Dataset Type</label>
                <select
                  value={type}
                  disabled
                  className="w-full border border-slate-300 rounded-md p-2.5 bg-slate-100 text-slate-500 cursor-not-allowed"
                >
                  <option value="AQI">Air Quality (AQI)</option>
                  <option value="WQI">Water Quality (WQI)</option>
                  <option value="TEMP">Temperature</option>
                  <option value="RAIN">Rainfall</option>
                </select>
              </div>
            )}
            <ProcessingProgress {...progressProps} />
          </>
        )}

        {!isBusy && phase !== 'idle' && <ProcessingProgress {...progressProps} />}
      </div>
    </div>
  );
};

export default UploadPage;
