import React, { useState, useEffect } from 'react';
import DatasetTable from '../components/dataset/DatasetTable';
import { fetchDatasets, deleteDataset } from '../lib/api';

const DatasetsPage = () => {
  const [datasets, setDatasets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadDatasets = async () => {
    setLoading(true);
    try {
      const data = await fetchDatasets();
      setDatasets(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDatasets();
  }, []);

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this dataset and all its analytics?')) return;
    try {
      await deleteDataset(id);
      loadDatasets();
    } catch (err) {
      alert('Failed to delete: ' + err.message);
    }
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
        <button onClick={loadDatasets} className="mt-4 px-4 py-2 bg-blue-600 text-white rounded">Retry</button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Datasets</h1>
        <p className="text-slate-600 mt-1">Manage your uploaded environmental datasets.</p>
      </div>
      
      <div className="glass-panel rounded-2xl overflow-hidden animate-fade-in-up">
        <DatasetTable datasets={datasets} onDelete={handleDelete} />
      </div>
    </div>
  );
};

export default DatasetsPage;
