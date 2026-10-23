import React, { useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { UploadCloud, AlertCircle } from 'lucide-react';

const FileDropzone = ({ onDrop, multiple = false, hint, accept = {
  'text/csv': ['.csv'],
  'application/json': ['.json'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/vnd.ms-excel': ['.xls']
}, maxSize = 50 * 1024 * 1024 }) => { // 50MB fallback
  const handleDrop = useCallback((acceptedFiles, fileRejections) => {
    if (acceptedFiles.length > 0) {
      onDrop(multiple ? acceptedFiles : acceptedFiles[0]);
    }
    if (fileRejections.length > 0) {
      alert(fileRejections[0].errors[0].message);
    }
  }, [onDrop, multiple]);

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop: handleDrop,
    accept,
    maxSize,
    multiple
  });

  return (
    <div 
      {...getRootProps()} 
      className={`border-2 border-dashed rounded-2xl p-10 flex flex-col items-center justify-center cursor-pointer transition-all duration-300
        ${isDragActive ? 'border-blue-500 bg-blue-50/50' : 'border-white/60 hover:border-white/100 bg-white/40 backdrop-blur-sm hover:shadow-lg'}
        ${isDragReject ? 'border-red-500 bg-red-50/50' : ''}
      `}
    >
      <input {...getInputProps()} />
      
      {isDragReject ? (
        <AlertCircle className="w-12 h-12 text-red-500 mb-4" />
      ) : (
        <UploadCloud className={`w-12 h-12 mb-4 ${isDragActive ? 'text-blue-500' : 'text-slate-400'}`} />
      )}
      
      <p className="text-lg font-medium text-slate-700 mb-1">
        {isDragActive ? "Drop the file here..." : "Drag & drop a file here, or click to select"}
      </p>
      {hint !== null && (
        <p className="text-sm text-slate-500">
          {hint || (multiple ? 'Select the rain, tmax and tmin files (.csv)' : 'Supports .csv, .json, .xlsx')}
        </p>
      )}
    </div>
  );
};

export default FileDropzone;
