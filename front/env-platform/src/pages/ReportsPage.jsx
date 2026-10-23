import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, Archive, CheckCircle2, FileSpreadsheet, FileText, Loader2 } from 'lucide-react';

import {
  datasetDisplayLabel,
  downloadReportJob,
  exportReport,
  fetchDatasets,
  fetchReportJob,
  previewReport,
} from '../lib/api';

const DATA_TYPES = [
  { key: 'water_quality', label: 'Water quality', hint: 'WQI, DO, pH, BOD and ions' },
  { key: 'air_quality', label: 'Air quality', hint: 'AQI and criteria pollutants' },
  { key: 'temperature', label: 'Temperature', hint: 'Mean, minimum and maximum' },
  { key: 'rainfall', label: 'Rainfall', hint: 'Daily precipitation totals' },
];

const TYPE_ALIASES = {
  air_quality: ['air_quality'],
  water_quality: ['water_quality'],
  temperature: ['temperature', 'rainfall'],
  rainfall: ['temperature', 'rainfall'],
};

const FORMATS = {
  xlsx: {
    label: 'Excel report',
    hint: 'Analyst workbook: overview, station summary, monthly aggregates, anomalies, outlooks',
    icon: FileSpreadsheet,
  },
  pdf: {
    label: 'PDF report',
    hint: 'Presentation-ready document with the same sections',
    icon: FileText,
  },
  csv: {
    label: 'Raw data (CSV)',
    hint: 'Every cleaned record, one file per dataset plus a manifest',
    icon: Archive,
  },
};

const capabilitiesOf = (dataset) => {
  if (Array.isArray(dataset.capabilities) && dataset.capabilities.length > 0) {
    return dataset.capabilities;
  }
  return TYPE_ALIASES[dataset.dataset_type] || [dataset.dataset_type].filter(Boolean);
};

const isoDate = (value) => (value ? String(value).slice(0, 10) : '');

const shiftDays = (value, days) => {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

const ReportsPage = () => {
  const [datasets, setDatasets] = useState([]);
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [types, setTypes] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [range, setRange] = useState({ from: '', to: '' });
  const [datesTouched, setDatesTouched] = useState(false);
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [format, setFormat] = useState('xlsx');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);
  const pollTimer = useRef(null);

  const compatible = datasets.filter((dataset) =>
    capabilitiesOf(dataset).some((capability) => types.includes(capability)),
  );

  useEffect(() => {
    let cancelled = false;

    fetchDatasets()
      .then((items) => {
        if (cancelled) return;
        const completed = items.filter((dataset) => dataset.status === 'completed');
        const available = DATA_TYPES
          .filter((type) => completed.some((dataset) => capabilitiesOf(dataset).includes(type.key)))
          .map((type) => type.key);
        setDatasets(completed);
        setTypes(available);
        setSelectedIds(
          completed
            .filter((dataset) => capabilitiesOf(dataset).some((capability) => available.includes(capability)))
            .map((dataset) => dataset.id),
        );
      })
      .catch((error) => {
        if (!cancelled) setStatus({ type: 'error', text: error.message || 'Failed to load datasets' });
      })
      .finally(() => {
        if (!cancelled) setDatasetsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (datasetsLoading) return undefined;
    if (selectedIds.length === 0) {
      setPreview(null);
      return undefined;
    }

    let cancelled = false;
    setPreviewing(true);
    const timer = setTimeout(async () => {
      try {
        const data = await previewReport({
          datasetIds: selectedIds,
          dataTypes: types,
          from: range.from,
          to: range.to,
        });
        if (cancelled) return;
        setPreview(data);
        if (!datesTouched && !range.from && !range.to && data.date_bounds?.last) {
          const last = isoDate(data.date_bounds.last);
          setRange({ from: shiftDays(last, -365), to: last });
        }
      } catch (error) {
        if (!cancelled) {
          setPreview(null);
          setStatus({ type: 'error', text: error.message || 'Failed to load report preview' });
        }
      } finally {
        if (!cancelled) setPreviewing(false);
      }
    }, 300);

    return () => {
      cancelled = true;
      setPreviewing(false);
      clearTimeout(timer);
    };
  }, [datasetsLoading, selectedIds, types, range.from, range.to, datesTouched]);

  useEffect(() => () => clearTimeout(pollTimer.current), []);

  const resetDefaultRange = () => {
    setDatesTouched(false);
    setRange({ from: '', to: '' });
  };

  const toggleType = (key) => {
    const next = types.includes(key) ? types.filter((value) => value !== key) : [...types, key];
    setTypes(next);
    const allowed = next.length > 0
      ? datasets
        .filter((dataset) => capabilitiesOf(dataset).some((capability) => next.includes(capability)))
        .map((dataset) => dataset.id)
      : [];
    const kept = selectedIds.filter((id) => allowed.includes(id));
    setSelectedIds(kept.length > 0 ? kept : allowed);
    setStatus(null);
    resetDefaultRange();
  };

  const toggleDataset = (id) => {
    setSelectedIds((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
    setStatus(null);
    resetDefaultRange();
  };

  const toggleAllDatasets = () => {
    const ids = compatible.map((dataset) => dataset.id);
    setSelectedIds(selectedIds.length === ids.length ? [] : ids);
    setStatus(null);
    resetDefaultRange();
  };

  const updateRange = (patch) => {
    setDatesTouched(true);
    setRange((current) => ({ ...current, ...patch }));
  };

  const useFullHistory = () => {
    setDatesTouched(true);
    setRange({ from: '', to: '' });
  };

  const pollJob = (jobId) => {
    const tick = async () => {
      try {
        const state = await fetchReportJob(jobId);
        if (state.status === 'completed') {
          const file = await downloadReportJob(jobId, format);
          saveBlob(file.blob, file.filename);
          setStatus({ type: 'success', text: `Downloaded ${file.filename}.` });
          setBusy(false);
          return;
        }
        if (state.status === 'failed') {
          setStatus({ type: 'error', text: state.error || 'Report generation failed.' });
          setBusy(false);
          return;
        }
        pollTimer.current = setTimeout(tick, 1500);
      } catch (error) {
        setStatus({ type: 'error', text: error.message || 'Report generation failed.' });
        setBusy(false);
      }
    };
    tick();
  };

  const handleExport = async () => {
    setStatus(null);
    setBusy(true);
    try {
      const result = await exportReport({
        datasetIds: selectedIds,
        dataTypes: types,
        from: range.from,
        to: range.to,
        format,
      });
      if (result.job) {
        setStatus({
          type: 'success',
          text: `Large selection (${preview?.totals?.row_count?.toLocaleString() || 'many'} records). Preparing your report in the background.`,
        });
        pollJob(result.job.job_id);
        return;
      }
      saveBlob(result.blob, result.filename);
      setStatus({ type: 'success', text: `Downloaded ${result.filename}.` });
      setBusy(false);
    } catch (error) {
      const retry = error.retryAfter
        ? ` Try again in about ${Math.max(1, Math.ceil(error.retryAfter / 60))} min.`
        : '';
      setStatus({ type: 'error', text: `${error.message || 'Export failed'}${retry}` });
      setBusy(false);
    }
  };

  const totals = preview?.totals;
  const nothingMatches = Boolean(totals) && totals.row_count === 0;
  const canExport = !busy && !previewing && selectedIds.length > 0 && Boolean(totals) && !nothingMatches;
  const bounds = preview?.date_bounds;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Generate Reports</h1>
        <p className="text-slate-600 mt-1">
          Export a consistent report package combining overview, station summaries, monthly aggregates,
          anomalies, outlooks and data-quality notes from the datasets you select.
        </p>
      </div>

      <div className="glass-panel rounded-2xl overflow-hidden animate-fade-in-up">
        <div className="p-6 space-y-8">
          <div>
            <h3 className="text-lg font-medium text-slate-800 mb-1">1. Data types</h3>
            <p className="text-xs text-slate-500 mb-3">Pick what the report should contain; the dataset list below narrows to matching files.</p>
            {datasetsLoading ? (
              <p className="text-sm text-slate-500">Loading data types…</p>
            ) : DATA_TYPES.every((type) => !datasets.some((dataset) => capabilitiesOf(dataset).includes(type.key))) ? (
              <p className="text-sm text-slate-500">No completed datasets yet — upload data first.</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {DATA_TYPES.filter((type) => datasets.some((dataset) => capabilitiesOf(dataset).includes(type.key))).map((type) => (
                  <label
                    key={type.key}
                    className={`flex items-start gap-3 p-3 border rounded-md cursor-pointer transition-colors ${types.includes(type.key) ? 'border-blue-400 bg-blue-50/50' : 'border-slate-200 hover:bg-slate-50'}`}
                  >
                    <input
                      type="checkbox"
                      checked={types.includes(type.key)}
                      onChange={() => toggleType(type.key)}
                      className="mt-1 h-4 w-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500"
                    />
                    <span>
                      <span className="block font-medium text-slate-700">{type.label}</span>
                      <span className="block text-xs text-slate-500 mt-0.5">{type.hint}</span>
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-lg font-medium text-slate-800">2. Datasets</h3>
              {compatible.length > 0 && (
                <button
                  type="button"
                  onClick={toggleAllDatasets}
                  className="text-xs font-medium text-blue-600 hover:text-blue-800"
                >
                  {selectedIds.length === compatible.length ? 'Clear all' : 'Select all'}
                </button>
              )}
            </div>
            <p className="text-xs text-slate-500 mb-3">Only datasets with a selected data type are listed.</p>
            {compatible.length === 0 ? (
              <p className="text-sm text-slate-500">
                {types.length === 0
                  ? 'Select at least one data type.'
                  : 'No datasets match the selected data types.'}
              </p>
            ) : (
              <div className="divide-y divide-slate-200 border border-slate-200 rounded-md bg-white">
                {compatible.map((dataset) => (
                  <label key={dataset.id} className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-slate-50">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(dataset.id)}
                      onChange={() => toggleDataset(dataset.id)}
                      className="h-4 w-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500"
                    />
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm font-medium text-slate-700 truncate">
                        {datasetDisplayLabel(dataset)}
                      </span>
                      <span className="block text-xs text-slate-500">
                        {capabilitiesOf(dataset).map((capability) => capability.replace('_', ' ')).join(' · ')}
                      </span>
                    </span>
                    <span className="text-xs text-slate-500 whitespace-nowrap">
                      {Number(dataset.row_count || 0).toLocaleString()} rows
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>

          <div>
            <h3 className="text-lg font-medium text-slate-800 mb-3">3. Date range</h3>
            <div className="flex flex-col sm:flex-row sm:items-end gap-4">
              <div className="w-full sm:w-auto">
                <label className="block text-sm text-slate-500 mb-1">From</label>
                <input
                  type="date"
                  value={range.from}
                  min={isoDate(bounds?.first)}
                  max={range.to || isoDate(bounds?.last)}
                  onChange={(event) => updateRange({ from: event.target.value })}
                  className="w-full border border-slate-300 rounded-md p-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
                />
              </div>
              <div className="w-full sm:w-auto">
                <label className="block text-sm text-slate-500 mb-1">To</label>
                <input
                  type="date"
                  value={range.to}
                  min={range.from || isoDate(bounds?.first)}
                  max={isoDate(bounds?.last)}
                  onChange={(event) => updateRange({ to: event.target.value })}
                  className="w-full border border-slate-300 rounded-md p-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
                />
              </div>
              <button
                type="button"
                onClick={useFullHistory}
                className="text-xs font-medium text-blue-600 hover:text-blue-800 pb-2"
              >
                Use full history
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              Defaults to the latest 365 days of the selected data, matching the dashboards. The range filters
              summary and anomaly queries by record timestamp; outlooks always reflect each station's latest data.
            </p>
          </div>

          <div>
            <h3 className="text-lg font-medium text-slate-800 mb-3">4. Format</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {Object.entries(FORMATS).map(([key, meta]) => {
                const Icon = meta.icon;
                return (
                  <label
                    key={key}
                    className={`flex items-start gap-3 p-3 border rounded-md cursor-pointer transition-colors ${format === key ? 'border-blue-500 bg-blue-50/60' : 'border-slate-200 hover:bg-slate-50'}`}
                  >
                    <input
                      type="radio"
                      name="report-format"
                      checked={format === key}
                      onChange={() => setFormat(key)}
                      className="mt-1 h-4 w-4 text-blue-600 border-slate-300 focus:ring-blue-500"
                    />
                    <span>
                      <span className="flex items-center gap-1.5 font-medium text-slate-700">
                        <Icon className="w-4 h-4" />
                        {meta.label}
                      </span>
                      <span className="block text-xs text-slate-500 mt-0.5">{meta.hint}</span>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white/60 px-3 py-2 text-sm text-slate-600">
            {selectedIds.length === 0 ? (
              'Select at least one dataset to see record counts.'
            ) : !preview ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> Checking selection…
              </span>
            ) : (
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="font-medium text-slate-700">{totals.dataset_count}</span> datasets
                  <span className="text-slate-400">·</span>
                  <span className="font-medium text-slate-700">{totals.station_count}</span> stations
                  <span className="text-slate-400">·</span>
                  <span className="font-medium text-slate-700">{totals.row_count.toLocaleString()}</span> records
                  {previewing && <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />}
                </div>
                {preview.selected.some((row) => row.row_count === 0) && (
                  <p className="text-xs text-amber-700">
                    No data in this date range for{' '}
                    {[...new Set(preview.selected.filter((row) => row.row_count === 0).map((row) => row.dataset_name))].join(', ')}.
                  </p>
                )}
                {nothingMatches && (
                  <p className="text-xs text-red-600">Nothing matches — adjust the datasets or date range before exporting.</p>
                )}
                {preview.warnings?.map((warning) => (
                  <p key={warning} className="text-xs text-amber-700">{warning}</p>
                ))}
              </div>
            )}
          </div>

          {status && (
            <div className={`flex items-start gap-2 rounded-lg px-3 py-2 text-sm border ${status.type === 'success' ? 'bg-green-50 border-green-200 text-green-700' : 'bg-red-50 border-red-200 text-red-700'}`}>
              {status.type === 'success'
                ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
                : <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />}
              <span>{status.text}</span>
            </div>
          )}
        </div>

        <div className="bg-white/30 backdrop-blur-md px-6 py-4 border-t border-white/40 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            Exports are limited to 10 per hour. Large selections are prepared in the background.
          </p>
          <button
            onClick={handleExport}
            disabled={!canExport}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Archive className="w-4 h-4" />
            )}
            {busy ? 'Preparing report…' : format === 'csv' ? 'Download CSV archive' : `Download ${FORMATS[format].label}`}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ReportsPage;
