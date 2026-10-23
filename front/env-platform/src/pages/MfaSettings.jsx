import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Copy, KeyRound, ShieldCheck, ShieldOff } from 'lucide-react';
import { useAuth } from '../context/useAuth';
import { API_BASE, authFetch } from '../lib/api';

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

const MfaSettings = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [setupData, setSetupData] = useState(null);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const startSetup = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await authFetch(`${API_BASE}/auth/mfa/setup-authenticated`, { method: 'POST' });
      if (!res.ok) throw new Error(await readError(res, 'Could not start MFA setup'));
      setSetupData(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const enableMfa = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const res = await authFetch(`${API_BASE}/auth/mfa/enable-authenticated`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      if (!res.ok) throw new Error(await readError(res, 'Could not enable MFA'));
      navigate('/login', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const disableMfa = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const res = await authFetch(`${API_BASE}/auth/mfa/disable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password, code }),
      });
      if (!res.ok) throw new Error(await readError(res, 'Could not disable MFA'));
      navigate('/login', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const copySecret = async () => {
    try {
      await navigator.clipboard.writeText(setupData.secret);
      setCopied(true);
      setNotice('Secret copied.');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('Could not copy the secret. Copy it manually.');
    }
  };

  return (
    <div className="mx-auto max-w-2xl py-8">
      <div className="glass-panel p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-500">
              <ShieldCheck className="h-4 w-4 text-blue-600" /> Account security
            </p>
            <h1 className="mt-2 text-2xl font-bold text-slate-900">Multi-factor authentication</h1>
            <p className="mt-1 text-sm text-slate-500">
              Add a time-based one-time code from your authenticator app.
            </p>
          </div>
          <span className={`rounded-full border px-3 py-1 text-xs font-medium ${user?.mfa_enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
            {user?.mfa_enabled ? 'Enabled' : 'Not enabled'}
          </span>
        </div>

        {error && <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        {notice && <div className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div>}

        {user?.mfa_enabled ? (
          <form className="mt-6 space-y-4" onSubmit={disableMfa}>
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Disabling MFA will sign you out of this session. If your organization or platform policy requires MFA, you will be prompted to set it up again at login.
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Current password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="mt-1 block w-full rounded-xl border border-white/60 bg-white/40 p-2.5 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">Authenticator code</label>
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                minLength={6}
                maxLength={8}
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
                className="mt-1 block w-full rounded-xl border border-white/60 bg-white/40 p-2.5 text-sm tracking-widest"
              />
            </div>
            <button type="submit" disabled={busy} className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-50">
              <ShieldOff className="h-4 w-4" /> {busy ? 'Disabling...' : 'Disable MFA'}
            </button>
          </form>
        ) : !setupData ? (
          <div className="mt-6">
            <button onClick={startSetup} disabled={busy} className="flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              <KeyRound className="h-4 w-4" /> {busy ? 'Starting...' : 'Set up MFA'}
            </button>
          </div>
        ) : (
          <div className="mt-6 space-y-5">
            <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-600">
              <li>Open your authenticator app and add a new account.</li>
              <li>Enter this secret key manually.</li>
              <li>Enter the 6-digit code below to finish.</li>
            </ol>
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/60 bg-white/50 px-4 py-3">
              <code className="break-all text-sm font-semibold tracking-wider text-slate-900">{setupData.secret}</code>
              <button type="button" onClick={copySecret} className="ml-auto flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-white">
                {copied ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <details className="text-xs text-slate-500">
              <summary className="cursor-pointer">Authenticator URI</summary>
              <p className="mt-2 break-all rounded-lg bg-slate-100 p-2 font-mono">{setupData.otpauth_uri}</p>
            </details>
            <form className="space-y-3" onSubmit={enableMfa}>
              <label className="block text-sm font-medium text-slate-700">Authenticator code</label>
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                minLength={6}
                maxLength={8}
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
                className="block w-full rounded-xl border border-white/60 bg-white/40 p-2.5 text-sm tracking-widest"
              />
              <button type="submit" disabled={busy} className="flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
                <ShieldCheck className="h-4 w-4" /> {busy ? 'Enabling...' : 'Enable MFA'}
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
};

export default MfaSettings;
