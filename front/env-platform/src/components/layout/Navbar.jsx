import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { SlideTabs } from '../ui/slide-tabs';
import { 
  Home, UploadCloud, Database, Wind, Droplets, Thermometer, 
  CloudRain, AlertTriangle, FileText, LogOut, User 
} from 'lucide-react';
import { NotificationCenter } from '../ui/notification-center';

const Navbar = () => {
  const { user, logout } = useAuth();

  const navItems = [
    { name: 'Home', path: '/', icon: Home, color: 'text-indigo-500' },
    { name: 'Upload', path: '/upload', icon: UploadCloud, color: 'text-emerald-500' },
    { name: 'Datasets', path: '/datasets', icon: Database, color: 'text-violet-500' },
    { name: 'AQI', path: '/aqi', icon: Wind, color: 'text-teal-500' },
    { name: 'WQI', path: '/wqi', icon: Droplets, color: 'text-blue-500' },
    { name: 'Temp', path: '/temperature', icon: Thermometer, color: 'text-orange-500' },
    { name: 'Rain', path: '/rainfall', icon: CloudRain, color: 'text-sky-500' },
    { name: 'Anomalies', path: '/anomalies', icon: AlertTriangle, color: 'text-rose-500' },
    { name: 'Reports', path: '/reports', icon: FileText, color: 'text-fuchsia-500' },
  ];

  return (
    <nav className="glass-panel mx-6 mt-4 mb-2 rounded-2xl px-6 py-3 flex items-center justify-between z-20 sticky top-4">
      <div className="flex items-center gap-6 overflow-hidden">
        <h1 className="text-xl font-bold text-slate-800 flex items-center gap-2 shrink-0">
          <Database className="w-6 h-6 text-blue-600 drop-shadow-md" />
          <span className="hidden xl:inline">EnvPlatform</span>
        </h1>
        
        <div className="flex-1 overflow-x-auto hide-scrollbar pl-2 py-1">
          <SlideTabs tabs={navItems} />
        </div>
      </div>

      <div className="flex items-center gap-4 ml-4 shrink-0">
        <NotificationCenter />
        
        <div className="flex items-center gap-3 pl-0 sm:pl-4 sm:border-l border-white/50">
          <div className="hidden md:flex flex-col text-right">
            <span className="text-sm font-medium text-slate-700">{user?.name || 'User'}</span>
            <span className="text-xs text-slate-500">Admin</span>
          </div>
          <button 
            onClick={logout}
            className="w-8 h-8 bg-blue-100/50 hover:bg-red-100 hover:text-red-600 rounded-full flex items-center justify-center text-blue-700 font-bold transition-colors"
            title="Logout"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
