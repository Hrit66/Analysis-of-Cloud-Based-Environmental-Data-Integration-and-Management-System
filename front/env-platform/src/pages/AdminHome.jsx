import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity, AlertTriangle, ArrowRight, Building2, Clock, Database,
  HardDrive, ShieldAlert, ShieldCheck, Users,
} from 'lucide-react';
import { API_BASE, authFetch } from '../lib/api';

const fmtDate = (value) => {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString();
};

const fmtBytes = (value) => {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
};

const statusTone = (status) => {
  if (['success', 'ok', 'active'].includes(status)) return 'bg-emerald-50 text-emerald-700 border-emerald-200';
  if (['failure', 'error', 'critical'].includes(status)) return 'bg-red-50 text-red-700 border-red-200';
  return 'bg-amber-50 text-amber-700 border-amber-200';
};

const readError = async (res, fallback) => {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') return body.detail;
  } catch {
    // ignore
  }
  return fallback;
};

const AdminHome = () => {
  const [overview, setOverview] = useState(null);
  const [audit, setAudit] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [overviewRes, auditRes] = await Promise.all([
          authFetch(`${API_BASE}/admin/overview`),
          authFetch(`${API_BASE}/admin/audit?limit=8`),
        ]);
        if (!overviewRes.ok) throw new Error(await readError(overviewRes, 'Could not load overview'));
        if (!auditRes.ok) throw new Error(await readError(auditRes, 'Could not load audit events'));
        const [overviewData, auditData] = await Promise.all([overviewRes.json(), auditRes.json()]);
        if (!cancelled) {
          setOverview(overviewData);
          setAudit(auditData);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return <div className="mx-auto max-w-7xl py-10 text-slate-600">Loading platform overview...</div>;
  }

  const cards = [
    {
      label: 'Pending user approvals',
      value: overview?.pending_users ?? 0,
      icon: Users,
      tone: 'text-amber-600 bg-amber-50',
      to: '/admin?tab=approvals',
    },
    {
      label: 'Pending organizations',
      value: overview?.pending_organizations ?? 0,
      icon: Building2,
      tone: 'text-amber-600 bg-amber-50',
      to: '/admin?tab=orgs',
    },
    {
      label: 'Storage used',
      value: `${overview?.storage?.percent ?? 0}%`,
      detail: `${fmtBytes(overview?.storage?.used_bytes)} of ${fmtBytes(overview?.storage?.limit_bytes)}`,
      icon: HardDrive,
      tone: 'text-blue-600 bg-blue-50',
      to: '/admin?tab=usage',
    },
    {
      label: 'Failed logins (24h)',
      value: overview?.failed_logins_24h ?? 0,
      icon: ShieldAlert,
      tone: overview?.failed_logins_24h ? 'text-red-600 bg-red-50' : 'text-emerald-600 bg-emerald-50',
      to: '/admin?tab=audit',
    },
  ];

  return (
    <div className="mx-auto max-w-7xl space-y-6 pb-12">
      <div className="glass-panel p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-500">
              <ShieldCheck className="h-4 w-4 text-blue-600" /> Platform administration
            </p>
            <h1 className="mt-2 text-3xl font-bold text-slate-900">Overview</h1>
            <p className="mt-1 text-sm text-slate-500">
              Approvals, storage, and the latest platform activity.
            </p>
          </div>
          <Link
            to="/admin"
            className="flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Open Admin <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <Link key={card.label} to={card.to} className="glass-panel p-5 transition-transform hover:-translate-y-0.5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{card.label}</p>
                <p className="mt-2 text-3xl font-bold text-slate-900">{card.value}</p>
                {card.detail && <p className="mt-1 text-xs text-slate-500">{card.detail}</p>}
              </div>
              <span className={`rounded-xl p-2 ${card.tone}`}><card.icon className="h-5 w-5" /></span>
            </div>
          </Link>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="glass-panel p-6 lg:col-span-2">
          <div className="flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <Activity className="h-5 w-5 text-blue-600" /> Recent audit events
            </h2>
            <Link to="/admin?tab=audit" className="text-sm text-blue-600 hover:underline">View all</Link>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr><th className="py-2">Time</th><th>Event</th><th>Actor</th><th>Result</th></tr>
              </thead>
              <tbody>
                {audit.items.map((item) => (
                  <tr key={item.id} className="border-t border-white/50">
                    <td className="py-2 text-xs text-slate-500">{fmtDate(item.created_at)}</td>
                    <td className="text-xs font-medium text-slate-800">{item.action}</td>
                    <td className="text-xs text-slate-600">{item.actor_email || item.actor_id || '-'}</td>
                    <td>
                      <span className={`rounded-full border px-2 py-0.5 text-xs ${statusTone(item.result || 'success')}`}>
                        {item.result || 'success'}
                      </span>
                    </td>
                  </tr>
                ))}
                {audit.items.length === 0 && (
                  <tr><td colSpan={4} className="py-4 text-sm text-slate-500">No audit events yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-6">
          <div className="glass-panel p-6">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <Database className="h-5 w-5 text-blue-600" /> Storage
            </h2>
            <div className="mt-4 h-3 overflow-hidden rounded-full bg-slate-200">
              <div
                className={`h-full ${(overview?.storage?.percent ?? 0) >= 80 ? 'bg-amber-500' : 'bg-blue-600'}`}
                style={{ width: `${Math.min(100, overview?.storage?.percent || 0)}%` }}
              />
            </div>
            <p className="mt-2 text-sm text-slate-600">
              {fmtBytes(overview?.storage?.used_bytes)} of {fmtBytes(overview?.storage?.limit_bytes)} used
            </p>
            <Link to="/admin?tab=datasets" className="mt-3 inline-block text-sm text-blue-600 hover:underline">
              Review dataset metadata
            </Link>
          </div>

          <div className="glass-panel p-6">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <AlertTriangle className="h-5 w-5 text-amber-600" /> Attention
            </h2>
            {overview?.alerts?.length > 0 ? (
              <div className="mt-3 space-y-2">
                {overview.alerts.map((alert, index) => (
                  <div key={index} className={`rounded-xl border px-3 py-2 text-sm ${statusTone(alert.level)}`}>
                    {alert.message}
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm text-emerald-700">No active alerts.</p>
            )}
            {overview?.admins_without_mfa?.length > 0 && (
              <p className="mt-3 text-sm text-amber-700">
                {overview.admins_without_mfa.length} platform admin(s) still need MFA.
              </p>
            )}
            <p className="mt-3 flex items-center gap-2 text-xs text-slate-500">
              <Clock className="h-3.5 w-3.5" /> Updated just now
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminHome;
