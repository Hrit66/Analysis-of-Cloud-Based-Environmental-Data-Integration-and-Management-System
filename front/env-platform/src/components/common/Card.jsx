import React from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

const Card = ({ title, value, trend, status, color, trendTone = 'default', trendLabel, caption, onClick }) => {
  const isUp = trend ? trend.startsWith('+') : false;

  const getTrendIcon = () => {
    if (!trend) return <Minus className="w-4 h-4 text-slate-400" />;
    const className = trendTone === 'direction'
      ? (isUp ? 'text-orange-500' : 'text-sky-500')
      : (isUp ? 'text-green-500' : 'text-red-500');
    return isUp
      ? <TrendingUp className={`w-4 h-4 ${className}`} />
      : <TrendingDown className={`w-4 h-4 ${className}`} />;
  };

  const trendTextColor = trendTone === 'direction'
    ? (isUp ? 'text-orange-600' : 'text-sky-600')
    : (isUp ? 'text-green-600' : 'text-red-600');

  const getStatusColor = () => {
    switch(color) {
      case 'green': return 'text-green-600 bg-green-50 border-green-200';
      case 'yellow': return 'text-yellow-600 bg-yellow-50 border-yellow-200';
      case 'orange': return 'text-orange-600 bg-orange-50 border-orange-200';
      case 'red': return 'text-red-600 bg-red-50 border-red-200';
      case 'blue': return 'text-blue-600 bg-blue-50 border-blue-200';
      default: return 'text-slate-600 bg-slate-50 border-slate-200';
    }
  };

  return (
    <div
      className={`glass-card p-6 rounded-2xl flex flex-col justify-between animate-fade-in-up ${onClick ? 'cursor-pointer transition hover:shadow-md hover:-translate-y-0.5' : ''}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (event) => { if (event.key === 'Enter' || event.key === ' ') onClick(event); } : undefined}
    >
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-sm font-medium text-slate-500">{title}</h3>
        {status && (
          <span className={`text-xs px-2 py-1 rounded-md border font-medium ${getStatusColor()}`}>
            {status}
          </span>
        )}
      </div>
      
      <div className="flex items-end justify-between">
        <div>
          <div className="text-3xl font-bold text-slate-800">{value}</div>
          {caption && (
            <div className="text-[10px] text-slate-400 mt-1">{caption}</div>
          )}
        </div>
        
        {trend && (
          <div className="flex flex-col items-end">
            <div className="flex items-center gap-1 text-sm font-medium">
              {getTrendIcon()}
              <span className={trendTextColor}>{trend}</span>
            </div>
            {trendLabel && (
              <span className="text-[10px] text-slate-400 mt-0.5">{trendLabel}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default Card;
