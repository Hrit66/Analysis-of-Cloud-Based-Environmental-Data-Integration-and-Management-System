import React from 'react';
import DatasetTable from '../components/dataset/DatasetTable';

const DatasetsPage = () => {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Datasets</h1>
        <p className="text-slate-600 mt-1">Manage your uploaded environmental datasets.</p>
      </div>
      
      <div className="glass-panel rounded-2xl overflow-hidden animate-fade-in-up">
        <DatasetTable />
      </div>
    </div>
  );
};

export default DatasetsPage;
