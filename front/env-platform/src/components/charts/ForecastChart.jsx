import React from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';

const ForecastChart = ({ historicalData = [], forecastData = [], dataKey, color = '#3b82f6', yLabel }) => {
  // Combine data for a continuous line, adding an isForecast flag
  const combinedData = [
    ...historicalData.map(d => ({ ...d, historical: d[dataKey] })),
    ...forecastData.map(d => ({ ...d, forecast: d[dataKey] }))
  ];

  return (
    <div className="h-80 w-full mt-4">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={combinedData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
          <XAxis 
            dataKey="date" 
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#64748b', fontSize: 12 }}
            dy={10}
          />
          <YAxis 
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#64748b', fontSize: 12 }}
            label={{ value: yLabel, angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 12 }}
          />
          <Tooltip 
            contentStyle={{ borderRadius: '8px', border: '1px solid #e2e8f0', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
            itemStyle={{ color: '#0f172a', fontWeight: 600 }}
          />
          <Legend verticalAlign="top" height={36}/>
          
          {/* Historical Line */}
          <Line 
            name="Historical Data"
            type="monotone" 
            dataKey="historical" 
            stroke={color} 
            strokeWidth={3}
            dot={false}
            activeDot={{ r: 6, strokeWidth: 0 }}
          />
          
          {/* Forecast Line - Dashed */}
          <Line 
            name="Predicted Forecast"
            type="monotone" 
            dataKey="forecast" 
            stroke={color} 
            strokeWidth={3}
            strokeDasharray="5 5"
            dot={false}
            activeDot={{ r: 6, strokeWidth: 0 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default ForecastChart;
