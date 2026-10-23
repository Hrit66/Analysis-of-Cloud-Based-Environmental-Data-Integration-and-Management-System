import React from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';

const formatValue = (value, unit) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return `${Math.round(value * 10) / 10}${unit}`;
};

// Chart timestamps are epoch milliseconds. Daily samples are stored at IST
// midnight, which is 18:30 UTC the previous day, so format explicitly in
// Asia/Kolkata instead of the browser's local zone.
export const formatDateLabel = (value) => {
  if (value === null || value === undefined || value === '') return '';
  const numeric = typeof value === 'number' || /^\d+$/.test(String(value));
  const date = new Date(numeric ? Number(value) : value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
};

export const ChartTooltip = ({ active, payload, label, unit = '', timeAxis = false }) => {
  if (!active || !payload || payload.length === 0) return null;
  const header = timeAxis ? formatDateLabel(label) : label;

  const rows = [...payload]
    .filter(row => row.value !== null && row.value !== undefined)
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));

  return (
    <div className="rounded-lg border border-slate-200 bg-white/95 backdrop-blur-sm px-3 py-2 shadow-md">
      {header && <p className="text-xs text-slate-400 mb-1">{header}</p>}
      {rows.map((row, idx) => (
        <p key={idx} className="text-xs font-semibold" style={{ color: row.color || row.stroke || '#0f172a' }}>
          {row.name} {formatValue(row.value, unit)}
        </p>
      ))}
    </div>
  );
};

const TrendLineChart = ({ data, dataKey, color = '#3b82f6', yLabel, tooltipName, unit = '', extraLines = [], timeAxis = false }) => {
  return (
    <div className="h-80 w-full mt-4">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
          {timeAxis ? (
            <XAxis
              dataKey="ts"
              type="number"
              domain={['dataMin', 'dataMax']}
              scale="time"
              tickFormatter={formatDateLabel}
              minTickGap={50}
              axisLine={false}
              tickLine={false}
              tick={{ fill: '#64748b', fontSize: 12 }}
              dy={10}
            />
          ) : (
            <XAxis 
              dataKey="date" 
              axisLine={false}
              tickLine={false}
              tick={{ fill: '#64748b', fontSize: 12 }}
              dy={10}
            />
          )}
          <YAxis 
            domain={['auto', 'auto']}
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#64748b', fontSize: 12 }}
            label={{ value: yLabel, angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 12 }}
          />
          <Tooltip 
            content={<ChartTooltip unit={unit} timeAxis={timeAxis} />} 
            labelFormatter={timeAxis ? formatDateLabel : undefined}
          />
          <Legend 
            verticalAlign="top" 
            align="right" 
            height={28}
            iconType="plainline"
            wrapperStyle={{ fontSize: 12, color: '#64748b' }}
          />
          {extraLines.filter(line => !line.dotOnly).map(line => (
            <Line
              key={line.dataKey}
              type="linear"
              dataKey={line.dataKey}
              name={line.name}
              stroke={line.color}
              strokeWidth={1.5}
              strokeDasharray="4 4"
              legendType={line.legendType || 'line'}
              dot={false}
            />
          ))}
          <Line 
            type={timeAxis ? 'linear' : 'monotone'} 
            dataKey={dataKey} 
            name={tooltipName || dataKey}
            stroke={color} 
            strokeWidth={timeAxis ? 2 : 3}
            dot={timeAxis ? { r: 3, fill: color, strokeWidth: 0 } : false}
            activeDot={{ r: 6, strokeWidth: 0 }}
          />
          {extraLines.filter(line => line.dotOnly).map(line => (
            <Line
              key={line.dataKey}
              type="linear"
              dataKey={line.dataKey}
              name={line.name}
              stroke="none"
              legendType={line.legendType || 'circle'}
              dot={{ r: 4, fill: line.color, strokeWidth: 0 }}
              activeDot={{ r: 6, fill: line.color, strokeWidth: 0 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default TrendLineChart;
