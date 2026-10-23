import React from 'react';
import SpeederLoader from './SpeederLoader';

const gridClassFor = (count) => {
  if (count >= 6) return 'lg:grid-cols-6';
  if (count > 4) return 'lg:grid-cols-5';
  return 'lg:grid-cols-4';
};

const DashboardLoadingSkeleton = ({ cardCount = 5, label = 'Loading dashboard' }) => (
  <div className="space-y-6">
    <div className="space-y-6 animate-pulse">
      <div className="h-8 bg-slate-200 rounded w-64"></div>
      <div className={`grid grid-cols-1 md:grid-cols-2 ${gridClassFor(cardCount)} gap-6`}>
        {Array.from({ length: cardCount }, (_, i) => (
          <div key={i} className="h-32 bg-slate-200 rounded-xl"></div>
        ))}
      </div>
    </div>
    <div className="glass-panel relative h-96 overflow-hidden rounded-2xl">
      <SpeederLoader label={label} />
    </div>
  </div>
);

export default DashboardLoadingSkeleton;
