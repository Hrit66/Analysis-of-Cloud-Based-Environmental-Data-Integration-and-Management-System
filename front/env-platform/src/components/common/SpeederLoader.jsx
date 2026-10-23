import React from 'react';
import './SpeederLoader.css';

const SpeederLoader = ({ label = 'Loading dashboard' }) => (
  <div className="speeder-loader" role="status" aria-live="polite">
    <div className="speeder-loader__stage" aria-hidden="true">
      <div className="speeder-loader__ship">
        <span>
          <span></span>
          <span></span>
          <span></span>
          <span></span>
        </span>
        <div className="speeder-loader__base">
          <span></span>
          <div className="speeder-loader__face"></div>
        </div>
      </div>
      <div className="speeder-loader__fazers">
        <span></span>
        <span></span>
        <span></span>
        <span></span>
      </div>
    </div>
    {label && <span className="speeder-loader__label">{label}</span>}
  </div>
);

export default SpeederLoader;
