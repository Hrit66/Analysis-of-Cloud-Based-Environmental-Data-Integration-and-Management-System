import React from 'react';
import DatasetStatusBadge from './DatasetStatusBadge';
import { Eye, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

const DatasetTable = ({ datasets = [], onDelete }) => {
  const navigate = useNavigate();

  const handleView = (type) => {
    navigate(`/${type.toLowerCase()}`);
  };

  const formatType = (type) => {
    const map = { 'air_quality': 'AQI', 'water_quality': 'WQI', 'temperature': 'TEMP', 'rainfall': 'RAIN' };
    return map[type] || type.toUpperCase();
  };

  const formatStatus = (status) => {
    const map = { 'completed': 'ready', 'processing': 'processing', 'failed': 'failed', 'uploaded': 'raw' };
    return map[status] || status.toLowerCase();
  };

  if (!datasets.length) {
    return (
      <div className="p-12 text-center text-slate-500">
        No datasets found. Upload your first dataset to get started.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm text-slate-600">
        <thead className="bg-white/40 text-slate-700 font-medium border-b border-white/50 backdrop-blur-md">
          <tr>
            <th className="px-6 py-4">Name</th>
            <th className="px-6 py-4">Type</th>
            <th className="px-6 py-4">Uploaded At</th>
            <th className="px-6 py-4">Rows</th>
            <th className="px-6 py-4">Status</th>
            <th className="px-6 py-4 text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/40">
          {datasets.map((dataset) => (
            <tr key={dataset.id} className="hover:bg-white/50 transition-colors">
              <td className="px-6 py-4 font-medium text-slate-900">{dataset.filename}</td>
              <td className="px-6 py-4">
                <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium bg-white/60 text-slate-800 shadow-sm">
                  {formatType(dataset.dataset_type)}
                </span>
              </td>
              <td className="px-6 py-4">{new Date(dataset.created_at).toLocaleDateString()}</td>
              <td className="px-6 py-4">{dataset.row_count?.toLocaleString() ?? '-'}</td>
              <td className="px-6 py-4">
                <DatasetStatusBadge status={formatStatus(dataset.status)} />
              </td>
              <td className="px-6 py-4 text-right">
                <div className="flex justify-end gap-2">
                  <button 
                    onClick={() => handleView(formatType(dataset.dataset_type))}
                    disabled={dataset.status !== 'completed'}
                    className={`p-1.5 rounded-md ${
                      dataset.status === 'completed' 
                        ? 'text-blue-600 hover:bg-blue-50' 
                        : 'text-slate-300 cursor-not-allowed'
                    }`}
                    title="View Analysis"
                  >
                    <Eye className="w-4 h-4" />
                  </button>
                  <button 
                    onClick={() => onDelete?.(dataset.id)}
                    className="p-1.5 rounded-md text-red-500 hover:bg-red-50"
                    title="Delete Dataset"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default DatasetTable;
