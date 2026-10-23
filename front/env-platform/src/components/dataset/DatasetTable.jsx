import React, { useState } from 'react';
import DatasetStatusBadge from './DatasetStatusBadge';
import { Eye, Trash2, ChevronDown, ChevronUp, Pencil, Check, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { datasetDisplayLabel } from '../../lib/api';

const formatReportChips = (report) => {
  if (!report) return [];
  const chips = [];
  const sumValues = (obj) => Object.values(obj || {}).reduce((a, b) => a + b, 0);

  chips.push(`Rows read: ${report.rows_read ?? 0}`);
  chips.push(`Rows kept: ${report.rows_kept ?? 0}`);
  const invalidTs = report.rows_dropped?.invalid_timestamp;
  if (invalidTs) chips.push(`Dropped ${invalidTs} (invalid timestamps)`);
  if (report.duplicates_removed) chips.push(`Duplicates removed: ${report.duplicates_removed}`);
  if (report.layout === 'long_pivoted') chips.push('Long format pivoted to wide');
  const renamed = Object.keys(report.columns_renamed || {}).length;
  if (renamed) chips.push(`Columns renamed: ${renamed}`);
  const missing = sumValues(report.missing_markers_found);
  if (missing) chips.push(`Missing markers: ${missing}`);
  const sentinels = sumValues(report.sentinel_values_detected);
  if (sentinels) chips.push(`Sentinel values cleared: ${sentinels}`);
  const outOfRange = sumValues(report.out_of_range_values_set_to_nan);
  if (outOfRange) chips.push(`Out-of-range values cleared: ${outOfRange}`);
  const bdlConverted = sumValues(report.below_detection_limit_converted);
  if (bdlConverted) chips.push(`Below-detection-limit imputed: ${bdlConverted}`);
  const bdlMissing = sumValues(report.below_detection_limit_treated_missing);
  if (bdlMissing) chips.push(`Below-detection-limit marked missing: ${bdlMissing}`);
  if (report.ambiguous_date_strings) chips.push(`Ambiguous dates parsed: ${report.ambiguous_date_strings}`);
  return chips;
};

const DatasetTable = ({ datasets = [], onDelete, onRename, deletingId = null }) => {
  const navigate = useNavigate();
  const [expandedId, setExpandedId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editingValue, setEditingValue] = useState('');

  const startEditing = (dataset) => {
    setEditingId(dataset.id);
    setEditingValue(datasetDisplayLabel(dataset));
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditingValue('');
  };

  const saveEditing = (dataset) => {
    const name = editingValue.trim();
    if (!name) return;
    setEditingId(null);
    setEditingValue('');
    onRename?.(dataset.id, name);
  };

  const handleView = (type) => {
    const routeMap = {
      'air_quality': 'aqi',
      'water_quality': 'wqi',
      'temperature': 'temperature',
      'rainfall': 'rainfall',
    };
    navigate(`/${routeMap[type] || type.toLowerCase()}`);
  };

  const formatType = (dataset) => {
    const type = dataset.dataset_type;
    const isImd = Boolean(dataset.cleaning_report?.source_format?.startsWith('imd'));
    if (isImd && (type === 'rainfall' || type === 'temperature')) return 'WEATHER (IMD)';
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
          {datasets.map((dataset) => {
            const hasDetails = Boolean(dataset.cleaning_report || dataset.error_message);
            const isExpanded = expandedId === dataset.id;
            const chips = formatReportChips(dataset.cleaning_report);

            return (
              <React.Fragment key={dataset.id}>
                <tr className="hover:bg-white/50 transition-colors">
                  <td className="px-6 py-4 font-medium text-slate-900">
                    {editingId === dataset.id ? (
                      <div className="flex items-center gap-1.5">
                        <input
                          autoFocus
                          value={editingValue}
                          maxLength={80}
                          onChange={(e) => setEditingValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') saveEditing(dataset);
                            if (e.key === 'Escape') cancelEditing();
                          }}
                          className="w-52 px-2 py-1 rounded-md border border-slate-300 bg-white text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-200"
                        />
                        <button
                          onClick={() => saveEditing(dataset)}
                          className="p-1.5 rounded-md text-green-600 hover:bg-green-50"
                          title="Save name"
                        >
                          <Check className="w-4 h-4" />
                        </button>
                        <button
                          onClick={cancelEditing}
                          className="p-1.5 rounded-md text-slate-400 hover:bg-slate-100"
                          title="Cancel rename"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ) : (
                      datasetDisplayLabel(dataset)
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium bg-white/60 text-slate-800 shadow-sm">
                      {formatType(dataset)}
                    </span>
                  </td>
                  <td className="px-6 py-4">{new Date(dataset.created_at).toLocaleDateString()}</td>
                  <td className="px-6 py-4">{dataset.row_count?.toLocaleString() ?? '-'}</td>
                  <td className="px-6 py-4">
                    <DatasetStatusBadge status={formatStatus(dataset.status)} />
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex justify-end gap-2">
                      {hasDetails && (
                        <button
                          onClick={() => setExpandedId(isExpanded ? null : dataset.id)}
                          className="p-1.5 rounded-md text-slate-500 hover:bg-slate-100"
                          title="Data quality report"
                        >
                          {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                        </button>
                      )}
                      <button
                        onClick={() => startEditing(dataset)}
                        className="p-1.5 rounded-md text-slate-500 hover:bg-slate-100"
                        title="Rename dataset"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button 
                        onClick={() => handleView(dataset.dataset_type)}
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
                        disabled={deletingId === dataset.id}
                        className={`p-1.5 rounded-md ${
                          deletingId === dataset.id
                            ? 'text-slate-300 cursor-not-allowed'
                            : 'text-red-500 hover:bg-red-50'
                        }`}
                        title={deletingId === dataset.id ? 'Deleting…' : 'Delete Dataset'}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
                {isExpanded && (
                  <tr className="bg-white/30">
                    <td colSpan={6} className="px-6 py-4">
                      {dataset.error_message && (
                        <p className="text-red-600 text-sm mb-3">Error: {dataset.error_message}</p>
                      )}
                      {chips.length > 0 && (
                        <div className="flex flex-wrap gap-2">
                          {chips.map((chip) => (
                            <span
                              key={chip}
                              className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-700"
                            >
                              {chip}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export default DatasetTable;
