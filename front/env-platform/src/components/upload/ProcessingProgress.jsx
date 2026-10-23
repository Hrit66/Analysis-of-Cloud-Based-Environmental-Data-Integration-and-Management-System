import React, { useEffect, useRef, useState } from 'react';
import {
  Activity,
  AlertCircle,
  Check,
  CheckCircle2,
  ExternalLink,
  FileSearch,
  RotateCcw,
  Upload,
  X,
} from 'lucide-react';
import {
  formatCount,
  formatElapsed,
  nextBarPercent,
  stageStates,
  stagesForMode,
} from '../../lib/progress';
import './ProcessingProgress.css';

const SOURCE_LABELS = {
  real: 'Real',
  synthetic: 'Synthetic',
  modelled: 'Modelled',
};

const stageLabelFor = (job, phase) => {
  if (phase === 'uploading') return 'Uploading';
  if (job?.stage_label) return job.stage_label;
  if (job?.status === 'completed') return 'Done';
  return 'Preparing processing';
};

const stageKeyFor = (job, phase) => {
  if (phase === 'uploading') return 'uploading';
  if (job?.status === 'completed') return 'done';
  return job?.stage_key || 'reading_file';
};

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => (
    typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  ));

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(query.matches);
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, []);

  return reduced;
}

function useDelayedLoader(active, delay = 300, minimum = 600) {
  const [visible, setVisible] = useState(false);
  const shownAt = useRef(0);

  useEffect(() => {
    let timer;
    if (active) {
      if (!visible) {
        timer = window.setTimeout(() => {
          shownAt.current = Date.now();
          setVisible(true);
        }, delay);
      }
    } else if (visible) {
      const remaining = Math.max(0, minimum - (Date.now() - shownAt.current));
      timer = window.setTimeout(() => setVisible(false), remaining);
    }
    return () => window.clearTimeout(timer);
  }, [active, delay, minimum, visible]);

  return visible;
}

function ProgressLoader({ reduced, percent = 0 }) {
  if (reduced) {
    return (
      <div
        className="processing-loader processing-loader--static"
        style={{ '--pp-progress': percent }}
        aria-hidden="true"
      >
        <Activity className="h-14 w-14" strokeWidth={1.6} />
      </div>
    );
  }

  return (
    <svg
      className="processing-loader"
      style={{ '--pp-progress': percent }}
      viewBox="0 0 160 160"
      fill="none"
      aria-hidden="true"
    >
      <g className="processing-loader__swing">
        <path className="processing-loader__tentacle" d="M54 99c-8 11-15 17-23 24" />
        <path className="processing-loader__tentacle" d="M70 104c-5 12-9 20-13 28" />
        <path className="processing-loader__tentacle" d="M90 104c5 12 9 20 13 28" />
        <path className="processing-loader__tentacle" d="M106 99c8 11 15 17 23 24" />
      </g>
      <g className="processing-loader__bob">
        <ellipse cx="80" cy="68" rx="38" ry="35" fill="var(--pp-primary)" />
        <ellipse cx="80" cy="88" rx="26" ry="20" fill="var(--pp-primary-deep)" opacity="0.9" />
        <circle cx="66" cy="64" r="8" fill="#ffffff" />
        <circle cx="94" cy="64" r="8" fill="#ffffff" />
        <circle cx="68" cy="66" r="3.4" fill="var(--pp-text)" />
        <circle cx="92" cy="66" r="3.4" fill="var(--pp-text)" />
        <path
          d="M72 82c4 4 12 4 16 0"
          stroke="#ffffff"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <circle className="processing-loader__bubble" cx="123" cy="35" r="5" />
        <circle className="processing-loader__bubble" cx="134" cy="51" r="3" style={{ animationDelay: '-0.6s' }} />
      </g>
    </svg>
  );
}

const sumValues = (value) => (
  Object.values(value || {}).reduce((total, item) => total + Number(item || 0), 0)
);

function CleaningReport({ report }) {
  if (!report) return null;
  const rows = [
    ['Rows read', formatCount(report.rows_read)],
    ['Rows kept', formatCount(report.rows_kept)],
    ['Invalid timestamps removed', formatCount(report.rows_dropped?.invalid_timestamp)],
    ['Duplicate station-dates removed', formatCount(report.duplicates_removed)],
    ['Missing-value markers', formatCount(sumValues(report.missing_markers_found))],
    ['Sentinel values cleared', formatCount(sumValues(report.sentinel_values_detected))],
    ['Out-of-range values cleared', formatCount(sumValues(report.out_of_range_values_set_to_nan))],
    ['Columns renamed', formatCount(Object.keys(report.columns_renamed || {}).length)],
    ['Ambiguous dates parsed', formatCount(report.ambiguous_date_strings)],
  ];

  return (
    <div>
      <div className="mb-4">
        <h4 className="text-sm font-semibold text-slate-800">Cleaning report</h4>
        <p className="mt-1 text-xs text-slate-500">
          What the cleaner changed while importing this dataset.
        </p>
      </div>
      <div>
        {rows.map(([label, value]) => (
          <div key={label} className="processing-progress__report-row">
            <span className="text-slate-500">{label}</span>
            <span className="font-medium text-slate-800">{value}</span>
          </div>
        ))}
      </div>
      <details className="mt-4 rounded-lg bg-slate-50 p-3">
        <summary className="cursor-pointer text-xs font-medium text-slate-600">
          Raw cleaning report
        </summary>
        <pre className="mt-2 max-h-52 overflow-auto text-[11px] leading-relaxed text-slate-600">
          {JSON.stringify(report, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function ReportModal({ report, onClose }) {
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  if (!report) return null;

  return (
    <div
      className="processing-progress__report-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="processing-progress__report p-6"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cleaning-report-title"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h3 id="cleaning-report-title" className="text-lg font-bold text-slate-800">
            Cleaning report
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close cleaning report"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <CleaningReport report={report} />
      </div>
    </div>
  );
}

const Counter = ({ label, value }) => (
  <div className="rounded-lg bg-white/55 px-3 py-2 text-center">
    <dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</dt>
    <dd className="mt-0.5 text-sm font-semibold text-slate-800">{value}</dd>
  </div>
);

const ProcessingProgress = ({
  phase,
  job,
  uploadPercent = 0,
  startedAt,
  mode = 'standard',
  datasetType,
  fileCount = 1,
  error,
  result,
  duplicate = false,
  cancelling = false,
  onCancel,
  onUploadAnother,
  onRetry,
  onChooseFile,
  onOpenDashboard,
}) => {
  const [shownPercent, setShownPercent] = useState(0);
  const [reportOpen, setReportOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const reducedMotion = usePrefersReducedMotion();

  const status = job?.status;
  const busy = phase === 'uploading' || phase === 'processing';
  const completed = phase === 'completed';
  const cancelled = phase === 'cancelled';
  const failed = phase === 'failed' || status === 'failed';
  const showLoader = useDelayedLoader(busy);

  useEffect(() => {
    setShownPercent((previous) => nextBarPercent(previous, {
      phase,
      status,
      percent: job?.percent,
      uploadPercent,
    }));
  }, [phase, status, job?.percent, uploadPercent]);

  useEffect(() => {
    if (!busy) return undefined;
    const start = new Date(startedAt || job?.started_at || Date.now()).getTime();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [busy, startedAt, job?.started_at]);

  useEffect(() => {
    if (!busy) setReportOpen(false);
  }, [busy]);

  const stages = stagesForMode(mode, datasetType);
  const currentKey = stageKeyFor(job, phase);
  const states = stageStates(stages, currentKey, completed ? 'completed' : status);
  const counts = job?.counts || {};
  const completedResult = result || job?.result || {};
  const cleaningReport = completedResult.cleaning_report || job?.result?.cleaning_report;
  const stageLabel = stageLabelFor(job, phase);

  const counters = completed
    ? {
        rows_read: completedResult.rows_read ?? cleaningReport?.rows_read ?? 0,
        rows_kept: completedResult.rows_kept ?? cleaningReport?.rows_kept ?? 0,
        rows_dropped: completedResult.rows_dropped ?? 0,
      }
    : counts;

  if (completed) {
    const sourceTag = completedResult.source_tag || 'real';
    const forecastReadiness = completedResult.forecast_readiness
      || job?.result?.forecast_readiness
      || 'Forecast readiness unavailable';
    return (
      <div className="processing-progress flex flex-col items-center gap-5 text-center" aria-label="Dataset processing complete">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-green-100 text-green-600">
          <CheckCircle2 className="h-8 w-8" />
        </div>
        <div>
          <h3 className="text-xl font-bold text-slate-800">
            {duplicate ? 'Already uploaded' : 'Dataset ready'}
          </h3>
          <p className="mt-1 max-w-md text-sm text-slate-600">
            {duplicate
              ? 'This exact upload was processed before, so the existing dataset was kept.'
              : 'Your data has been cleaned and is ready to explore.'}
          </p>
        </div>

        <dl className="grid w-full grid-cols-2 gap-2 sm:grid-cols-4">
          <Counter label="Rows read" value={formatCount(counters.rows_read)} />
          <Counter label="Rows kept" value={formatCount(counters.rows_kept)} />
          <Counter label="Rows dropped" value={formatCount(counters.rows_dropped)} />
          <div className="rounded-lg bg-white/55 px-3 py-2 text-center">
            <dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Source</dt>
            <dd className="mt-0.5 text-sm font-semibold text-slate-800">
              {SOURCE_LABELS[sourceTag] || sourceTag}
            </dd>
          </div>
        </dl>

        <p className="max-w-md text-sm text-slate-600">
          <span className="font-medium text-slate-700">Forecast: </span>
          {forecastReadiness}
        </p>

        <div className="flex flex-wrap justify-center gap-2 pt-1">
          <button
            type="button"
            onClick={onOpenDashboard}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <ExternalLink className="h-4 w-4" />
            Open dashboard
          </button>
          {cleaningReport && (
            <button
              type="button"
              onClick={() => setReportOpen(true)}
              className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
            >
              <FileSearch className="h-4 w-4" />
              View cleaning report
            </button>
          )}
          <button
            type="button"
            onClick={onUploadAnother}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
          >
            <Upload className="h-4 w-4" />
            Upload another
          </button>
        </div>

        {reportOpen && (
          <ReportModal report={cleaningReport} onClose={() => setReportOpen(false)} />
        )}
      </div>
    );
  }

  if (failed || cancelled) {
    return (
      <div className="processing-progress flex flex-col items-center gap-4 text-center" aria-label="Dataset processing failed">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-red-100 text-red-600">
          <AlertCircle className="h-8 w-8" />
        </div>
        <h3 className="text-xl font-bold text-red-800">
          {cancelled ? 'Processing cancelled' : 'Processing failed'}
        </h3>
        <div role="alert" className="w-full max-w-md rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-left text-sm text-red-700">
          {cancelled ? 'Processing cancelled' : (error || 'Processing failed')}
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <RotateCcw className="h-4 w-4" />
            Try again
          </button>
          <button
            type="button"
            onClick={onChooseFile}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
          >
            Choose a different file
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="processing-progress flex flex-col items-center gap-5"
      role="status"
      aria-live="polite"
      aria-atomic="false"
      aria-busy={busy}
      aria-label={`Dataset processing: ${stageLabel}`}
    >
      <div className="flex min-h-[128px] items-center justify-center">
        {showLoader ? (
          <ProgressLoader reduced={reducedMotion} percent={shownPercent} />
        ) : (
          <div className="h-32 w-32" aria-hidden="true" />
        )}
      </div>

      <p className="processing-progress__stage text-center text-base font-semibold">
        {stageLabel}
      </p>

      <div className="w-full">
        <div className="flex items-center gap-3">
          <div
            className="processing-progress__bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={shownPercent}
            aria-label="Processing progress"
          >
            <div
              className="processing-progress__bar-fill"
              style={{ width: `${shownPercent}%` }}
            />
          </div>
          <span className="w-10 shrink-0 text-right text-sm font-semibold tabular-nums text-slate-700">
            {shownPercent}%
          </span>
        </div>

        <dl className="mt-4 grid grid-cols-3 gap-2">
          <Counter label="Rows read" value={formatCount(counters.rows_read)} />
          <Counter label="Rows kept" value={formatCount(counters.rows_kept)} />
          <Counter label="Rows dropped" value={formatCount(counters.rows_dropped)} />
        </dl>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <span>
            Elapsed <span className="font-medium tabular-nums text-slate-700">{formatElapsed(elapsed)}</span>
          </span>
          {mode === 'imd' && (
            <span>
              Files <span className="font-medium text-slate-700">{counts.files_total ?? fileCount}</span>
            </span>
          )}
        </div>

        <ul className="processing-progress__checklist mt-5 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
          {stages.map((stage, index) => {
            const state = states[index];
            return (
              <li
                key={stage.key}
                className={`processing-progress__item--${state} flex items-start gap-2 text-left text-xs leading-5`}
              >
                <span className={`processing-progress__check processing-progress__check--${state} mt-0.5`}>
                  {state === 'done' ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
                </span>
                <span>{stage.label}</span>
              </li>
            );
          })}
        </ul>

        <p className="processing-progress__muted mt-5 text-center text-xs leading-relaxed">
          You can leave this page. We'll notify you in the bell when it's done.
        </p>

        {onCancel && (
          <div className="mt-2 flex justify-center">
            <button
              type="button"
              onClick={onCancel}
              disabled={cancelling}
              aria-busy={cancelling}
              className="rounded-md px-2 py-1 text-xs font-medium text-slate-500 underline-offset-2 transition-colors hover:text-red-600 hover:underline disabled:cursor-wait disabled:text-slate-400 disabled:no-underline"
            >
              {cancelling ? 'Cancelling…' : 'Cancel processing'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default ProcessingProgress;
