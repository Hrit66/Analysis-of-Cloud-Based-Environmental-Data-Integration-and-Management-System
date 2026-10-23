import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/useAuth';
import { SlideTabs } from '../ui/slide-tabs';
import {
  Home, UploadCloud, Database, Wind, Droplets, Thermometer,
  CloudRain, AlertTriangle, FileText, LogOut, Building2, ShieldCheck,
  ChevronDown, KeyRound, Bell, BellOff,
} from 'lucide-react';
import NotificationBell from '../ui/NotificationBell';
import BrandLogo from '../common/BrandLogo';

const NAV_ITEMS = [
  { key: 'home', name: 'Home', path: '/', icon: Home, color: 'text-indigo-500' },
  { key: 'upload', name: 'Upload', path: '/upload', icon: UploadCloud, color: 'text-emerald-500' },
  { key: 'datasets', name: 'Datasets', path: '/datasets', icon: Database, color: 'text-violet-500' },
  { key: 'aqi', name: 'AQI', path: '/aqi', icon: Wind, color: 'text-teal-500' },
  { key: 'wqi', name: 'WQI', path: '/wqi', icon: Droplets, color: 'text-blue-500' },
  { key: 'temperature', name: 'Temp', path: '/temperature', icon: Thermometer, color: 'text-orange-500' },
  { key: 'rainfall', name: 'Rain', path: '/rainfall', icon: CloudRain, color: 'text-sky-500' },
  { key: 'anomalies', name: 'Anomalies', path: '/anomalies', icon: AlertTriangle, color: 'text-rose-500' },
  { key: 'reports', name: 'Reports', path: '/reports', icon: FileText, color: 'text-fuchsia-500' },
  { key: 'organization', name: 'Organization', path: '/organization', icon: Building2, color: 'text-cyan-600' },
  { key: 'admin', name: 'Admin', path: '/admin', icon: ShieldCheck, color: 'text-red-500' },
];

const ANALYSIS_KEYS = NAV_ITEMS
  .filter((item) => !['organization', 'admin'].includes(item.key))
  .map((item) => item.key);

const Navbar = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (accountRef.current && !accountRef.current.contains(event.target)) {
        setAccountOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const fallbackNavigation = user?.platform_role === 'platform_admin'
    ? ['home', 'admin']
    : [...ANALYSIS_KEYS, ...(user?.org_role === 'org_admin' ? ['organization'] : [])];
  const allowed = new Set(
    Array.isArray(user?.navigation) && user.navigation.length > 0
      ? user.navigation
      : fallbackNavigation,
  );
  const navItems = NAV_ITEMS.filter((item) => allowed.has(item.key));

  const goTo = (path) => {
    setAccountOpen(false);
    navigate(path);
  };

  const handleLogout = async () => {
    setAccountOpen(false);
    await logout();
    navigate('/login', { replace: true });
  };

  const initial = (user?.name || user?.email || 'U').charAt(0).toUpperCase();
  const roleLabel = user?.platform_role === 'platform_admin'
    ? 'Platform admin'
    : user?.org_role?.replace('_', ' ') || user?.account_type?.replace('_', ' ') || 'Member';

  return (
    <nav className="glass-panel mx-6 mt-4 mb-2 rounded-2xl px-6 py-3 flex items-center justify-between z-20 sticky top-4">
      <div className="flex items-center gap-6 overflow-hidden">
        <h1 aria-label="EnvPlatform" className="text-xl font-bold text-slate-800 flex items-center gap-2 shrink-0">
          <BrandLogo alt="" className="h-9 w-9" />
          <span aria-hidden="true" className="hidden xl:inline">EnvPlatform</span>
        </h1>

        <div className="flex-1 overflow-x-auto hide-scrollbar pl-2 py-1">
          <SlideTabs tabs={navItems} />
        </div>
      </div>

      <div className="flex items-center gap-3 ml-4 shrink-0">
        <NotificationBell />

        <div className="relative" ref={accountRef}>
          <button
            onClick={() => setAccountOpen((open) => !open)}
            className="flex items-center gap-2 rounded-full border border-white/60 bg-white/50 py-1 pl-1 pr-2 text-left hover:bg-white/80 transition-colors"
            aria-label="Account menu"
            aria-expanded={accountOpen}
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">
              {initial}
            </span>
            <span className="hidden md:flex flex-col pr-1">
              <span className="max-w-32 truncate text-sm font-medium text-slate-700">{user?.name || 'User'}</span>
              <span className="text-xs capitalize text-slate-500">{roleLabel}</span>
            </span>
            <ChevronDown className={`h-4 w-4 text-slate-500 transition-transform ${accountOpen ? 'rotate-180' : ''}`} />
          </button>

          {accountOpen && (
            <div className="absolute right-0 mt-3 w-56 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_10px_40px_-10px_rgba(0,0,0,0.15)] z-50">
              <div className="border-b border-slate-100 px-4 py-3">
                <p className="truncate text-sm font-medium text-slate-900">{user?.name || 'User'}</p>
                <p className="truncate text-xs text-slate-500">{user?.email}</p>
              </div>
              <button onClick={() => goTo('/change-password')} className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm text-slate-700 hover:bg-slate-50">
                <KeyRound className="h-4 w-4 text-slate-500" /> Change password
              </button>
              <button onClick={() => goTo('/mfa')} className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm text-slate-700 hover:bg-slate-50">
                <ShieldCheck className="h-4 w-4 text-slate-500" /> MFA
                <span className="ml-auto text-xs text-slate-400">{user?.mfa_enabled ? 'On' : 'Off'}</span>
              </button>
              <button onClick={() => goTo('/notifications')} className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm text-slate-700 hover:bg-slate-50">
                <Bell className="h-4 w-4 text-slate-500" /> Notifications
              </button>
              <button onClick={() => goTo('/notifications/preferences')} className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm text-slate-700 hover:bg-slate-50">
                <BellOff className="h-4 w-4 text-slate-500" /> Notification preferences
              </button>
              <button onClick={handleLogout} className="flex w-full items-center gap-3 border-t border-slate-100 px-4 py-3 text-left text-sm text-red-600 hover:bg-red-50">
                <LogOut className="h-4 w-4" /> Logout
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
