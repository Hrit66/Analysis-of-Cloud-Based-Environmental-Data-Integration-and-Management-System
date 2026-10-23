import React from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import { ChartTooltip, formatDateLabel } from './TrendLineChart';

const TrendBarChart = ({ data, dataKey, color = '#3b82f6', yLabel, tooltipName, unit = '', timeAxis = false }) => {
  return (
    <div className="h-80 w-full mt-4">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
          {timeAxis ? (
            <XAxis
              dataKey="ts"
              type="number"
              domain={['dataMin', 'dataMax']}
              scale="time"
              tickFormatter={formatDateLabel}
              minTickGap={40}
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
            domain={[0, 'auto']}
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#64748b', fontSize: 12 }}
            label={{ value: yLabel, angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 12 }}
          />
          <Tooltip content={<ChartTooltip unit={unit} timeAxis={timeAxis} />} cursor={{ fill: 'rgba(148, 163, 184, 0.15)' }} />
          <Legend
            verticalAlign="top"
            align="right"
            height={28}
            iconType="square"
            wrapperStyle={{ fontSize: 12, color: '#64748b' }}
          />
          <Bar
            dataKey={dataKey}
            name={tooltipName || dataKey}
            fill={color}
            radius={[2, 2, 0, 0]}
            maxBarSize={14}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default TrendBarChart;
