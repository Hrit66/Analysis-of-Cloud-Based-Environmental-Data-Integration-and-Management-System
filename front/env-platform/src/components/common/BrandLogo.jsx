import React from 'react';
import logo from '../../assets/vr.png';

const BrandLogo = ({ className = 'h-16 w-16', alt = 'EnvPlatform' }) => (
  <img
    src={logo}
    alt={alt}
    className={`shrink-0 object-contain drop-shadow-md ${className}`}
  />
);

export default BrandLogo;
