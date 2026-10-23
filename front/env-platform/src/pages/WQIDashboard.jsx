import React, { useState, useEffect } from 'react';
import AnalyticsDashboardTemplate from '../components/layout/AnalyticsDashboardTemplate';
import DashboardLoadingSkeleton from '../components/common/DashboardLoadingSkeleton';
import { useDatasetFor } from '../hooks/useDatasetFor';
import { fetchWQIData, fetchWQISummary, fetchWQITrend, fetchDatasetDateRange, fetchForecasts, fetchAnomalySummary, datasetDisplayLabel } from '../lib/api';

const WQI_SI = {
  ph: 8.5,
  turbidity: 5,
  tds: 500,
  hardness: 300,
  chlorides: 250,
  sulfates: 200,
  nitrates: 45,
  fluorides: 1,
  iron: 0.3,
  manganese: 0.1,
  do: 5,
  bod: 3,
};

const CORE_PARAMS = ['ph', 'do', 'bod'];

const PARAM_LABELS = {
  ph: 'pH',
  turbidity: 'Turbidity (NTU)',
  tds: 'TDS (mg/L)',
  hardness: 'Hardness (mg/L)',
  chlorides: 'Chlorides (mg/L)',
  sulfates: 'Sulfates (mg/L)',
  nitrates: 'Nitrates (mg/L as NO3)',
  fluorides: 'Fluorides (mg/L)',
  iron: 'Iron (mg/L)',
  manganese: 'Manganese (mg/L)',
  do: 'Dissolved oxygen (mg/L)',
  bod: 'BOD (mg/L)',
};

const CATEGORY_COLORS = {
  Excellent: 'green',
  Good: 'blue',
  Poor: 'yellow',
  'Very Poor': 'red',
  'Unsuitable (>100)': 'red',
};

const categoryForValue = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  const num = Number(value);
  if (num < 25) return 'Excellent';
  if (num < 50) return 'Good';
  if (num < 75) return 'Poor';
  if (num < 100) return 'Very Poor';
  return 'Unsuitable (>100)';
};

const coliformFlag = (value) => {
  if (value === null || value === undefined) {
    return { level: undefined, status: null, caption: 'MPN/100 mL - not measured on latest sample' };
  }
  const caption = 'MPN/100 mL - CPCB limits: 50 (A) / 500 (B) / 5,000 (C)';
  if (value > 5000) return { level: 'red', status: 'Exceeds all limits', caption };
  if (value > 500) return { level: 'orange', status: 'Exceeds Class A/B', caption };
  if (value > 50) return { level: 'yellow', status: 'Exceeds Class A', caption };
  return { level: 'green', status: 'Within Class A', caption };
};

const LEGEND_ITEMS = [
  { label: '0-25 Excellent', className: 'bg-green-50 text-green-700 border-green-200' },
  { label: '25-50 Good', className: 'bg-blue-50 text-blue-700 border-blue-200' },
  { label: '50-75 Poor', className: 'bg-yellow-50 text-yellow-700 border-yellow-200' },
  { label: '75-100 Very Poor', className: 'bg-red-50 text-red-700 border-red-200' },
  { label: '100+ Unsuitable', className: 'bg-red-100 text-red-800 border-red-300' },
];

const formatDay = (timestamp) => {
  if (!timestamp) return '-';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
};

const formatNumber = (value) => {
  if (value === null || value === undefined) return '-';
  const num = Number(value);
  if (!Number.isFinite(num)) return '-';
  return Number(num.toFixed(2)).toLocaleString('en-US');
};

const formatCompact = (value) => {
  if (value === null || value === undefined) return '-';
  const num = Number(value);
  if (!Number.isFinite(num)) return '-';
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(num);
};

const monthLabel = (timestamp) => {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
};

function AboutThisIndex() {
  return (
    <div className="space-y-2 text-[11px]">
      <p>
        <strong className="text-slate-600">Method:</strong> weighted arithmetic water quality index
        (CPCB). <strong className="text-slate-600">Lower is better.</strong> The headline index is
        scored on a <strong className="text-slate-600">fixed core set - pH, dissolved oxygen and
        BOD</strong> - so that every scored sample is comparable. A sample with any of the three
        missing gets no headline index (shown as &ldquo;-&rdquo;), never a score renormalised over
        whatever happened to be measured.
      </p>
      <p>
        WQI = &Sigma;(Q<sub>i</sub>&middot;W<sub>i</sub>) / &Sigma;W<sub>i</sub>, where
        Q<sub>i</sub> = 100&middot;(V<sub>i</sub>&minus;V<sub>id</sub>)/(S<sub>i</sub>&minus;V<sub>id</sub>)
        and W<sub>i</sub> = K/S<sub>i</sub> with K = 1/&Sigma;(1/S<sub>i</sub>) = 0.06569927 over the
        12 parameters below (K cancels in the ratio). For dissolved oxygen the ratio is reversed:
        Q<sub>i</sub> = 100&middot;(V<sub>id</sub>&minus;V<sub>i</sub>)/(V<sub>id</sub>&minus;S<sub>i</sub>).
        For pH the numerator is the <em>absolute</em> deviation:
        Q<sub>pH</sub> = 100&middot;|pH&minus;7.0|/1.5.
      </p>
      <p>
        <strong className="text-slate-600">Extended index:</strong> when a sample carries extra
        parameters, a second index is reported separately in the breakdown, labelled with its
        parameter count (&ldquo;N of 12 parameters&rdquo;). It scores every present parameter and is
        never used for the chart, the average card or the station rank - with different parameter
        sets it is not comparable across samples. It needs at least 3 present parameters including
        DO or BOD, otherwise it is shown as unavailable.
      </p>
      <div className="overflow-x-auto">
        <table className="mt-1 text-[11px]">
          <thead>
            <tr className="text-slate-500">
              <th className="pr-4 text-left font-medium">Parameter</th>
              <th className="pr-4 text-left font-medium">Standard S<sub>i</sub></th>
              <th className="pr-4 text-left font-medium">Ideal V<sub>id</sub></th>
              <th className="text-left font-medium">Source of the limit</th>
            </tr>
          </thead>
          <tbody className="text-slate-600">
            <tr><td className="pr-4 font-semibold">pH</td><td className="pr-4">8.5</td><td className="pr-4">7.0</td><td>BIS 10500:2012 range 6.5-8.5; ideal 7.0 is the CPCB WQI convention</td></tr>
            <tr><td className="pr-4">Turbidity</td><td className="pr-4">5 NTU</td><td className="pr-4">0</td><td>BIS 10500:2012 permissible (acceptable 1 NTU)</td></tr>
            <tr><td className="pr-4">TDS</td><td className="pr-4">500 mg/L</td><td className="pr-4">0</td><td>BIS 10500:2012 acceptable (permissible 2,000)</td></tr>
            <tr><td className="pr-4">Hardness</td><td className="pr-4">300 mg/L</td><td className="pr-4">0</td><td>IS 10500:1991 / Indian WQI tables (2012 acceptable: 200)</td></tr>
            <tr><td className="pr-4">Chlorides</td><td className="pr-4">250 mg/L</td><td className="pr-4">0</td><td>BIS 10500:2012 acceptable (permissible 1,000)</td></tr>
            <tr><td className="pr-4">Sulfates</td><td className="pr-4">200 mg/L</td><td className="pr-4">0</td><td>BIS 10500:2012 acceptable (permissible 400)</td></tr>
            <tr><td className="pr-4">Nitrates</td><td className="pr-4">45 mg/L (as NO3)</td><td className="pr-4">0</td><td>BIS 10500:2012 acceptable, no relaxation; files report nitrate-N and the import converts it (&times;4.4266)</td></tr>
            <tr><td className="pr-4">Fluorides</td><td className="pr-4">1.0 mg/L</td><td className="pr-4">0</td><td>BIS 10500:2012 acceptable (permissible 1.5)</td></tr>
            <tr><td className="pr-4">Iron</td><td className="pr-4">0.3 mg/L</td><td className="pr-4">0</td><td>BIS 10500:2012 acceptable, no relaxation</td></tr>
            <tr><td className="pr-4">Manganese</td><td className="pr-4">0.1 mg/L</td><td className="pr-4">0</td><td>BIS 10500:2012 acceptable (permissible 0.3)</td></tr>
            <tr><td className="pr-4 font-semibold">Dissolved oxygen</td><td className="pr-4">5.0 mg/L</td><td className="pr-4">14.6 (saturation)</td><td>CPCB class B/C (DO &ge; 5); ideal 14.6 is the WQI-table saturation constant</td></tr>
            <tr><td className="pr-4 font-semibold">BOD</td><td className="pr-4">3.0 mg/L</td><td className="pr-4">0</td><td>CPCB class B/C (BOD &le; 3)</td></tr>
          </tbody>
        </table>
      </div>
      <p className="text-slate-500">
        Turbidity uses the BIS <em>permissible</em> value (5 NTU), not the acceptable value
        (1 NTU), which would saturate the index on these raw lake samples. Hardness 300 mg/L
        follows the IS 10500:1991 / Indian WQI parameter tables; the 2012 revision's acceptable
        limit is 200 mg/L.
      </p>
      <p className="text-slate-500">
        Rows in <strong>bold</strong> (pH, DO, BOD) are the fixed core set used by the headline
        index; the other nine parameters feed the extended index only. Nitrate is stored in the
        database as NO3: the source files report nitrate as N (&ldquo;NO3-N&rdquo;, e.g. 1.3 mg/L)
        and the import multiplies by 4.4266 (62.004/14.007) so the 45 mg/L NO3 limit applies to a
        consistent unit.
      </p>
      <p>
        <strong className="text-slate-600">pH rule:</strong> the pH sub-index uses the{' '}
        <em>absolute</em> deviation from the ideal 7.0 - deviation below the ideal is penalised
        exactly like deviation above it. pH 6.5 (inside the BIS range 6.5-8.5) and pH 7.5 both
        score Q<sub>pH</sub> = 33.33; the signed formula would have scored pH 6.5 as
        &minus;33.33, i.e. better than neutral water.
      </p>
      <p>
        <strong className="text-slate-600">Cap and floor:</strong> sub-indices Q<sub>i</sub> are
        clamped to 0-200: capped above at 200 and floored at 0. A dissolved oxygen reading above
        its 14.6 saturation ideal therefore scores Q<sub>do</sub> = 0, not a negative sub-index
        that would flatter the sample. The final score is also floored at 0.
      </p>
      <p>
        <strong className="text-slate-600">Scoring rules:</strong> the headline index requires
        all three core parameters (pH, DO, BOD) and is scored on exactly those - no
        renormalisation, so the index does not step when the file's schema changes. The extended
        index requires at least 3 present parameters including DO or BOD; it renormalises over
        what is present but is always shown with its parameter count.
      </p>
      <p>
        <strong className="text-slate-600">Average rule:</strong> the Average WQI card is the
        unweighted mean of the per-sample <em>core</em> index values inside the selected date
        window for the selected station - no time weighting, no parameter averaging, and samples
        without the full core set are excluded (counted in the caption).
      </p>
      <p>
        <strong className="text-slate-600">Station rank:</strong> the Average card also ranks the
        station's window mean against every station in the same dataset and window that has at
        least 3 scored samples. The rank is always shown with the sample count it is based on and
        the number of ranked stations; stations with fewer than 3 samples are never ranked.
      </p>
      <p>
        <strong className="text-slate-600">CPCB best-use class:</strong> reported separately from
        the WQI and never mixed into it. A sample's class is the best CPCB designated use whose
        checkable criteria are all met (IS 2296:1992). Criteria whose parameter is missing are not
        assumed to pass - the result is marked &ldquo;partial&rdquo; and the card lists what is
        missing. Class D is approximate because the files store total NH<sub>3</sub>-N, not free
        ammonia (free ammonia is a fraction of the total, so total &le; 1.2 proves the criterion);
        sodium adsorption ratio and boron are not stored, so class E cannot be fully verified
        either.
      </p>
      <div className="overflow-x-auto">
        <table className="mt-1 text-[11px]">
          <thead>
            <tr className="text-slate-500">
              <th className="pr-4 text-left font-medium">Class</th>
              <th className="pr-4 text-left font-medium">Designated best use</th>
              <th className="text-left font-medium">Criteria</th>
            </tr>
          </thead>
          <tbody className="text-slate-600">
            <tr><td className="pr-4">A</td><td className="pr-4">Drinking water source, no conventional treatment (disinfection only)</td><td>pH 6.5-8.5, DO &ge; 6, BOD &le; 2, coliform &le; 50</td></tr>
            <tr><td className="pr-4">B</td><td className="pr-4">Outdoor bathing (organised)</td><td>pH 6.5-8.5, DO &ge; 5, BOD &le; 3, coliform &le; 500</td></tr>
            <tr><td className="pr-4">C</td><td className="pr-4">Drinking water source after conventional treatment</td><td>pH 6.0-9.0, DO &ge; 4, BOD &le; 3, coliform &le; 5000</td></tr>
            <tr><td className="pr-4">D</td><td className="pr-4">Propagation of wildlife and fisheries</td><td>pH 6.5-8.5, DO &ge; 4, free ammonia &le; 1.2</td></tr>
            <tr><td className="pr-4">E</td><td className="pr-4">Irrigation, industrial cooling, controlled waste disposal</td><td>pH 6.0-8.5, conductivity &le; 2250, SAR &le; 26, boron &le; 2</td></tr>
          </tbody>
        </table>
      </div>
      <p className="text-slate-500">
        Source: CPCB designated best-use water quality criteria (IS 2296:1992). Coliform in
        MPN/100 mL, DO / BOD / free ammonia in mg/L, conductivity in micromhos/cm, boron in mg/L.
        A sample failing every checkable criterion is shown as &ldquo;Below E&rdquo;.
      </p>
      <p>
        <strong className="text-slate-600">Bacteriological flag:</strong> total coliform is not part
        of the score. BIS IS:10500 sets the coliform limit at &ldquo;not detectable&rdquo; (0),
        which makes Q<sub>i</sub> undefined, and MPN counts in this data reach 9.2&times;10<sup>9</sup>,
        which would swamp every other parameter. Instead the Bacteriological card compares the
        latest sample with the CPCB class limits: Class A 50, Class B 500, Class C 5,000 MPN/100 mL.
        Above 5,000 the sample exceeds all three class limits.
      </p>
      <p>
        <strong className="text-slate-600">Trend:</strong> the trend panel uses Sen&apos;s slope, the
        median of all pairwise slopes, so a single unusual sample cannot dominate the estimate. The
        two-sided Mann-Kendall test checks for a monotonic trend and corrects its variance for tied
        values. It needs at least 8 scored WQI samples in the selected window. Lower WQI is better,
        so a positive slope means worsening water quality and a negative slope means improvement;
        a p-value at or above 0.05 is reported as no statistically significant trend. The result
        describes the selected window only - it is not a forecast or proof of causation.
      </p>
      <p>
        <strong className="text-slate-600">Outlooks:</strong> the next-3-months outlooks below the
        breakdown cover three parameters per station, each evaluated rolling-origin against the
        persistence baseline (repeat the last observed month) at horizons of 1-3 months: total
        coliform (modelled in log1p space because MPN spans several orders of magnitude), dissolved
        oxygen and the core WQI (both in native units). Each parameter needs at least 24 monthly
        samples before an outlook is published. Monthly sampling is sparse and this source often
        repeats values across consecutive months, so persistence is hard to beat; when it matches or
        wins at the 1-month horizon the note says so - the outlooks are broad level indicators, not
        precise forecasts.
      </p>
      <p>
        <strong className="text-slate-600">Anomalies:</strong> the DO / WQI anomalies card counts
        samples flagged in the station's <em>full history</em> by a robust z-score (median/MAD
        scale, |z| &gt; 3 - the series are too short for the seasonal baseline, so raw values are
        scored). Flagged samples are tagged unusually low or unusually high, e.g. low-DO hypoxia
        events (DO 0.5-1.2 mg/L) or supersaturation (DO 15.0). Stations with fewer than 15 samples
        for a parameter are not scored. Across this dataset the flag rates are 2.0% of DO samples
        and 7.4% of WQI samples; the card shows the split for the selected station.
      </p>
      <p>
        <strong className="text-slate-600">Not scored but stored:</strong> ammonia (NH<sub>3</sub>-N),
        conductivity and coliform are stored with the data. Ammonia has no BIS IS:10500 limit in
        this method and is kept exactly as measured - the frequently repeated 0.40 mg/L value is
        <em> not</em> treated as a below-detection placeholder, it is shown as measured.
      </p>
      <p>
        <strong className="text-slate-600">Sensitivity:</strong> the score is sensitive to the limit
        choices; under different standards the same sample can differ by hundreds of points.
        The headline series is kept comparable by the fixed core set, but the extended index
        varies with which extra parameters are present - always read it with its parameter count.
      </p>
      <p>
        <strong className="text-slate-600">Scale (lower is better):</strong> 0-25 Excellent,
        25-50 Good, 50-75 Poor, 75-100 Very Poor, 100+ Unsuitable (&gt;100) (75 itself is
        Very Poor).
      </p>
      <p>
        <strong className="text-slate-600">Worked examples (core set):</strong> pH 8.0, DO 6.4,
        BOD 4.0 gives Q<sub>i</sub> 66.67 / 85.42 / 133.33 and WQI = 106.56. pH 7.1, DO 5.7,
        BOD 5.0 gives Q<sub>i</sub> 6.67 / 92.71 / 166.67 and WQI = 115.03. pH 6.9, DO 2.0,
        BOD 16.0 gives WQI = 143.94 (the BOD sub-index is capped at 200). pH 7.1, DO 6.2,
        BOD 4.0 gives WQI = 96.36; that sample (Ibbalur, 30 Dec 2020) also carries turbidity
        6.6 NTU and nitrate-N 1.3 mg/L, so its extended index - 5 of 12 parameters - is 102.40,
        reported separately from the headline. pH 6.5, DO 6.1, BOD 4.0 gives WQI = 101.50 -
        pH 6.5 is inside the BIS acceptable range but below the ideal, so it still carries a
        penalty.
      </p>
      <p className="text-slate-400">
        The page defaults to the last 12 months of the dataset (or the full range if the data is
        shorter) and shows the latest sample of the selected station in that window. The outlooks
        and anomaly flags are always computed from the station's full history, not the window.
      </p>
    </div>
  );
}

const buildRows = (record, subIndices) =>
  Object.keys(WQI_SI)
    .filter(param => subIndices[param] !== undefined)
    .map(param => ({
      param,
      value: record[param],
      qi: subIndices[param],
      share: (subIndices[param] / WQI_SI[param]),
    }));

const renderTrendSection = (trend) => {
  if (!trend) return null;

  if (!trend.available) {
    return (
      <div className="mt-5 border-t border-slate-100 pt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-bold text-slate-800">WQI trend</h3>
          <span className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-500">
            unavailable
          </span>
        </div>
        <p className="text-xs text-slate-500 mt-1">
          Needs at least {trend.min_samples ?? 8} scored samples in the selected window; this window has {trend.n ?? 0}.
        </p>
      </div>
    );
  }

  const slope = Number(trend.sen_slope_per_year);
  const mk = trend.mann_kendall || {};
  const pValue = mk.p_value;
  const pLabel = pValue === null || pValue === undefined
    ? '-'
    : pValue < 0.001 ? '<0.001' : Number(pValue).toFixed(3);
  const slopeLabel = `${slope > 0 ? '+' : ''}${formatNumber(slope)}`;
  const improving = trend.direction === 'decreasing';
  const worsening = trend.direction === 'increasing';
  const tone = trend.significant
    ? (worsening ? 'border-red-200 bg-red-50 text-red-700' : improving ? 'border-green-200 bg-green-50 text-green-700' : 'border-slate-200 bg-slate-50 text-slate-600')
    : 'border-slate-200 bg-slate-50 text-slate-600';
  const label = trend.significant
    ? (worsening ? 'significant worsening' : improving ? 'significant improvement' : 'significant change')
    : 'no significant trend';

  return (
    <div className="mt-5 border-t border-slate-100 pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <h3 className="text-sm font-bold text-slate-800">WQI trend (selected window)</h3>
        <span className={`rounded border px-2 py-0.5 text-[10px] font-medium ${tone}`}>{label}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <div className="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Sen&apos;s slope</div>
          <div className="text-sm font-semibold text-slate-800">{slopeLabel} <span className="text-[10px] font-normal text-slate-400">WQI points/year</span></div>
        </div>
        <div className="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Mann-Kendall p</div>
          <div className="text-sm font-semibold text-slate-800">{pLabel} <span className="text-[10px] font-normal text-slate-400">{trend.significant ? 'significant at 0.05' : 'not significant at 0.05'}</span></div>
        </div>
        <div className="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Samples</div>
          <div className="text-sm font-semibold text-slate-800">{trend.n} <span className="text-[10px] font-normal text-slate-400">over {Number(trend.span_years).toFixed(1)} years</span></div>
        </div>
      </div>
      <p className="text-[11px] text-slate-500 mt-2">
        {trend.interpretation} Lower WQI is better. Sen&apos;s slope is the median of pairwise slopes;
        the p-value is the two-sided Mann-Kendall test with tie correction.
      </p>
      <p className="text-[10px] text-slate-400 mt-1">
        {formatDay(trend.start_date)} to {formatDay(trend.end_date)}. A significant trend describes the
        selected window, not a forecast or proof of causation.
      </p>
    </div>
  );
};

const buildBreakdown = (record, dateLabel, trend) => {
  const rows = buildRows(record, record.sub_indices || {}).sort((a, b) => b.share - a.share);
  const extRows = buildRows(record, record.extended_sub_indices || {}).sort((a, b) => b.share - a.share);
  const shareTotal = rows.reduce((total, row) => total + row.share, 0) || 1;
  const extShareTotal = extRows.reduce((total, row) => total + row.share, 0) || 1;
  const showExtended = record.extended_wqi !== null && record.extended_wqi !== undefined
    && extRows.length > rows.length;
  const extendedSameAsCore = record.extended_wqi !== null && record.extended_wqi !== undefined
    && !showExtended && rows.length > 0;
  const missingCore = CORE_PARAMS.filter(param => record.sub_indices?.[param] === undefined);

  const excluded = [
    { label: 'Conductivity', value: record.conductivity, unit: 'uS/cm' },
    { label: 'Ammonia (NH3-N)', value: record.ammonia, unit: 'mg/L' },
    { label: 'Total coliform', value: record.total_coliform, unit: 'MPN/100 mL' },
  ].filter(row => row.value !== null && row.value !== undefined);

  const renderTable = (tableRows, shareTotalForRows) => (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-slate-500 border-b border-slate-100">
          <th className="py-2 font-medium">Parameter</th>
          <th className="py-2 font-medium text-right">Value</th>
          <th className="py-2 font-medium text-right">Sub-index Q<sub>i</sub></th>
          <th className="py-2 font-medium text-right">Share of score</th>
        </tr>
      </thead>
      <tbody>
        {tableRows.map(row => (
          <tr key={row.param} className="border-b border-slate-50">
            <td className="py-2 text-slate-700">{PARAM_LABELS[row.param]}</td>
            <td className="py-2 text-right text-slate-700">{formatNumber(row.value)}</td>
            <td className="py-2 text-right text-slate-700">{formatNumber(row.qi)}</td>
            <td className="py-2 text-right">
              <div className="flex items-center justify-end gap-2">
                <div className="hidden sm:block w-28 h-1.5 bg-slate-100 rounded overflow-hidden">
                  <div className="h-1.5 bg-sky-500 rounded" style={{ width: `${Math.max(2, row.share / shareTotalForRows * 100)}%` }}></div>
                </div>
                <span className="text-slate-700 w-14">{(row.share / shareTotalForRows * 100).toFixed(1)}%</span>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
        <h2 className="text-lg font-bold text-slate-800">Score breakdown (latest sample)</h2>
        <span className="text-xs text-slate-500">
          {dateLabel} &middot; core WQI {formatNumber(record.wqi)} {record.wqi_category ? `(${record.wqi_category})` : ''}
        </span>
      </div>
      {rows.length > 0 ? renderTable(rows, shareTotal) : (
        <p className="text-sm text-slate-500">
          No headline score: the fixed core set needs all three of pH, DO and BOD
          (this sample has {CORE_PARAMS.length - missingCore.length} of them
          {missingCore.length > 0 ? ` - missing ${missingCore.map(p => PARAM_LABELS[p]).join(', ')}` : ''}).
        </p>
      )}
      <p className="text-xs text-slate-500 mt-3">
        The headline score always uses the fixed core set (pH, DO, BOD), so every scored sample
        is comparable - parameters are never renormalised in or out of it.
      </p>
      {renderTrendSection(trend)}
      {showExtended && (
        <div className="mt-5 border-t border-slate-100 pt-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-1">
            <h3 className="text-sm font-bold text-slate-800">
              Extended index ({extRows.length} of 12 parameters)
            </h3>
            <span className="text-xs text-slate-500">
              {formatNumber(record.extended_wqi)} {record.extended_wqi_category ? `(${record.extended_wqi_category})` : ''}
            </span>
          </div>
          <p className="text-xs text-slate-500 mb-2">
            Scores every parameter present on this sample. It is intentionally not comparable
            between samples with different parameter counts - read it with its count, not as a trend.
          </p>
          {renderTable(extRows, extShareTotal)}
        </div>
      )}
      {extendedSameAsCore && (
        <p className="text-xs text-slate-400 mt-1">
          Only the 3 core parameters are present, so the extended index equals the headline score.
        </p>
      )}
      {excluded.length > 0 && (
        <p className="text-xs text-slate-400 mt-1">
          Stored but not scored: {excluded.map(row => `${row.label} ${formatNumber(row.value)} ${row.unit}`).join('; ')}. See &ldquo;About this index&rdquo; for why.
        </p>
      )}
    </div>
  );
};

const OUTLOOK_PARAMS = [
  { key: 'total_coliform', label: 'Coliform', unit: 'MPN/100 mL', compact: true },
  { key: 'do', label: 'Dissolved oxygen', unit: 'mg/L', compact: false },
  { key: 'wqi', label: 'WQI (core set)', unit: 'index points', compact: false },
];

const renderOutlookSection = (forecast, meta, key) => {
  const metrics = forecast.metrics || {};
  const horizon = metrics.horizon_mae || [];
  const persistence = metrics.horizon_persistence_mae || [];
  const persistenceWins = horizon.length > 0 && persistence.length > 0 && horizon[0] >= persistence[0];
  const formatValue = meta.compact ? formatCompact : formatNumber;

  return (
    <div key={key} className="mt-6 border-t border-slate-100 pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <h3 className="text-sm font-bold text-slate-800">
          {meta.label} outlook (next {forecast.predictions.length} months)
        </h3>
        <span className="text-[11px] text-slate-500">{metrics.model_note}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {forecast.predictions.map(point => (
          <div key={point.timestamp} className="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2">
            <div className="text-[11px] text-slate-500">{monthLabel(point.timestamp)}</div>
            <div className="text-sm font-semibold text-slate-800">
              {meta.compact ? '~' : ''}{formatValue(point.predicted_value)}{' '}
              <span className="text-[10px] font-normal text-slate-400">{meta.unit}</span>
            </div>
            <div className="text-[10px] text-slate-400">
              80% interval {formatValue(point.lower_bound)} - {formatValue(point.upper_bound)}
            </div>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-slate-500 mt-2">
        Rolling-origin check ({metrics.rolling_origins} origins, {metrics.monthly_points} monthly points): model / persistence MAE
        {horizon.length === 3 && persistence.length === 3
          ? <> at 1-3 months {horizon[0]} / {persistence[0]}, {horizon[1]} / {persistence[1]}, {horizon[2]} / {persistence[2]} {metrics.scale === 'log1p' ? '(log1p units)' : `(${meta.unit})`};</>
          : <> {metrics.test_mae} / {metrics.baseline_persistence_mae};</>}
        {metrics.mae_multiplicative_factor
          ? <> typical error x{metrics.mae_multiplicative_factor} in MPN.</>
          : <> typical error ±{metrics.test_mae} {meta.unit}.</>}
      </p>
      <p className={`text-[11px] mt-1 ${persistenceWins ? 'text-amber-700' : 'text-slate-400'}`}>
        {metrics.limitation}
      </p>
    </div>
  );
};

const buildOutlooks = (forecasts, location) => {
  const list = (Array.isArray(forecasts) ? forecasts : [])
    .filter(f => f.location === location && Array.isArray(f.predictions) && f.predictions.length > 0);

  if (list.length === 0) {
    return (
      <div className="mt-6 border-t border-slate-100 pt-4">
        <h3 className="text-sm font-bold text-slate-800">Outlooks</h3>
        <p className="text-[11px] text-slate-400 mt-1">
          No outlook for this station - each parameter needs at least 24 monthly samples.
          Coliform is modelled in log1p space; DO and WQI in native units, each evaluated
          rolling-origin against persistence.
        </p>
      </div>
    );
  }

  return OUTLOOK_PARAMS.map(meta => {
    const forecast = list.find(f => f.parameter === meta.key);
    return forecast ? renderOutlookSection(forecast, meta, meta.key) : null;
  });
};

const CPCB_CLASS_COLORS = {
  A: 'green',
  B: 'blue',
  C: 'yellow',
  D: 'orange',
  E: 'red',
  'Below E': 'red',
};

const cpcbCaption = (cpcb) => {
  if (!cpcb) return 'no stored classification for this sample';
  const parts = [cpcb.label];
  if (cpcb.partial && cpcb.missing?.length) parts.push(`partial - missing ${cpcb.missing.join(', ')}`);
  if (cpcb.note) parts.push(cpcb.note);
  return parts.join(' | ');
};

const cardsConfig = [
  { title: 'Latest WQI', dataKey: 'currentWQI', statusKey: 'category', color: (data) => CATEGORY_COLORS[data?.category], captionKey: 'latestCaption' },
  { title: 'Average WQI', dataKey: 'avgWQI', statusKey: 'averageCategory', color: (data) => CATEGORY_COLORS[data?.averageCategory], captionKey: 'averageCaption' },
  { title: 'Worst WQI', dataKey: 'maxWQI', statusKey: 'worstCategory', color: (data) => CATEGORY_COLORS[data?.worstCategory], captionKey: 'worstCaption' },
  { title: 'Bacteriological (latest)', dataKey: 'coliformValue', statusKey: 'coliformStatus', color: (data) => data?.coliformLevel, captionKey: 'coliformCaption' },
  { title: 'CPCB best-use class', dataKey: 'cpcbClass', statusKey: 'cpcbStatus', color: (data) => data?.cpcbClassLevel, captionKey: 'cpcbClassCaption' },
  { title: 'DO / WQI anomalies', dataKey: 'anomalyCount', statusKey: 'anomalyStatus', color: () => 'red', captionKey: 'anomalyCaption' },
];

const chartConfig = {
  dataKey: 'value',
  color: '#0ea5e9',
  yLabel: 'Water Quality Index',
  tooltipName: 'WQI',
  timeAxis: true,
};

const EMPTY_CARDS = { currentWQI: '-', category: '-', avgWQI: '-', maxWQI: '-', anomalyCount: '-' };

const WQIDashboard = () => {
  const {
    datasets,
    selectedId: datasetId,
    setSelectedId,
    loading: datasetsLoading,
  } = useDatasetFor('water_quality');
  const [location, setLocation] = useState(null);
  const [locations, setLocations] = useState([]);
  const [dateBounds, setDateBounds] = useState(null);
  const [summaryLoaded, setSummaryLoaded] = useState(false);

  useEffect(() => {
    if (!datasetId) return;
    setSummaryLoaded(false);
    Promise.all([
      fetchWQISummary(datasetId),
      fetchDatasetDateRange(datasetId).catch(() => null),
    ])
      .then(([summary, bounds]) => {
        if (Array.isArray(summary) && summary.length > 0) {
          const locs = summary.map(r => r.location);
          setLocations(locs);
          setLocation(prev => (locs.includes(prev) ? prev : locs[0]));
        }
        setDateBounds(bounds);
      })
      .catch(console.error)
      .finally(() => setSummaryLoaded(true));
  }, [datasetId]);

  const fetchWQIDataForTemplate = async (id, from, to) => {
    if (!id) return { ...EMPTY_CARDS, series: [] };

    const [wqiData, forecasts, summary, anomalySummary, trend] = await Promise.all([
      fetchWQIData(id, location, from, to),
      fetchForecasts(id, { location }).catch(() => []),
      fetchWQISummary(id, null, from, to).catch(() => []),
      fetchAnomalySummary(id).catch(() => null),
      location ? fetchWQITrend(id, location, from, to).catch(() => null) : Promise.resolve(null),
    ]);

    if (!Array.isArray(wqiData) || wqiData.length === 0) {
      return { ...EMPTY_CARDS, series: [], summaryNote: 'No samples for this station in the selected window.' };
    }

    const valid = wqiData.filter(d => d.wqi !== null && d.wqi !== undefined && !Number.isNaN(d.wqi));
    if (valid.length === 0) {
      return { ...EMPTY_CARDS, series: [], summaryNote: 'No index values in the selected window.' };
    }

    const values = valid.map(d => d.wqi);
    const average = values.reduce((a, b) => a + b, 0) / values.length;
    const latest = valid[0];
    const worst = valid.reduce((acc, item) => (item.wqi > acc.wqi ? item : acc), valid[0]);
    const coliform = coliformFlag(latest.total_coliform);

    const series = [...wqiData]
      .reverse()
      .map(d => ({
        ts: d.timestamp ? new Date(d.timestamp).getTime() : null,
        date: d.timestamp ? new Date(d.timestamp).toLocaleDateString() : '',
        value: d.wqi,
      }))
      .filter(d => d.ts !== null && d.value !== null && d.value !== undefined && !Number.isNaN(d.value));

    const summaryNote = `${valid.length} samples in window | latest ${formatDay(latest.timestamp)} | mean ${formatNumber(average)} | worst ${formatNumber(worst.wqi)} on ${formatDay(worst.timestamp)}`;

    const cpcb = latest.cpcb_use_class || null;
    const anomalyEntries = anomalySummary?.summary
      ? Object.values(anomalySummary.summary).filter(s => !location || s.location === location)
      : [];
    const doAnomalies = anomalyEntries.find(s => s.parameter === 'do');
    const wqiAnomalies = anomalyEntries.find(s => s.parameter === 'wqi');
    const anomalyTotal = (doAnomalies?.anomalies ?? 0) + (wqiAnomalies?.anomalies ?? 0);
    const anomalyCaption = `full history, robust z > 3: DO ${doAnomalies?.anomalies ?? 0} of ${doAnomalies?.total ?? 0}, WQI ${wqiAnomalies?.anomalies ?? 0} of ${wqiAnomalies?.total ?? 0} samples flagged`;
    const rankEntry = Array.isArray(summary) ? summary.find(r => r.location === location) : null;
    let rankCaption;
    if (rankEntry?.rank_pct !== null && rankEntry?.rank_pct !== undefined) {
      rankCaption = `worse than ${rankEntry.rank_pct}% of ${rankEntry.rank_of} stations (based on ${rankEntry.rank_samples} samples)`;
    } else if (!rankEntry || !('rank_of' in rankEntry)) {
      rankCaption = 'rank unavailable for this window';
    } else if (rankEntry.scored_count >= 3) {
      rankCaption = 'rank unavailable: fewer than 2 stations with 3+ samples in the window';
    } else {
      rankCaption = `no rank: needs at least 3 samples in the window (has ${rankEntry.scored_count ?? 0})`;
    }

    return {
      currentWQI: `${Math.round(latest.wqi)}`,
      category: latest.wqi_category || categoryForValue(latest.wqi),
      avgWQI: `${Math.round(average)}`,
      averageCategory: categoryForValue(average),
      maxWQI: `${Math.round(worst.wqi)}`,
      worstCategory: worst.wqi_category || categoryForValue(worst.wqi),
      coliformValue: latest.total_coliform !== null && latest.total_coliform !== undefined ? formatNumber(latest.total_coliform) : '-',
      coliformStatus: coliform.status,
      coliformLevel: coliform.level,
      coliformCaption: coliform.caption,
      cpcbClass: cpcb ? (cpcb.class ? `Class ${cpcb.class}` : 'Not classifiable') : '-',
      cpcbStatus: cpcb ? (cpcb.partial ? 'partial' : (cpcb.approximate ? 'approximate' : null)) : null,
      cpcbClassLevel: cpcb ? CPCB_CLASS_COLORS[cpcb.class] : undefined,
      cpcbClassCaption: cpcbCaption(cpcb),
      anomalyCount: `${anomalyTotal}`,
      anomalyStatus: anomalyTotal > 0 ? 'flagged samples' : null,
      anomalyCaption,
      series,
      summaryNote,
      latestCaption: `core set (pH/DO/BOD) as of ${formatDay(latest.timestamp)}`,
      averageCaption: `core set | unweighted mean of ${valid.length} samples | ${rankCaption}`,
      worstCaption: `on ${formatDay(worst.timestamp)}`,
      breakdown: (
        <>
          {buildBreakdown(latest, formatDay(latest.timestamp), trend)}
          {buildOutlooks(forecasts, location)}
        </>
      ),
      chartNote: <AboutThisIndex />,
    };
  };

  if (datasetsLoading) {
    return <DashboardLoadingSkeleton cardCount={cardsConfig.length} label="Loading water quality data" />;
  }

  if (!datasetId) {
    return (
      <div className="glass-card p-12 rounded-2xl text-center">
        <p className="text-slate-600">No water quality dataset uploaded yet.</p>
        <p className="text-sm text-slate-500 mt-2">Datasets containing water quality columns appear here — upload one (select WQI on the Upload page).</p>
      </div>
    );
  }

  if (!summaryLoaded) {
    return <DashboardLoadingSkeleton cardCount={cardsConfig.length} label="Loading water quality data" />;
  }

  return (
    <AnalyticsDashboardTemplate
      key={datasetId}
      title="Water Quality (WQI) Dashboard"
      fetchFn={fetchWQIDataForTemplate}
      cardsConfig={cardsConfig}
      chartConfig={chartConfig}
      datasetId={datasetId}
      location={location}
      locations={locations}
      onLocationChange={setLocation}
      dateBounds={dateBounds}
      datasetOptions={datasets.map(d => ({ id: d.id, label: datasetDisplayLabel(d) }))}
      onDatasetChange={setSelectedId}
      windowDays={365}
      aboutLabel="About this index"
      legendItems={LEGEND_ITEMS}
    />
  );
};

export default WQIDashboard;
