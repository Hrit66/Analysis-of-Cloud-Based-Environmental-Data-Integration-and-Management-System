import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/useAuth';
import { API_BASE, authHeaders } from '../lib/api';
import {
  Activity, AlertTriangle, Building2, Check, Clock, Database, Download,
  HardDrive, KeyRound, Lock, LogOut, RefreshCw, Settings, ShieldAlert,
  ShieldCheck, Trash2, Unlock, Users, X,
} from 'lucide-react';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'approvals', label: 'User approvals' },
  { id: 'orgs', label: 'Organization applications' },
  { id: 'users', label: 'All users' },
  { id: 'datasets', label: 'Datasets' },
  { id: 'audit', label: 'Audit log' },
  { id: 'usage', label: 'Usage' },
  { id: 'settings', label: 'Settings' },
];

const ACCOUNT_TYPES = ['student', 'researcher', 'govt_agency', 'global_org'];
const ORG_ROLES = ['viewer', 'analyst', 'org_admin'];
const PLATFORM_ROLES = ['user', 'platform_admin'];
const AUDIT_EVENTS = [
  'auth.login', 'auth.login_failed', 'auth.refresh_reuse', 'auth.refresh_race',
  'auth.register', 'auth.email_verified', 'auth.verification_sent',
  'auth.password_reset', 'auth.password_reset_requested', 'auth.password_changed',
  'auth.mfa_enabled', 'auth.mfa_disabled', 'auth.mfa_failed', 'auth.mfa_setup_started',
  'auth.onboarding_completed', 'auth.user_approved', 'auth.user_rejected',
  'auth.user_updated', 'auth.bootstrap_admin',
  'admin.user_updated', 'admin.force_logout', 'admin.user_unlocked',
  'admin.password_reset_sent', 'admin.dataset_published', 'admin.dataset_unpublished',
  'admin.dataset_deleted', 'admin.dataset_source_updated', 'admin.settings_updated',
  'org.applied', 'org.approved', 'org.rejected', 'org.info_requested',
  'org.contact_verified', 'org.invite_created', 'org.invite_accepted',
  'org.invite_revoked', 'org.member_removed', 'org.member_role_updated',
  'org.suspended', 'org.reinstated', 'org.settings_updated', 'org.admin_setup',
  'dataset.deleted', 'dataset.renamed', 'dataset.publish_requested',
  'dataset.source_tag_updated', 'report.exported',
];

const fmtDate = (value) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  const parts = new Intl.DateTimeFormat('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'Asia/Kolkata',
  }).formatToParts(date);
  const get = (type) => parts.find((part) => part.type === type)?.value || '';
  return `${get('day')} ${get('month')} ${get('year')}, ${get('hour')}:${get('minute')} IST`;
};

const toUtcIso = (value) => {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString();
};

const fmtBytes = (value) => {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
};

const statusTone = (status) => {
  if (['active', 'verified', 'completed', 'success', 'ok'].includes(status)) {
    return 'bg-emerald-50 text-emerald-700 border-emerald-200';
  }
  if (['suspended', 'rejected', 'failed', 'failure', 'error'].includes(status)) {
    return 'bg-red-50 text-red-700 border-red-200';
  }
  return 'bg-amber-50 text-amber-700 border-amber-200';
};

const readError = async (res, fallback) => {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((item) => item.msg).join(' ');
  } catch {
    // ignore
  }
  return fallback;
};

const adminFetch = async (path, options = {}) => {
  const res = await fetch(`${API_BASE}/admin${path}`, {
    ...options,
    headers: authHeaders({ 'Content-Type': 'application/json', ...(options.headers || {}) }),
  });
  if (!res.ok) throw new Error(await readError(res, 'Admin request failed'));
  return res.status === 204 ? null : res.json();
};

const StatCard = ({ label, value, detail, tone = 'slate', icon: Icon }) => (
  <div className="rounded-2xl border border-white/60 bg-white/50 p-4 shadow-sm">
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
        <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
        {detail && <p className="mt-1 text-xs text-slate-500">{detail}</p>}
      </div>
      {Icon && (
        <span className={`rounded-xl p-2 ${tone === 'red' ? 'bg-red-50 text-red-600' : tone === 'amber' ? 'bg-amber-50 text-amber-600' : 'bg-blue-50 text-blue-600'}`}>
          <Icon className="h-5 w-5" />
        </span>
      )}
    </div>
  </div>
);

const AdminReviewPage = () => {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab');
  const [tab, setTabState] = useState(
    TABS.some((item) => item.id === requestedTab) ? requestedTab : 'overview',
  );
  const setTab = useCallback((id) => {
    setTabState(id);
    setSearchParams({ tab: id }, { replace: true });
  }, [setSearchParams]);
  const [overview, setOverview] = useState(null);
  const [users, setUsers] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [audit, setAudit] = useState({ items: [], total: 0 });
  const [usage, setUsage] = useState(null);
  const [settings, setSettings] = useState(null);
  const [settingsForm, setSettingsForm] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [userSearch, setUserSearch] = useState('');
  const [userFilters, setUserFilters] = useState({ status: '', platform_role: '', account_type: '' });
  const [datasetSearch, setDatasetSearch] = useState('');
  const [auditFilters, setAuditFilters] = useState({
    actor: '', event: '', result: '', target: '', date_from: '', date_to: '',
  });
  const [orgFilters, setOrgFilters] = useState({ status: '', domain: '' });

  const loadAudit = useCallback(async (filters = auditFilters) => {
    const params = new URLSearchParams();
    ['actor', 'event', 'result', 'target'].forEach((key) => {
      if (filters[key]) params.append(key, filters[key]);
    });
    if (filters.date_from) params.append('date_from', toUtcIso(filters.date_from));
    if (filters.date_to) params.append('date_to', toUtcIso(filters.date_to));
    params.append('limit', '200');
    const data = await adminFetch(`/audit?${params.toString()}`);
    setAudit(data);
  }, [auditFilters]);

  const loadAll = useCallback(async () => {
    try {
      const [ov, userData, orgData, datasetData, auditData, usageData, settingsData] = await Promise.all([
        adminFetch('/overview'),
        adminFetch('/users'),
        fetch(`${API_BASE}/organizations/applications`, { headers: authHeaders() }).then(async (res) => {
          if (!res.ok) throw new Error(await readError(res, 'Could not load organization applications'));
          return res.json();
        }),
        adminFetch('/datasets'),
        adminFetch('/audit?limit=200'),
        adminFetch('/usage'),
        adminFetch('/settings'),
      ]);
      setOverview(ov);
      setUsers(userData.items || []);
      setOrgs(Array.isArray(orgData) ? orgData : []);
      setDatasets(datasetData.items || []);
      setAudit(auditData);
      setUsage(usageData);
      setSettings(settingsData);
      setSettingsForm({
        registration_mode: settingsData.registration_mode || 'open',
        allowed_domains: (settingsData.allowed_domains || []).join(', '),
        mfa_required: { ...(settingsData.mfa_required || {}) },
        quotas: Object.fromEntries(ACCOUNT_TYPES.map((type) => {
          const quota = settingsData.quotas?.[type] || {};
          return [type, {
            datasets: quota.datasets ?? 0,
            rows: quota.rows ?? 0,
            storage_mb: Math.round((quota.storage_bytes || 0) / (1024 * 1024)),
            exports_per_hour: quota.exports_per_hour ?? 0,
            api_keys: quota.api_keys ?? 0,
          }];
        })),
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const pendingUsers = useMemo(
    () => users.filter((item) => item.status === 'pending_approval'),
    [users],
  );
  const actionableOrgs = useMemo(
    () => orgs.filter((item) => ['pending', 'info_requested'].includes(item.status)),
    [orgs],
  );
  const filteredOrgs = useMemo(() => {
    const domain = orgFilters.domain.trim().toLowerCase();
    return orgs.filter((item) => {
      if (orgFilters.status && item.status !== orgFilters.status) return false;
      if (domain && !(item.domains || []).some((value) => String(value).toLowerCase().includes(domain))) {
        return false;
      }
      return true;
    });
  }, [orgs, orgFilters]);
  const userLabel = (userId) => {
    if (!userId) return null;
    const found = users.find((item) => item.id === String(userId));
    return found?.email || found?.full_name || String(userId);
  };
  const filteredUsers = useMemo(() => {
    const needle = userSearch.trim().toLowerCase();
    return users.filter((item) => {
      if (userFilters.status && item.status !== userFilters.status) return false;
      if (userFilters.platform_role && item.platform_role !== userFilters.platform_role) return false;
      if (userFilters.account_type && item.account_type !== userFilters.account_type) return false;
      if (!needle) return true;
      return [item.email, item.full_name, item.org_name, item.account_type]
        .some((value) => String(value || '').toLowerCase().includes(needle));
    });
  }, [users, userSearch, userFilters]);
  const filteredDatasets = useMemo(() => {
    const needle = datasetSearch.trim().toLowerCase();
    if (!needle) return datasets;
    return datasets.filter((item) => [item.filename, item.display_name, item.owner_email, item.org_name]
      .some((value) => String(value || '').toLowerCase().includes(needle)));
  }, [datasets, datasetSearch]);

  const runAction = async (message, action) => {
    setError('');
    setNotice('');
    try {
      await action();
      setNotice(message);
      await loadAll();
    } catch (err) {
      setError(err.message);
    }
  };

  const approveUser = async (item) => {
    const accountType = window.prompt('Account type: student or researcher', item.account_type || 'student');
    if (!accountType) return;
    if (!['student', 'researcher'].includes(accountType)) return setError('Choose student or researcher.');
    const reason = window.prompt('Reason for approval', 'Approved by platform administrator');
    if (!reason?.trim()) return;
    const res = await fetch(`${API_BASE}/auth/admin/users/${item.id}/approve`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ account_type: accountType, reason }),
    });
    if (!res.ok) return setError(await readError(res, 'Could not approve user'));
    setNotice(`${item.email} approved.`);
    await loadAll();
  };

  const rejectUser = async (item) => {
    const reason = window.prompt('Reason for rejection (required)');
    if (!reason?.trim()) return;
    const res = await fetch(`${API_BASE}/auth/admin/users/${item.id}/reject`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ reason }),
    });
    if (!res.ok) return setError(await readError(res, 'Could not reject user'));
    setNotice(`${item.email} rejected.`);
    await loadAll();
  };

  const approveOrg = (item) => {
    const reason = window.prompt('Approval note (required)', 'Approved by platform administrator');
    if (!reason?.trim()) return;
    return runAction(`${item.name} approved.`, () => fetch(`${API_BASE}/organizations/${item.id}/approve`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ note: reason }),
    }).then(async (res) => {
      if (!res.ok) throw new Error(await readError(res, 'Could not approve organization'));
    }));
  };

  const rejectOrg = (item) => {
    const reason = window.prompt('Reason for rejection (required)');
    if (!reason?.trim()) return;
    return runAction(`${item.name} rejected.`, () => fetch(`${API_BASE}/organizations/applications/${item.id}/reject`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ reason }),
    }).then(async (res) => {
      if (!res.ok) throw new Error(await readError(res, 'Could not reject organization'));
    }));
  };

  const requestInfo = (item) => {
    const reason = window.prompt('What information is needed? (required)');
    if (!reason?.trim()) return;
    return runAction(`Information requested from ${item.name}.`, () => fetch(`${API_BASE}/organizations/applications/${item.id}/request-info`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ reason }),
    }).then(async (res) => {
      if (!res.ok) throw new Error(await readError(res, 'Could not request information'));
    }));
  };

  const updateUser = async (item, changes, label) => {
    if (item.id === user?.id) return setError('You cannot modify your own admin account.');
    const reason = window.prompt(`Reason for ${label} (required)`);
    if (!reason?.trim()) return;
    if (!window.confirm(`Apply "${label}" to ${item.email}?`)) return;
    await runAction(`${item.email}: ${label} applied.`, () => adminFetch(`/users/${item.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ ...changes, reason }),
    }));
  };

  const forceLogout = (item) => {
    if (!window.confirm(`Force logout ${item.email}? All sessions will be revoked.`)) return;
    return runAction(`${item.email} signed out everywhere.`, () => adminFetch(`/users/${item.id}/force-logout`, { method: 'POST' }));
  };

  const unlockUser = (item) => {
    if (!window.confirm(`Unlock ${item.email}?`)) return;
    return runAction(`${item.email} unlocked.`, () => adminFetch(`/users/${item.id}/unlock`, { method: 'POST' }));
  };

  const sendReset = (item) => {
    if (!window.confirm(`Send a password reset link to ${item.email}?`)) return;
    return runAction(`Password reset email queued for ${item.email}.`, () => adminFetch(`/users/${item.id}/send-password-reset`, { method: 'POST' }));
  };

  const editUserQuota = async (item) => {
    const fields = [
      ['datasets', 'Dataset limit'],
      ['rows', 'Row limit'],
      ['storage_bytes', 'Storage limit (bytes)'],
      ['exports_per_hour', 'Exports per hour'],
      ['api_keys', 'API key limit'],
    ];
    const current = item.quota_overrides || {};
    const next = {};
    for (const [field, label] of fields) {
      const raw = window.prompt(
        `${label}\nLeave blank to use the account-type default.`,
        current[field] ?? '',
      );
      if (raw === null) return;
      const value = raw.trim();
      if (!value) continue;
      if (!/^\d+$/.test(value)) return setError(`${label} must be a whole number.`);
      next[field] = Number(value);
    }
    const reason = window.prompt('Reason for quota change (required)', 'Custom quota');
    if (!reason?.trim()) return;
    await runAction(`Quota updated for ${item.email}.`, () => adminFetch(`/users/${item.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ quota_overrides: next, reason }),
    }));
  };

  const publishDataset = (item, action) => {
    const reason = window.prompt(`Reason to ${action} this dataset (required)`);
    if (!reason?.trim()) return;
    return runAction(`Dataset ${action === 'publish' ? 'published' : 'unpublished'}.`, () => adminFetch(`/datasets/${item.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ action, reason }),
    }));
  };

  const deleteDataset = (item) => {
    const reason = window.prompt('Policy reason for deleting this dataset (required)');
    if (!reason?.trim()) return;
    if (!window.confirm(`Permanently delete ${item.filename}? This cannot be undone.`)) return;
    return runAction('Dataset deleted.', () => adminFetch(`/datasets/${item.id}?reason=${encodeURIComponent(reason)}`, { method: 'DELETE' }));
  };

  const applyAuditFilters = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await loadAudit(auditFilters);
    } catch (err) {
      setError(err.message);
    }
  };

  const exportAuditCsv = () => {
    const header = [
      'time_ist', 'actor', 'event', 'target', 'target_label', 'target_type',
      'ip', 'user_agent', 'details', 'result',
    ];
    const rows = audit.items.map((item) => [
      fmtDate(item.created_at), item.actor_email || item.actor_id || '', item.action || '',
      item.target || '', item.target_label || '', item.target_type || '',
      item.ip || '', item.user_agent || '', JSON.stringify(item.metadata || {}),
      item.result || 'success',
    ]);
    const csv = [header, ...rows]
      .map((row) => row.map((value) => `"${String(value ?? '').replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'audit-log.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  const saveSettings = async () => {
    if (!settingsForm) return;
    const reason = window.prompt('Reason for this settings change (optional)') || '';
    const quotaOverrides = Object.fromEntries(ACCOUNT_TYPES.map((type) => {
      const quota = settingsForm.quotas[type];
      return [type, {
        datasets: Number(quota.datasets),
        rows: Number(quota.rows),
        storage_bytes: Math.round(Number(quota.storage_mb) * 1024 * 1024),
        exports_per_hour: Number(quota.exports_per_hour),
        api_keys: Number(quota.api_keys),
      }];
    }));
    await runAction('Settings saved.', () => adminFetch('/settings', {
      method: 'PATCH',
      body: JSON.stringify({
        registration_mode: settingsForm.registration_mode,
        allowed_domains: settingsForm.allowed_domains.split(/[\n,]+/).map((item) => item.trim()).filter(Boolean),
        mfa_required: settingsForm.mfa_required,
        quota_overrides: quotaOverrides,
        reason,
      }),
    }));
  };

  if (user?.platform_role !== 'platform_admin') {
    return <div className="p-6 text-slate-600">Platform administrator access is required.</div>;
  }

  const pendingOrgCount = actionableOrgs.length;
  const tabBadge = (id) => {
    if (id === 'approvals' && pendingUsers.length) return pendingUsers.length;
    if (id === 'orgs' && pendingOrgCount) return pendingOrgCount;
    return null;
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="glass-panel p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
              <ShieldAlert className="h-6 w-6 text-blue-600" /> Administration
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              Review accounts, manage platform data, and inspect the audit trail.
            </p>
          </div>
          <button
            onClick={() => { setError(''); setLoading(true); loadAll(); }}
            disabled={loading}
            className="flex items-center gap-2 rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm text-slate-600 hover:bg-white/80 disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {TABS.map((item) => (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium ${tab === item.id ? 'bg-blue-600 text-white' : 'bg-white/50 text-slate-600 hover:bg-white/80'}`}
            >
              {item.label}
              {tabBadge(item.id) && (
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${tab === item.id ? 'bg-white/20' : 'bg-amber-100 text-amber-700'}`}>
                  {tabBadge(item.id)}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}
      {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">{notice}</div>}
      {loading && !overview && <div className="text-slate-600">Loading administration data...</div>}

      {!loading && tab === 'overview' && overview && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="API" value={overview.api?.status || '-'} icon={Activity} />
            <StatCard label="Database" value={overview.database?.status || '-'} tone={overview.database?.status === 'ok' ? 'slate' : 'red'} icon={Database} />
            <StatCard label="Pending users" value={overview.pending_users ?? 0} icon={Users} tone="amber" />
            <StatCard label="Pending organizations" value={overview.pending_organizations ?? 0} icon={Building2} tone="amber" />
            <StatCard label="Failed jobs" value={overview.failed_jobs ?? 0} tone={overview.failed_jobs ? 'red' : 'slate'} icon={AlertTriangle} />
            <StatCard label="Failed logins (24h)" value={overview.failed_logins_24h ?? 0} tone={overview.failed_logins_24h >= 10 ? 'amber' : 'slate'} icon={Lock} />
            <StatCard label="Locked accounts" value={overview.locked_accounts ?? 0} icon={Lock} />
            <StatCard label="Storage" value={`${overview.storage?.percent ?? 0}%`} detail={`${fmtBytes(overview.storage?.used_bytes)} of ${fmtBytes(overview.storage?.limit_bytes)}`} tone={(overview.storage?.percent ?? 0) >= 80 ? 'amber' : 'slate'} icon={HardDrive} />
          </div>

          {overview.alerts?.length > 0 && (
            <div className="glass-panel p-5">
              <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900"><AlertTriangle className="h-5 w-5 text-amber-600" /> Alerts</h2>
              <div className="mt-3 space-y-2">
                {overview.alerts.map((alert, index) => (
                  <div key={index} className={`rounded-xl border px-3 py-2 text-sm ${statusTone(alert.level)}`}>
                    {alert.message}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            <div className="glass-panel p-5">
              <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900"><ShieldCheck className="h-5 w-5 text-blue-600" /> Security</h2>
              <div className="mt-3 space-y-2 text-sm text-slate-600">
                <p>Refresh-token reuse events (7 days): <strong>{overview.refresh_reuse_7d ?? 0}</strong></p>
                <p>Recent failed events (24h): <strong>{overview.recent_errors_24h ?? 0}</strong></p>
                <p>Last successful backup: <strong>{overview.last_backup_at ? fmtDate(overview.last_backup_at) : 'Not recorded'}</strong></p>
              </div>
              {overview.admins_without_mfa?.length > 0 ? (
                <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                  <p className="font-medium">Platform admins without MFA</p>
                  {overview.admins_without_mfa.map((item) => <p key={item.id}>{item.email}</p>)}
                </div>
              ) : (
                <p className="mt-4 text-sm text-emerald-700">All platform admins have MFA enabled.</p>
              )}
            </div>
            <div className="glass-panel p-5">
              <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900"><Clock className="h-5 w-5 text-blue-600" /> Quick actions</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <button onClick={() => setTab('approvals')} className="rounded-xl border border-white/60 bg-white/50 p-3 text-left text-sm hover:bg-white/80">Review pending users <span className="ml-1 font-semibold text-amber-700">{pendingUsers.length}</span></button>
                <button onClick={() => setTab('orgs')} className="rounded-xl border border-white/60 bg-white/50 p-3 text-left text-sm hover:bg-white/80">Review organizations <span className="ml-1 font-semibold text-amber-700">{pendingOrgCount}</span></button>
                <button onClick={() => setTab('audit')} className="rounded-xl border border-white/60 bg-white/50 p-3 text-left text-sm hover:bg-white/80">Open audit log</button>
                <button onClick={() => setTab('settings')} className="rounded-xl border border-white/60 bg-white/50 p-3 text-left text-sm hover:bg-white/80">Platform settings</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {!loading && tab === 'approvals' && (
        <div className="glass-panel space-y-3 p-6">
          {pendingUsers.length === 0 && <p className="text-sm text-slate-500">No pending user approvals.</p>}
          {pendingUsers.map((item) => (
            <div key={item.id} className="rounded-xl border border-white/60 bg-white/40 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-medium text-slate-900">{item.full_name || item.email}</p>
                  <p className="text-sm text-slate-500">{item.email} · {item.institution || 'No institution'} · {item.account_type || 'none'}</p>
                  <p className="text-xs text-slate-500">Requested {fmtDate(item.created_at)} · {item.review_reason || 'review required'}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => approveUser(item)} className="rounded-xl bg-emerald-600 px-3 py-2 text-sm text-white"><Check className="mr-1 inline h-4 w-4" />Approve</button>
                  <button onClick={() => rejectUser(item)} className="rounded-xl bg-red-600 px-3 py-2 text-sm text-white"><X className="mr-1 inline h-4 w-4" />Reject</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && tab === 'orgs' && (
        <div className="glass-panel space-y-3 p-6">
          <div className="flex flex-wrap items-center gap-2">
            <select value={orgFilters.status} onChange={(e) => setOrgFilters({ ...orgFilters, status: e.target.value })} className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-xs">
              <option value="">All statuses</option>
              <option value="pending">Pending</option>
              <option value="info_requested">Info requested</option>
              <option value="verified">Verified</option>
              <option value="rejected">Rejected</option>
              <option value="suspended">Suspended</option>
            </select>
            <input
              value={orgFilters.domain}
              onChange={(e) => setOrgFilters({ ...orgFilters, domain: e.target.value })}
              placeholder="Filter by domain"
              className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-xs"
            />
            <span className="text-xs text-slate-500">{filteredOrgs.length} application(s)</span>
          </div>
          {filteredOrgs.length === 0 && <p className="text-sm text-slate-500">No organization applications match these filters.</p>}
          {filteredOrgs.map((item) => {
            const actionable = ['pending', 'info_requested'].includes(item.status);
            return (
              <div key={item.id} className="rounded-xl border border-white/60 bg-white/40 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 font-medium text-slate-900">
                      <Building2 className="h-4 w-4" /> {item.name}
                      <span className={`rounded-full border px-2 py-0.5 text-xs ${statusTone(item.status)}`}>{item.status}</span>
                    </p>
                    <p className="text-sm text-slate-500">{item.type} · {item.country || 'No country'}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {(item.domains || []).map((domain) => (
                        <span key={domain} className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700">{domain}</span>
                      ))}
                      {(item.domains || []).length === 0 && <span className="text-xs text-slate-400">No domains</span>}
                    </div>
                    <p className="mt-1 text-sm text-slate-500">{item.contact_email} · {item.contact_verified ? 'contact verified' : 'contact not verified'}</p>
                    {item.purpose && <p className="mt-1 text-sm text-slate-600">{item.purpose}</p>}
                    {item.document_url && (
                      <a href={item.document_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-sm text-blue-600">
                        View authorization document
                      </a>
                    )}
                    <p className="mt-1 text-xs text-slate-500">
                      Requested by {userLabel(item.requested_by) || 'unknown'} · requested {fmtDate(item.created_at)}
                      {item.approved_at && ` · approved by ${userLabel(item.approved_by) || 'unknown'} ${fmtDate(item.approved_at)}`}
                      {item.rejected_at && ` · rejected by ${userLabel(item.rejected_by) || 'unknown'} ${fmtDate(item.rejected_at)}`}
                    </p>
                    {item.approval_note && <p className="mt-1 text-xs text-emerald-700">Note: {item.approval_note}</p>}
                    {item.rejected_reason && <p className="mt-1 text-xs text-red-700">Rejection reason: {item.rejected_reason}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {actionable && item.contact_verified && (
                      <button onClick={() => approveOrg(item)} className="rounded-xl bg-emerald-600 px-3 py-2 text-sm text-white"><Check className="mr-1 inline h-4 w-4" />Approve</button>
                    )}
                    {actionable && !item.contact_verified && (
                      <span className="flex items-center gap-1 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-700"><Clock className="h-4 w-4" /> Awaiting contact verification</span>
                    )}
                    {actionable && (
                      <>
                        <button onClick={() => requestInfo(item)} className="rounded-xl bg-amber-600 px-3 py-2 text-sm text-white">Request info</button>
                        <button onClick={() => rejectOrg(item)} className="rounded-xl bg-red-600 px-3 py-2 text-sm text-white"><X className="mr-1 inline h-4 w-4" />Reject</button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!loading && tab === 'users' && (
        <div className="glass-panel p-6">
          <div className="mb-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900"><Users className="h-5 w-5 text-blue-600" /> All users</h2>
              <input
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
                placeholder="Search email, name, organization..."
                className="w-full max-w-sm rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <select value={userFilters.status} onChange={(e) => setUserFilters({ ...userFilters, status: e.target.value })} className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-xs">
                <option value="">All statuses</option>
                <option value="active">Active</option>
                <option value="pending_verification">Pending verification</option>
                <option value="pending_approval">Pending approval</option>
                <option value="suspended">Suspended</option>
                <option value="rejected">Rejected</option>
              </select>
              <select value={userFilters.platform_role} onChange={(e) => setUserFilters({ ...userFilters, platform_role: e.target.value })} className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-xs">
                <option value="">All platform roles</option>
                <option value="user">User</option>
                <option value="platform_admin">Platform admin</option>
              </select>
              <select value={userFilters.account_type} onChange={(e) => setUserFilters({ ...userFilters, account_type: e.target.value })} className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-xs">
                <option value="">All account types</option>
                {ACCOUNT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
              <span className="self-center text-xs text-slate-500">{filteredUsers.length} user(s)</span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-2">User</th><th>Type</th><th>Organization</th><th>Role</th>
                  <th>Status</th><th>MFA</th><th>Last login</th><th>Storage</th><th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredUsers.map((item) => {
                  const isSelf = item.id === user?.id;
                  return (
                    <tr key={item.id} className="border-t border-white/50 align-top">
                      <td className="py-3">
                        <p className="font-medium text-slate-900">{item.full_name || item.email}</p>
                        <p className="text-xs text-slate-500">{item.email}</p>
                      </td>
                      <td>
                        <select value={item.account_type || ''} disabled={isSelf} onChange={(e) => updateUser(item, { account_type: e.target.value }, 'account type change')} className="rounded-lg border border-white/60 bg-white/50 px-2 py-1 text-xs disabled:opacity-50">
                          {!item.account_type && <option value="">Not set</option>}
                          {ACCOUNT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
                        </select>
                      </td>
                      <td className="text-xs">{item.org_name || '-'}<div className="text-slate-400">{item.org_role || ''}</div></td>
                      <td>
                        <select value={item.platform_role || 'user'} disabled={isSelf} onChange={(e) => updateUser(item, { platform_role: e.target.value }, 'platform role change')} className="rounded-lg border border-white/60 bg-white/50 px-2 py-1 text-xs disabled:opacity-50">
                          {PLATFORM_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
                        </select>
                        {item.org_id && (
                          <select value={item.org_role || 'viewer'} disabled={isSelf} onChange={(e) => updateUser(item, { org_role: e.target.value }, 'organization role change')} className="mt-1 rounded-lg border border-white/60 bg-white/50 px-2 py-1 text-xs disabled:opacity-50">
                            {ORG_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
                          </select>
                        )}
                      </td>
                      <td><span className={`rounded-full border px-2 py-0.5 text-xs ${statusTone(item.status)}`}>{item.status}</span></td>
                      <td>{item.mfa_enabled ? 'On' : 'Off'}</td>
                      <td className="text-xs">{fmtDate(item.last_login_at)}</td>
                      <td className="text-xs">{fmtBytes(item.storage_bytes)}<div className="text-slate-400">{item.dataset_count} dataset(s)</div>{Object.keys(item.quota_overrides || {}).length > 0 && <div className="text-blue-600">custom quota</div>}</td>
                      <td>
                        <div className="flex flex-wrap gap-1">
                          {item.status === 'active' ? (
                            <button onClick={() => updateUser(item, { status: 'suspended' }, 'deactivation')} disabled={isSelf} className="rounded-lg bg-red-50 px-2 py-1 text-xs text-red-700 disabled:opacity-40">Deactivate</button>
                          ) : (
                            <button onClick={() => updateUser(item, { status: 'active' }, 'reactivation')} disabled={isSelf} className="rounded-lg bg-emerald-50 px-2 py-1 text-xs text-emerald-700 disabled:opacity-40">Reactivate</button>
                          )}
                          <button onClick={() => forceLogout(item)} className="rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-700" title="Force logout"><LogOut className="inline h-3 w-3" /></button>
                          <button onClick={() => sendReset(item)} className="rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-700" title="Send password reset"><KeyRound className="inline h-3 w-3" /></button>
                          <button onClick={() => editUserQuota(item)} className="rounded-lg bg-blue-50 px-2 py-1 text-xs text-blue-700" title="Edit quota">Quotas</button>
                          {item.locked_until && <button onClick={() => unlockUser(item)} className="rounded-lg bg-amber-50 px-2 py-1 text-xs text-amber-700" title="Unlock account"><Unlock className="inline h-3 w-3" /></button>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && tab === 'datasets' && (
        <div className="glass-panel p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900"><HardDrive className="h-5 w-5 text-blue-600" /> Datasets</h2>
            <input value={datasetSearch} onChange={(e) => setDatasetSearch(e.target.value)} placeholder="Search filename, owner, organization..." className="w-full max-w-sm rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm" />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500"><tr><th className="py-2">Dataset</th><th>Owner</th><th>Organization</th><th>Rows</th><th>Size</th><th>Uploaded</th><th>Visibility</th><th>Source</th><th>Actions</th></tr></thead>
              <tbody>
                {filteredDatasets.map((item) => (
                  <tr key={item.id} className="border-t border-white/50 align-top">
                    <td className="py-3"><p className="font-medium text-slate-900">{item.display_name || item.filename}</p><p className="text-xs text-slate-500">{item.dataset_type} · {item.status}</p></td>
                    <td className="text-xs">{item.owner_name || '-'}<div className="text-slate-400">{item.owner_email || ''}</div></td>
                    <td className="text-xs">{item.org_name || '-'}</td>
                    <td>{Number(item.row_count || 0).toLocaleString()}</td>
                    <td>{fmtBytes(item.file_size_bytes)}</td>
                    <td className="text-xs">{fmtDate(item.created_at)}</td>
                    <td><span className={`rounded-full border px-2 py-0.5 text-xs ${statusTone(item.visibility === 'reference' ? 'active' : 'pending')}`}>{item.visibility}</span></td>
                    <td className="text-xs">{item.source_tag}</td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {item.visibility === 'reference' ? (
                          <button onClick={() => publishDataset(item, 'unpublish')} className="rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-700">Unpublish</button>
                        ) : (
                          <button onClick={() => publishDataset(item, 'publish')} className="rounded-lg bg-blue-50 px-2 py-1 text-xs text-blue-700">Publish</button>
                        )}
                        <button onClick={() => deleteDataset(item)} className="rounded-lg bg-red-50 px-2 py-1 text-xs text-red-700"><Trash2 className="inline h-3 w-3" /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && tab === 'audit' && (
        <div className="glass-panel p-6 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900"><ShieldCheck className="h-5 w-5 text-blue-600" /> Audit log</h2>
            <button onClick={exportAuditCsv} className="flex items-center gap-2 rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm"><Download className="h-4 w-4" /> Export CSV</button>
          </div>
          <form onSubmit={applyAuditFilters} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
            <input value={auditFilters.actor} onChange={(e) => setAuditFilters({ ...auditFilters, actor: e.target.value })} placeholder="Actor email or ID" className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm" />
            <input value={auditFilters.target} onChange={(e) => setAuditFilters({ ...auditFilters, target: e.target.value })} placeholder="Target ID" className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm" />
            <select value={auditFilters.event} onChange={(e) => setAuditFilters({ ...auditFilters, event: e.target.value })} className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm">
              <option value="">All events</option>
              {AUDIT_EVENTS.map((event) => <option key={event} value={event}>{event}</option>)}
            </select>
            <select value={auditFilters.result} onChange={(e) => setAuditFilters({ ...auditFilters, result: e.target.value })} className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm">
              <option value="">All results</option><option value="success">Success</option><option value="failure">Failure</option>
            </select>
            <input type="datetime-local" value={auditFilters.date_from} onChange={(e) => setAuditFilters({ ...auditFilters, date_from: e.target.value })} className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm" />
            <input type="datetime-local" value={auditFilters.date_to} onChange={(e) => setAuditFilters({ ...auditFilters, date_to: e.target.value })} className="rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm" />
            <button type="submit" className="rounded-xl bg-blue-600 px-3 py-2 text-sm text-white sm:col-span-2 lg:col-span-1">Apply filters</button>
          </form>
          <p className="text-xs text-slate-500">Showing {audit.items.length} of {audit.total} events. This log is read-only.</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500"><tr><th className="py-2">Time (IST)</th><th>Actor</th><th>Event</th><th>Target</th><th>IP / Device</th><th>Details</th><th>Result</th></tr></thead>
              <tbody>
                {audit.items.map((item) => (
                  <tr key={item.id} className="border-t border-white/50 align-top">
                    <td className="whitespace-nowrap py-2 text-xs">{fmtDate(item.created_at)}</td>
                    <td className="text-xs">{item.actor_email || item.actor_id || '-'}</td>
                    <td className="text-xs font-medium text-slate-800">{item.action}</td>
                    <td className="text-xs">
                      {item.target_label || item.target || '-'}
                      {item.target_label && item.target && (
                        <div className="font-mono text-[10px] text-slate-400">{item.target}</div>
                      )}
                      {item.target_type && (
                        <div className="text-[10px] uppercase tracking-wide text-slate-400">{item.target_type}</div>
                      )}
                    </td>
                    <td className="text-xs">
                      {item.ip || '-'}
                      {item.user_agent && (
                        <div className="max-w-[220px] truncate text-[10px] text-slate-400" title={item.user_agent}>
                          {item.user_agent}
                        </div>
                      )}
                    </td>
                    <td className="text-xs">
                      {item.metadata && Object.keys(item.metadata).length ? (
                        <details>
                          <summary className="cursor-pointer text-blue-600">View</summary>
                          <pre className="mt-1 max-w-xs whitespace-pre-wrap rounded bg-slate-50 p-2 text-[10px] text-slate-600">
                            {JSON.stringify(item.metadata, null, 2)}
                          </pre>
                        </details>
                      ) : '-'}
                    </td>
                    <td><span className={`rounded-full border px-2 py-0.5 text-xs ${statusTone(item.result || 'success')}`}>{item.result || 'success'}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && tab === 'usage' && usage && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard label="Storage used" value={fmtBytes(usage.used_bytes)} detail={`${usage.percent}% of ${fmtBytes(usage.limit_bytes)}`} tone={usage.alert ? 'amber' : 'slate'} icon={HardDrive} />
            <StatCard label="Top users" value={usage.top_users?.length ?? 0} icon={Users} />
            <StatCard label="Storage alert" value={usage.alert ? '80% reached' : 'Healthy'} tone={usage.alert ? 'amber' : 'slate'} icon={AlertTriangle} />
          </div>
          <div className="glass-panel p-6">
            <div className="h-3 overflow-hidden rounded-full bg-slate-200">
              <div className={`h-full ${usage.alert ? 'bg-amber-500' : 'bg-blue-600'}`} style={{ width: `${Math.min(100, usage.percent || 0)}%` }} />
            </div>
            <p className="mt-2 text-sm text-slate-600">{fmtBytes(usage.used_bytes)} of {fmtBytes(usage.limit_bytes)} used</p>
          </div>
          <div className="glass-panel p-6">
            <h2 className="text-lg font-semibold text-slate-900">Top users by storage</h2>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-slate-500"><tr><th className="py-2">User</th><th>Account type</th><th>Organization</th><th>Datasets</th><th>Storage</th></tr></thead>
                <tbody>
                  {usage.top_users?.map((item) => (
                    <tr key={item.id} className="border-t border-white/50">
                      <td className="py-2">{item.full_name || item.email}<div className="text-xs text-slate-500">{item.email}</div></td>
                      <td>{item.account_type || 'none'}</td>
                      <td>{item.org_name || '-'}</td>
                      <td>{item.dataset_count}</td>
                      <td>{fmtBytes(item.storage_bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="glass-panel p-6">
            <h2 className="text-lg font-semibold text-slate-900">Quotas by account type</h2>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-slate-500"><tr><th className="py-2">Type</th><th>Datasets</th><th>Rows</th><th>Storage</th><th>Exports/hour</th><th>API keys</th></tr></thead>
                <tbody>
                  {Object.entries(usage.quotas || {}).map(([type, quota]) => (
                    <tr key={type} className="border-t border-white/50">
                      <td className="py-2">{type}</td><td>{quota.datasets}</td><td>{Number(quota.rows).toLocaleString()}</td><td>{fmtBytes(quota.storage_bytes)}</td><td>{quota.exports_per_hour}</td><td>{quota.api_keys}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {!loading && tab === 'settings' && settingsForm && settings && (
        <div className="glass-panel p-6 space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900"><Settings className="h-5 w-5 text-blue-600" /> Platform settings</h2>
            <button onClick={saveSettings} className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white">Save settings</button>
          </div>
          <p className="text-xs text-slate-500">Last changed {settings.updated_at ? `${fmtDate(settings.updated_at)} by ${settings.updated_by_email || settings.updated_by || 'unknown'}` : 'never'}.</p>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-slate-700">Registration mode</label>
              <select value={settingsForm.registration_mode} onChange={(e) => setSettingsForm({ ...settingsForm, registration_mode: e.target.value })} className="mt-1 w-full rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm">
                <option value="open">Open</option><option value="invite_only">Invite only</option><option value="domain_allowlist">Domain allowlist</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Allowed email domains</label>
              <input value={settingsForm.allowed_domains} onChange={(e) => setSettingsForm({ ...settingsForm, allowed_domains: e.target.value })} placeholder="ac.in, edu, edu.in" className="mt-1 w-full rounded-xl border border-white/60 bg-white/50 px-3 py-2 text-sm" />
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-800">Require MFA</h3>
            <div className="mt-2 flex flex-wrap gap-4">
              {ACCOUNT_TYPES.map((type) => (
                <label key={type} className="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={Boolean(settingsForm.mfa_required[type])} onChange={(e) => setSettingsForm({ ...settingsForm, mfa_required: { ...settingsForm.mfa_required, [type]: e.target.checked } })} className="h-4 w-4 rounded border-slate-300 text-blue-600" />
                  {type}
                </label>
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-800">Quotas by account type</h3>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-slate-500"><tr><th className="py-2">Type</th><th>Datasets</th><th>Rows</th><th>Storage (MB)</th><th>Exports/hour</th><th>API keys</th></tr></thead>
                <tbody>
                  {ACCOUNT_TYPES.map((type) => (
                    <tr key={type} className="border-t border-white/50">
                      <td className="py-2">{type}</td>
                      {['datasets', 'rows', 'storage_mb', 'exports_per_hour', 'api_keys'].map((field) => (
                        <td key={field} className="py-1">
                          <input type="number" min="0" value={settingsForm.quotas[type][field]} onChange={(e) => setSettingsForm({ ...settingsForm, quotas: { ...settingsForm.quotas, [type]: { ...settingsForm.quotas[type], [field]: e.target.value } } })} className="w-24 rounded-lg border border-white/60 bg-white/50 px-2 py-1 text-xs" />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminReviewPage;
