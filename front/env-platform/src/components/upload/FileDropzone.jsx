import React, { useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { UploadCloud, File, AlertCircle } from 'lucide-react';

const FileDropzone = ({ onDrop, accept = {
  'text/csv': ['.csv'],
  'application/json': ['.json'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/vnd.ms-excel': ['.xls']
}, maxSize = 20971520 }) => { // 20MB
  const handleDrop = useCallback((acceptedFiles, fileRejections) => {
    if (acceptedFiles.length > 0) {
      onDrop(acceptedFiles[0]);
    }
    if (fileRejections.length > 0) {
      alert(fileRejections[0].errors[0].message);
    }
  }, [onDrop]);

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop: handleDrop,
    accept,
    maxSize,
    multiple: false
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
      <p className="text-sm text-slate-500">
        Supports .csv, .json, .xlsx up to 20MB
      </p>
    </div>
  );
};

export default FileDropzone;
