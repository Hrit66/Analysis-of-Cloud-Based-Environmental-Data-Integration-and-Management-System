import React from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

const Card = ({ title, value, trend, status, color }) => {
  
  const getTrendIcon = () => {
    if (!trend) return <Minus className="w-4 h-4 text-slate-400" />;
    if (trend.startsWith('+')) return <TrendingUp className="w-4 h-4 text-green-500" />;
    if (trend.startsWith('-')) return <TrendingDown className="w-4 h-4 text-red-500" />;
    return <Minus className="w-4 h-4 text-slate-400" />;
  };

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
    <div className="glass-card p-6 rounded-2xl flex flex-col justify-between animate-fade-in-up">
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-sm font-medium text-slate-500">{title}</h3>
        {status && (
          <span className={`text-xs px-2 py-1 rounded-md border font-medium ${getStatusColor()}`}>
            {status}
          </span>
        )}
      </div>
      
      <div className="flex items-end justify-between">
        <div className="text-3xl font-bold text-slate-800">{value}</div>
        
        {trend && (
          <div className="flex items-center gap-1 text-sm font-medium">
            {getTrendIcon()}
            <span className={
              trend.startsWith('+') ? 'text-green-600' : 
              trend.startsWith('-') ? 'text-red-600' : 'text-slate-500'
            }>
              {trend}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

export default Card;
