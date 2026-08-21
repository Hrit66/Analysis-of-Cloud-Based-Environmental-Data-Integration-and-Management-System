import React, { useState, useRef, useEffect } from 'react';
import { getSvgPath } from 'figma-squircle';
import { cn } from '../../lib/utils';

export function Squircle({ 
  children, 
  className, 
  cornerRadius = 32, 
  cornerSmoothing = 1, 
  ...props 
}) {
  const containerRef = useRef(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!containerRef.current) return;
    
    // We use a ResizeObserver to get the exact pixel dimensions
    // so figma-squircle can calculate the perfect G2 curvature path.
    const observer = new ResizeObserver((entries) => {
      for (let entry of entries) {
        setSize({
          width: entry.target.offsetWidth,
          height: entry.target.offsetHeight,
        });
      }
    });
    
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const svgPath = size.width > 0 && size.height > 0
    ? getSvgPath({ 
        width: size.width, 
        height: size.height, 
        cornerRadius, 
        cornerSmoothing 
      })
    : '';

  return (
    <div
      ref={containerRef}
      className={cn("relative", className)}
      style={{
        clipPath: svgPath ? `path('${svgPath}')` : 'none',
        // Fallback for before JS runs or if clipPath fails
        borderRadius: svgPath ? '0' : `${cornerRadius}px`
      }}
      {...props}
    >
      {children}
    </div>
  );
}

// A wrapper component to preserve drop shadows when using clip-path
export function SquircleCard({
  children,
  className,
  squircleClassName,
  cornerRadius = 32,
  cornerSmoothing = 1,
  ...props
}) {
  return (
    <div 
      className={cn("drop-shadow-2xl", className)}
      {...props}
    >
      <Squircle 
        cornerRadius={cornerRadius} 
        cornerSmoothing={cornerSmoothing}
        className={squircleClassName}
      >
        {children}
      </Squircle>
    </div>
  );
}
