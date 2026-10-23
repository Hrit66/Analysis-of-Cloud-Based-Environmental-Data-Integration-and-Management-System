import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { API_BASE } from '../lib/api';
import { Lock, User, Users } from 'lucide-react';

const AcceptInvite = () => {
  const [params] = useSearchParams();
  const token = params.get('token');
  const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: '', password: '', confirm: '', terms_accepted: false });
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!token) return setError('This invitation is missing its token.');
    if (form.password.length < 10) return setError('Password must be at least 10 characters.');
    if (form.password !== form.confirm) return setError('Passwords do not match.');
    if (!form.terms_accepted) return setError('Accept the terms to join the organization.');
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/organizations/accept-invite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, password: form.password, full_name: form.full_name || null, terms_accepted: form.terms_accepted }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not accept the invitation');
      if (body.access_token) {
        localStorage.setItem('token', body.access_token);
        navigate('/', { replace: true });
        return;
      }
      setMessage('Invitation accepted. Sign in to finish setting up multi-factor authentication.');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="flex justify-center"><Users className="w-12 h-12 text-blue-600" /></div>
        <div className="mt-8 glass-panel py-8 px-6 sm:rounded-2xl">
          <h1 className="text-2xl font-bold text-slate-900 text-center">Join your organization</h1>
          {message ? (
            <div className="mt-6 space-y-4 text-center">
              <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-4 text-sm text-emerald-900">{message}</div>
              <Link to="/login" className="inline-block text-blue-600 font-medium">Sign in</Link>
            </div>
          ) : (
            <form className="mt-6 space-y-5" onSubmit={handleSubmit}>
              <div>
                <label className="block text-sm font-medium text-slate-700">Full name</label>
                <div className="mt-1 relative">
                  <User className="absolute left-3 top-3 h-4 w-4 text-slate-500" />
                  <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} className="w-full rounded-xl border border-white/60 bg-white/40 p-2.5 pl-9 text-sm" />
                </div>
              </div>
              {[['Password', 'password'], ['Confirm password', 'confirm']].map(([label, key]) => (
                <div key={key}>
                  <label className="block text-sm font-medium text-slate-700">{label}</label>
                  <div className="mt-1 relative">
                    <Lock className="absolute left-3 top-3 h-4 w-4 text-slate-500" />
                    <input type="password" required minLength={key === 'password' ? 10 : undefined} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} className="w-full rounded-xl border border-white/60 bg-white/40 p-2.5 pl-9 text-sm" />
                  </div>
                </div>
              ))}
              <label className="flex items-start gap-2 text-sm text-slate-600">
                <input type="checkbox" checked={form.terms_accepted} onChange={(e) => setForm({ ...form, terms_accepted: e.target.checked })} className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600" />
                <span>I accept the terms of use and privacy policy.</span>
              </label>
              {error && <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}
              <button type="submit" disabled={submitting} className="w-full rounded-xl bg-blue-600 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
                {submitting ? 'Joining...' : 'Accept invitation'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default AcceptInvite;
