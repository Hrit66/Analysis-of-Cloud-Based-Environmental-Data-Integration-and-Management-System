import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import FileDropzone from '../components/upload/FileDropzone';
import { FileText, CheckCircle2 } from 'lucide-react';

const UploadPage = () => {
  const [file, setFile] = useState(null);
  const [type, setType] = useState('AQI');
  const [status, setStatus] = useState('idle'); // idle, uploading, processing, ready
  const navigate = useNavigate();

  const handleDrop = (uploadedFile) => {
    setFile(uploadedFile);
  };

  const handleUpload = () => {
    if (!file) return;
    setStatus('uploading');
    
    // Mock API upload progress
    setTimeout(() => {
      setStatus('processing');
      // Mock processing
      setTimeout(() => {
        setStatus('ready');
      }, 2000);
    }, 1500);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Upload Dataset</h1>
        <p className="text-slate-600 mt-1">Upload environmental data for analysis and prediction.</p>
      </div>

      <div className="glass-panel p-8 rounded-2xl space-y-6 animate-fade-in-up">
        {status === 'idle' && (
          <>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">Dataset Type</label>
              <select 
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full border border-slate-300 rounded-md p-2.5 focus:ring-blue-500 focus:border-blue-500 bg-white"
              >
                <option value="AQI">Air Quality (AQI)</option>
                <option value="WQI">Water Quality (WQI)</option>
                <option value="TEMP">Temperature</option>
                <option value="RAIN">Rainfall</option>
              </select>
            </div>

            {!file ? (
              <FileDropzone onDrop={handleDrop} />
            ) : (
              <div className="border border-white/50 rounded-xl p-4 flex items-center justify-between bg-white/40 backdrop-blur-sm">
                <div className="flex items-center gap-3">
                  <FileText className="text-blue-500 w-8 h-8" />
                  <div>
                    <p className="font-medium text-slate-800">{file.name}</p>
                    <p className="text-xs text-slate-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                  </div>
                </div>
                <button 
                  onClick={() => setFile(null)}
                  className="text-sm text-red-600 hover:text-red-700 font-medium"
                >
                  Remove
                </button>
              </div>
            )}

            <div className="flex justify-end pt-4">
              <button
                onClick={handleUpload}
                disabled={!file}
                className={`px-4 py-2 rounded-md font-medium text-white transition-colors ${
                  file ? 'bg-blue-600 hover:bg-blue-700' : 'bg-slate-300 cursor-not-allowed'
                }`}
              >
                Upload & Process
              </button>
            </div>
          </>
        )}

        {(status === 'uploading' || status === 'processing') && (
          <div className="py-12 flex flex-col items-center justify-center space-y-4">
            <div className="w-12 h-12 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin"></div>
            <h3 className="text-lg font-medium text-slate-800">
              {status === 'uploading' ? 'Uploading dataset...' : 'Processing data...'}
            </h3>
            <p className="text-slate-500 text-sm text-center max-w-sm">
              {status === 'uploading' 
                ? 'Please wait while we securely upload your file.' 
                : 'Cleaning data, identifying anomalies, and generating predictions.'}
            </p>
          </div>
        )}

        {status === 'ready' && (
          <div className="py-12 flex flex-col items-center justify-center space-y-4 text-center">
            <div className="w-16 h-16 bg-green-100 text-green-600 rounded-full flex items-center justify-center mb-2">
              <CheckCircle2 className="w-8 h-8" />
            </div>
            <h3 className="text-xl font-bold text-slate-800">Dataset Ready!</h3>
            <p className="text-slate-600 max-w-sm">
              Your data has been processed successfully. You can now view the insights.
            </p>
            <div className="pt-4 flex gap-3">
              <button
                onClick={() => {
                  setFile(null);
                  setStatus('idle');
                }}
                className="px-4 py-2 border border-slate-300 rounded-md font-medium text-slate-700 hover:bg-slate-50"
              >
                Upload Another
              </button>
              <button
                onClick={() => navigate(`/${type.toLowerCase()}`)}
                className="px-4 py-2 rounded-md font-medium text-white bg-blue-600 hover:bg-blue-700"
              >
                View Analysis
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default UploadPage;
