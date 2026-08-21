import React from 'react';
import DatasetStatusBadge from './DatasetStatusBadge';
import { Eye, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

// Mock data
const MOCK_DATASETS = [
  { id: '1', name: 'Delhi_AQI_2023.csv', type: 'AQI', uploadedAt: '2023-10-15T10:30:00Z', status: 'ready', rowCount: 14500 },
  { id: '2', name: 'Yamuna_WQI_Q3.xlsx', type: 'WQI', uploadedAt: '2023-10-16T14:20:00Z', status: 'processing', rowCount: 8200 },
  { id: '3', name: 'Global_Temp_Anomalies.json', type: 'TEMP', uploadedAt: '2023-10-17T09:15:00Z', status: 'failed', rowCount: 1024 },
  { id: '4', name: 'Mumbai_Rainfall_2022.csv', type: 'RAIN', uploadedAt: '2023-10-18T11:45:00Z', status: 'raw', rowCount: 365 },
];

const DatasetTable = () => {
  const navigate = useNavigate();

  const handleView = (type) => {
    navigate(`/${type.toLowerCase()}`);
  };

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
          {MOCK_DATASETS.map((dataset) => (
            <tr key={dataset.id} className="hover:bg-white/50 transition-colors">
              <td className="px-6 py-4 font-medium text-slate-900">{dataset.name}</td>
              <td className="px-6 py-4">
                <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium bg-white/60 text-slate-800 shadow-sm">
                  {dataset.type}
                </span>
              </td>
              <td className="px-6 py-4">{new Date(dataset.uploadedAt).toLocaleDateString()}</td>
              <td className="px-6 py-4">{dataset.rowCount.toLocaleString()}</td>
              <td className="px-6 py-4">
                <DatasetStatusBadge status={dataset.status} />
              </td>
              <td className="px-6 py-4 text-right">
                <div className="flex justify-end gap-2">
                  <button 
                    onClick={() => handleView(dataset.type)}
                    disabled={dataset.status !== 'ready'}
                    className={`p-1.5 rounded-md ${
                      dataset.status === 'ready' 
                        ? 'text-blue-600 hover:bg-blue-50' 
                        : 'text-slate-300 cursor-not-allowed'
                    }`}
                    title="View Analysis"
                  >
                    <Eye className="w-4 h-4" />
                  </button>
                  <button 
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
