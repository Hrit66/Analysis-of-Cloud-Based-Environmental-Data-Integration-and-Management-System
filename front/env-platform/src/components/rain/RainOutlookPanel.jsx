import React from 'react';
import { CloudRain, Info } from 'lucide-react';

const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const formatDay = (value) => {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric' });
};

const percentLabel = (value) => (value === null || value === undefined ? '—' : `${value}%`);
const barHeight = (value) => `${Math.max(4, Math.min(100, value || 0))}%`;

const RainOutlookPanel = ({ outlook }) => {
  if (!outlook) return null;

  const daily = outlook.daily || [];
  const monthly = outlook.monthly || [];
  const week = outlook.week_probability_pct ?? outlook.week_probability_estimate_pct;
  const estimateOnly = outlook.week_probability_pct === null && week !== null;
  const threshold = outlook.threshold_mm ?? 1;
  const years = outlook.years_observed ?? 0;
  const minYears = outlook.min_years ?? 10;
  const model = outlook.model;
  const windowDays = outlook.window_days ?? 7;
  const ciLow = outlook.week_probability_ci_low_pct;
  const ciHigh = outlook.week_probability_ci_high_pct;
  const ciLabel = ciLow !== null && ciLow !== undefined && ciHigh !== null && ciHigh !== undefined
    ? `${ciLow}–${ciHigh}%`
    : null;
  const brier = outlook.brier_score;
  const brierReference = outlook.brier_reference;
  const brierSkill = outlook.brier_skill_score_pct;

  return (
    <div className="glass-card p-6 rounded-2xl animate-fade-in-up" style={{ animationDelay: '150ms' }}>
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <CloudRain className="w-5 h-5 text-blue-600" />
            <h2 className="text-lg font-bold text-slate-800">Rain Outlook</h2>
            <span className="px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-100 text-[10px] font-semibold uppercase tracking-wide">
              Probability only
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Chance of a ≥ {threshold} mm day. No daily millimetre forecast.
          </p>
        </div>
        <div className="sm:text-right">
          <div className="text-3xl font-bold text-slate-800">{percentLabel(week)}</div>
          <div className="text-xs text-slate-500">
            {week === null
              ? `needs ≥ ${minYears} years of history`
              : estimateOnly
                ? `${years}-year estimate · next ${windowDays} days${ciLabel ? ` · 95% CI ${ciLabel}` : ''}`
                : `next ${windowDays} days · ${outlook.wet_years} of ${years} years${ciLabel ? ` · 95% CI ${ciLabel}` : ''}`}
          </div>
        </div>
      </div>

      {daily.length > 0 && (
        <div className="mt-5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-700">Daily chance</h3>
            <span className="text-[10px] text-slate-400">observed wet-day frequency by month</span>
          </div>
          <div className="grid grid-cols-7 gap-1.5">
            {daily.map((day) => (
              <div key={day.date} className="rounded-lg border border-slate-100 bg-slate-50/70 px-1 py-2 text-center">
                <div className="text-[10px] text-slate-500">{formatDay(day.date)}</div>
                <div className="h-16 flex items-end justify-center my-1">
                  <div
                    className="w-4 rounded-t bg-blue-500"
                    style={{ height: barHeight(day.rain_probability_pct) }}
                  />
                </div>
                <div className="text-xs font-semibold text-slate-700">{percentLabel(day.rain_probability_pct)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {monthly.length > 0 && (
        <div className="mt-5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-700">Monthly seasonality</h3>
            <span className="text-[10px] text-slate-400">wet-day frequency</span>
          </div>
          <div className="grid grid-cols-6 sm:grid-cols-12 gap-1">
            {monthly.map((month) => (
              <div key={month.month}>
                <div className="h-14 flex items-end justify-center rounded bg-slate-50 px-1">
                  <div
                    className="w-full max-w-5 rounded-t bg-sky-400"
                    style={{ height: barHeight(month.rain_probability_pct) }}
                  />
                </div>
                <div className="text-[9px] text-slate-500 text-center mt-1">{MONTH_LABELS[month.month - 1]}</div>
                <div className="text-[9px] text-slate-400 text-center">{percentLabel(month.rain_probability_pct)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className={`mt-4 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${
        model?.suppressed
          ? 'bg-amber-50 border-amber-100 text-amber-800'
          : 'bg-slate-50 border-slate-100 text-slate-600'
      }`}>
        <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <span>
          {model
            ? model.suppressed
              ? `Daily amount model hidden: ${model.reason} Rain chances are observed climatology, not model output.`
              : `Daily amount model beats the always-dry baseline (MAE ${model.mae} mm vs ${model.zero_baseline_mae} mm). Rain chances are still observed climatology.`
            : 'Daily amount model not available; showing observed climatology.'}
          {brier !== null && brier !== undefined && brierReference !== null && brierReference !== undefined && (
            <span className="block mt-1">
              Probability skill (leave-one-year-out Brier): {brier.toFixed(3)} vs{' '}
              {brierReference.toFixed(3)} for the constant base rate
              {brierSkill !== null && brierSkill !== undefined ? ` (${brierSkill}% skill)` : ''}.
            </span>
          )}
          {estimateOnly && (
            <span className="block mt-1">
              This weekly estimate uses {years} years; {minYears}+ years is preferred for confidence.
            </span>
          )}
        </span>
      </div>
    </div>
  );
};

export default RainOutlookPanel;
