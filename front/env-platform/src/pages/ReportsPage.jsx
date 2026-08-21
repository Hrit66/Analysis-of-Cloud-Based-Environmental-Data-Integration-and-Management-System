import React, { useState } from 'react';
import { Download, FileText, FileSpreadsheet } from 'lucide-react';

const ReportsPage = () => {
  const [params, setParams] = useState({
    aqi: true,
    wqi: false,
    temp: true,
    rain: false
  });
  
  const [dateRange, setDateRange] = useState({
    from: '2023-01-01',
    to: '2023-10-17'
  });
  
  const [dataset, setDataset] = useState('all');
  const [isGenerating, setIsGenerating] = useState(false);

  const handleExport = (format) => {
    setIsGenerating(true);
    // Mock API call to generate report blob
    setTimeout(() => {
      setIsGenerating(false);
      alert(`Successfully generated ${format.toUpperCase()} report! (Mock Download)`);
    }, 1500);
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Generate Reports</h1>
        <p className="text-slate-600 mt-1">Export your environmental data analysis to PDF or Excel formats.</p>
      </div>

      <div className="glass-panel rounded-2xl overflow-hidden animate-fade-in-up">
        <div className="p-6 space-y-8">
          
          {/* Dataset Selection */}
          <div>
            <h3 className="text-lg font-medium text-slate-800 mb-3">1. Select Dataset</h3>
            <select 
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              className="w-full sm:w-1/2 border border-slate-300 rounded-md p-2.5 focus:ring-blue-500 focus:border-blue-500 bg-white"
            >
              <option value="all">All Available Datasets</option>
              <option value="delhi">Delhi_AQI_2023.csv</option>
              <option value="yamuna">Yamuna_WQI_Q3.xlsx</option>
            </select>
          </div>

          {/* Parameters Selection */}
          <div>
            <h3 className="text-lg font-medium text-slate-800 mb-3">2. Select Parameters to Include</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="flex items-center space-x-3 p-3 border border-slate-200 rounded-md hover:bg-slate-50 cursor-pointer">
                <input 
                  type="checkbox" 
                  checked={params.aqi} 
                  onChange={() => setParams({...params, aqi: !params.aqi})}
                  className="h-4 w-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500"
                />
                <span className="font-medium text-slate-700">Air Quality Index (AQI)</span>
              </label>
              <label className="flex items-center space-x-3 p-3 border border-slate-200 rounded-md hover:bg-slate-50 cursor-pointer">
                <input 
                  type="checkbox" 
                  checked={params.wqi} 
                  onChange={() => setParams({...params, wqi: !params.wqi})}
                  className="h-4 w-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500"
                />
                <span className="font-medium text-slate-700">Water Quality Index (WQI)</span>
              </label>
              <label className="flex items-center space-x-3 p-3 border border-slate-200 rounded-md hover:bg-slate-50 cursor-pointer">
                <input 
                  type="checkbox" 
                  checked={params.temp} 
                  onChange={() => setParams({...params, temp: !params.temp})}
                  className="h-4 w-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500"
                />
                <span className="font-medium text-slate-700">Temperature</span>
              </label>
              <label className="flex items-center space-x-3 p-3 border border-slate-200 rounded-md hover:bg-slate-50 cursor-pointer">
                <input 
                  type="checkbox" 
                  checked={params.rain} 
                  onChange={() => setParams({...params, rain: !params.rain})}
                  className="h-4 w-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500"
                />
                <span className="font-medium text-slate-700">Rainfall</span>
              </label>
            </div>
          </div>

          {/* Date Range Selection */}
          <div>
            <h3 className="text-lg font-medium text-slate-800 mb-3">3. Date Range</h3>
            <div className="flex flex-col sm:flex-row items-center gap-4">
              <div className="w-full sm:w-auto">
                <label className="block text-sm text-slate-500 mb-1">From</label>
                <input 
                  type="date" 
                  value={dateRange.from}
                  onChange={(e) => setDateRange({...dateRange, from: e.target.value})}
                  className="w-full border border-slate-300 rounded-md p-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
                />
              </div>
              <div className="w-full sm:w-auto">
                <label className="block text-sm text-slate-500 mb-1">To</label>
                <input 
                  type="date" 
                  value={dateRange.to}
                  onChange={(e) => setDateRange({...dateRange, to: e.target.value})}
                  className="w-full border border-slate-300 rounded-md p-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Action Footer */}
        <div className="bg-white/30 backdrop-blur-md px-6 py-4 border-t border-white/40 flex flex-col sm:flex-row justify-end gap-3">
          <button
            onClick={() => handleExport('excel')}
            disabled={isGenerating}
            className="flex items-center justify-center gap-2 px-4 py-2 border border-green-600 text-green-700 rounded-md font-medium hover:bg-green-50 transition-colors disabled:opacity-50"
          >
            <FileSpreadsheet className="w-4 h-4" />
            Generate Excel
          </button>
          
          <button
            onClick={() => handleExport('pdf')}
            disabled={isGenerating}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {isGenerating ? (
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
            ) : (
              <FileText className="w-4 h-4" />
            )}
            Generate PDF Report
          </button>
        </div>
      </div>
    </div>
  );
};

export default ReportsPage;
