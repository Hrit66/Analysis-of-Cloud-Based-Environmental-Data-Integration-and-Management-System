import React, { useState, useEffect } from 'react';
import DatasetTable from '../components/dataset/DatasetTable';
import SpeederLoader from '../components/common/SpeederLoader';
import { fetchDatasets, deleteDataset, renameDataset } from '../lib/api';

const DatasetsPage = () => {
  const [datasets, setDatasets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

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
    if (deletingId) return;
    if (!window.confirm('Delete this dataset and all its analytics?')) return;
    setDeletingId(id);
    try {
      await deleteDataset(id);
      setDatasets((previous) => previous.filter((dataset) => dataset.id !== id));
    } catch (err) {
      // The server may have deleted it despite a lost/aborted response.
      let deleted = false;
      try {
        const data = await fetchDatasets();
        setDatasets(data);
        deleted = !data.some((dataset) => dataset.id === id);
      } catch {
        // Keep the list as-is if the verification request also failed.
      }
      if (!deleted) alert('Failed to delete: ' + err.message);
    } finally {
      setDeletingId(null);
    }
  };

  const handleRename = async (id, displayName) => {
    try {
      await renameDataset(id, displayName);
      loadDatasets();
    } catch (err) {
      alert('Failed to rename: ' + err.message);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="space-y-2 animate-pulse">
          <div className="h-8 bg-slate-200 rounded w-40"></div>
          <div className="h-4 bg-slate-200 rounded w-72"></div>
        </div>
        <div className="glass-panel relative h-80 overflow-hidden rounded-2xl">
          <SpeederLoader label="Loading datasets" />
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
        <DatasetTable
          datasets={datasets}
          onDelete={handleDelete}
          onRename={handleRename}
          deletingId={deletingId}
        />
      </div>
    </div>
  );
};

export default DatasetsPage;
