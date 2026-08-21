import React, { useState } from 'react';
import { AlertTriangle, Filter } from 'lucide-react';
import DatasetStatusBadge from '../components/dataset/DatasetStatusBadge'; // Reusing for severity colors if we want, or make a custom one

const MOCK_ANOMALIES = [
  { id: 1, timestamp: '2023-10-17 08:00:00', parameter: 'PM2.5 (AQI)', value: 350, expectedRange: '0 - 100', severity: 'High', dataset: 'Delhi_AQI_2023.csv' },
  { id: 2, timestamp: '2023-10-17 09:15:00', parameter: 'pH Level (WQI)', value: 4.2, expectedRange: '6.5 - 8.5', severity: 'Critical', dataset: 'Yamuna_WQI_Q3.xlsx' },
  { id: 3, timestamp: '2023-10-16 14:00:00', parameter: 'Temperature', value: 48, expectedRange: '20 - 40', severity: 'High', dataset: 'Global_Temp_Anomalies.json' },
  { id: 4, timestamp: '2023-10-15 11:30:00', parameter: 'PM10 (AQI)', value: 150, expectedRange: '0 - 100', severity: 'Medium', dataset: 'Delhi_AQI_2023.csv' },
];

const AnomaliesPage = () => {
  const [filter, setFilter] = useState('All');

  const filteredData = filter === 'All' ? MOCK_ANOMALIES : MOCK_ANOMALIES.filter(a => a.severity === filter);

  const getSeverityStyle = (severity) => {
    switch(severity) {
      case 'Critical': return 'bg-red-100 text-red-800 border-red-200';
      case 'High': return 'bg-orange-100 text-orange-800 border-orange-200';
      case 'Medium': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      default: return 'bg-slate-100 text-slate-800 border-slate-200';
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Detected Anomalies</h1>
          <p className="text-slate-600 mt-1">Review statistical outliers and parameter breaches.</p>
        </div>
        
        <div className="flex items-center gap-2 glass-card rounded-xl p-2 px-4 shadow-sm animate-fade-in-up">
          <Filter className="w-4 h-4 text-slate-500 ml-1" />
          <select 
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="text-sm text-slate-700 bg-transparent border-none outline-none focus:ring-0 pr-6"
          >
            <option value="All">All Severities</option>
            <option value="Critical">Critical</option>
            <option value="High">High</option>
            <option value="Medium">Medium</option>
          </select>
        </div>
      </div>

      <div className="glass-panel rounded-2xl overflow-hidden animate-fade-in-up" style={{ animationDelay: '100ms' }}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-600">
            <thead className="bg-white/40 text-slate-700 font-medium border-b border-white/50 backdrop-blur-md">
              <tr>
                <th className="px-6 py-4">Timestamp</th>
                <th className="px-6 py-4">Parameter</th>
                <th className="px-6 py-4">Value</th>
                <th className="px-6 py-4">Expected Range</th>
                <th className="px-6 py-4">Severity</th>
                <th className="px-6 py-4">Dataset</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {filteredData.map((anomaly) => (
                <tr key={anomaly.id} className="hover:bg-slate-50 transition-colors cursor-pointer">
                  <td className="px-6 py-4">{new Date(anomaly.timestamp).toLocaleString()}</td>
                  <td className="px-6 py-4 font-medium text-slate-900">{anomaly.parameter}</td>
                  <td className="px-6 py-4 font-bold text-slate-800">{anomaly.value}</td>
                  <td className="px-6 py-4 text-slate-500">{anomaly.expectedRange}</td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${getSeverityStyle(anomaly.severity)}`}>
                      {anomaly.severity === 'Critical' && <AlertTriangle className="w-3 h-3 mr-1" />}
                      {anomaly.severity}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-blue-600 hover:underline">{anomaly.dataset}</td>
                </tr>
              ))}
              {filteredData.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-slate-500">
                    No anomalies found matching the current filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default AnomaliesPage;
