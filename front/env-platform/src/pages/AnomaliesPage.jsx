import React, { useState, useEffect } from 'react';
import { AlertTriangle, Filter } from 'lucide-react';
import { fetchAnomalies, fetchDatasets } from '../lib/api';

const AnomaliesPage = () => {
  const [anomalies, setAnomalies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('All');
  const [datasetId, setDatasetId] = useState(null);

  useEffect(() => {
    fetchDatasets()
      .then(data => {
        const completed = data.find(d => d.status === 'COMPLETED');
        if (completed) setDatasetId(completed.id);
      })
      .catch(console.error);
  }, []);

  useEffect(() => {
    if (!datasetId) return;
    setLoading(true);
    fetchAnomalies(datasetId)
      .then(data => {
        setAnomalies(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [datasetId]);

  const filteredData = filter === 'All' 
    ? anomalies 
    : anomalies.filter(a => a.is_anomaly && a.severity === filter);

  const getSeverityStyle = (severity) => {
    switch(severity) {
      case 'Critical': return 'bg-red-100 text-red-800 border-red-200';
      case 'High': return 'bg-orange-100 text-orange-800 border-orange-200';
      case 'Medium': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      default: return 'bg-slate-100 text-slate-800 border-slate-200';
    }
  };

  const getSeverity = (anomaly) => {
    if (!anomaly.is_anomaly) return 'Normal';
    const score = Math.abs(anomaly.anomaly_score);
    if (score > 0.5) return 'Critical';
    if (score > 0.3) return 'High';
    return 'Medium';
  };

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 bg-slate-200 rounded w-64"></div>
        <div className="glass-panel rounded-2xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead><tr><th className="px-6 py-4 h-12 bg-slate-200"></th></tr></thead>
              <tbody>
                {[1,2,3,4].map(i => <tr key={i}><td className="px-6 py-4 h-12 bg-slate-200"></td></tr>)}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="glass-card p-6 rounded-2xl text-center">
        <p className="text-red-600">Error: {error}</p>
        <p className="text-sm text-slate-500 mt-2">Make sure backend is running at {import.meta.env.VITE_API_URL}</p>
      </div>
    );
  }

  if (!datasetId) {
    return (
      <div className="glass-card p-12 rounded-2xl text-center">
        <p className="text-slate-600">No completed datasets found.</p>
        <p className="text-sm text-slate-500 mt-2">Upload a dataset first from the Upload page.</p>
      </div>
    );
  }

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
            <option value="All">All</option>
            <option value="Critical">Critical</option>
            <option value="High">High</option>
            <option value="Medium">Medium</option>
            <option value="Normal">Normal</option>
          </select>
        </div>
      </div>

      <div className="glass-panel rounded-2xl overflow-hidden animate-fade-in-up" style={{ animationDelay: '100ms' }}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-600">
            <thead className="bg-white/40 text-slate-700 font-medium border-b border-white/50 backdrop-blur-md">
              <tr>
                <th className="px-6 py-4">Timestamp</th>
                <th className="px-6 py-4">Location</th>
                <th className="px-6 py-4">Parameter</th>
                <th className="px-6 py-4">Value</th>
                <th className="px-6 py-4">Anomaly Score</th>
                <th className="px-6 py-4">Severity</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {filteredData.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-slate-500">
                    No anomalies found matching the current filter.
                  </td>
                </tr>
              ) : (
                filteredData.map((anomaly) => {
                  const severity = getSeverity(anomaly);
                  return (
                    <tr key={`${anomaly.timestamp}-${anomaly.parameter}-${anomaly.location}`} className="hover:bg-slate-50 transition-colors cursor-pointer">
                      <td className="px-6 py-4">{new Date(anomaly.timestamp).toLocaleString()}</td>
                      <td className="px-6 py-4 font-medium text-slate-900">{anomaly.location}</td>
                      <td className="px-6 py-4 font-medium text-slate-900">{anomaly.parameter.toUpperCase()}</td>
                      <td className="px-6 py-4 font-bold text-slate-800">{anomaly.value}</td>
                      <td className="px-6 py-4 text-slate-500">{anomaly.anomaly_score?.toFixed(3) ?? '-'}</td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${getSeverityStyle(severity)}`}>
                          {severity === 'Critical' && <AlertTriangle className="w-3 h-3 mr-1" />}
                          {severity}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default AnomaliesPage;
