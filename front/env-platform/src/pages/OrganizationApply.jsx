import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { API_BASE } from '../lib/api';
import { Building2, Database, Mail, Phone } from 'lucide-react';

const TYPES = [
  { value: 'university', label: 'University or research institute' },
  { value: 'govt', label: 'Government agency' },
  { value: 'ngo', label: 'Non-governmental organization' },
  { value: 'intl_org', label: 'International organization' },
];

const OrganizationApply = () => {
  const [form, setForm] = useState({
    name: '', type: 'university', domains: '', country: '', contact_email: '',
    phone: '', purpose: '', document_url: '', terms_accepted: false,
  });
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const update = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setMessage('');
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/organizations/applications`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          domains: form.domains.split(',').map((item) => item.trim()).filter(Boolean),
          phone: form.phone || null,
          purpose: form.purpose || null,
          document_url: form.document_url || null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not submit the application');
      }
      setMessage('Application submitted. Check the contact mailbox for a verification link.');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-2xl">
        <div className="flex justify-center">
          <Database className="w-12 h-12 text-blue-600 drop-shadow-md" />
        </div>
        <div className="mt-8 glass-panel py-8 px-6 sm:rounded-2xl">
          <div className="flex items-center justify-center gap-2">
            <Building2 className="h-6 w-6 text-blue-600" />
            <h1 className="text-2xl font-bold text-slate-900">Organization account application</h1>
          </div>
          <p className="mt-2 text-center text-sm text-slate-500">
            For government bodies, international organizations, and institutions that need shared workspaces.
          </p>
          {message ? (
            <div className="mt-6 space-y-4 text-center">
              <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-4 text-sm text-emerald-900">{message}</div>
              <Link to="/login" className="inline-block text-blue-600 hover:text-blue-500 font-medium">Back to sign in</Link>
            </div>
          ) : (
            <form className="mt-6 grid gap-5 sm:grid-cols-2" onSubmit={handleSubmit}>
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-slate-700">Organization name</label>
                <input required value={form.name} onChange={(e) => update('name', e.target.value)} className="mt-1 w-full rounded-xl border border-white/60 bg-white/40 p-2.5 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">Organization type</label>
                <select value={form.type} onChange={(e) => update('type', e.target.value)} className="mt-1 w-full rounded-xl border border-white/60 bg-white/40 p-2.5 text-sm">
                  {TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">Country</label>
                <input value={form.country} onChange={(e) => update('country', e.target.value)} className="mt-1 w-full rounded-xl border border-white/60 bg-white/40 p-2.5 text-sm" />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-slate-700">Organization domains</label>
                <input required value={form.domains} onChange={(e) => update('domains', e.target.value)} placeholder="example.gov.in, example.org" className="mt-1 w-full rounded-xl border border-white/60 bg-white/40 p-2.5 text-sm" />
                <p className="mt-1 text-xs text-slate-500">Comma-separated. The contact email must use one of these domains.</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">Contact email</label>
                <div className="mt-1 relative">
                  <Mail className="absolute left-3 top-3 h-4 w-4 text-slate-500" />
                  <input type="email" required value={form.contact_email} onChange={(e) => update('contact_email', e.target.value)} className="w-full rounded-xl border border-white/60 bg-white/40 p-2.5 pl-9 text-sm" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">Phone</label>
                <div className="mt-1 relative">
                  <Phone className="absolute left-3 top-3 h-4 w-4 text-slate-500" />
                  <input value={form.phone} onChange={(e) => update('phone', e.target.value)} className="w-full rounded-xl border border-white/60 bg-white/40 p-2.5 pl-9 text-sm" />
                </div>
              </div>
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-slate-700">Purpose</label>
                <textarea rows={3} value={form.purpose} onChange={(e) => update('purpose', e.target.value)} className="mt-1 w-full rounded-xl border border-white/60 bg-white/40 p-2.5 text-sm" placeholder="How will your organization use EnvPlatform?" />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-slate-700">Authorization document URL (optional)</label>
                <input value={form.document_url} onChange={(e) => update('document_url', e.target.value)} className="mt-1 w-full rounded-xl border border-white/60 bg-white/40 p-2.5 text-sm" placeholder="https://..." />
              </div>
              <label className="sm:col-span-2 flex items-start gap-2 text-sm text-slate-600">
                <input type="checkbox" checked={form.terms_accepted} onChange={(e) => update('terms_accepted', e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600" />
                <span>I confirm I am authorized to apply for this organization and accept the terms.</span>
              </label>
              {error && <div className="sm:col-span-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}
              <button type="submit" disabled={submitting} className="sm:col-span-2 w-full rounded-xl bg-blue-600 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
                {submitting ? 'Submitting...' : 'Submit application'}
              </button>
            </form>
          )}
          <div className="mt-6 text-center text-sm">
            <Link to="/signup" className="text-slate-500 hover:text-slate-700">Student or researcher? Create a personal account</Link>
          </div>
        </div>
      </div>
    </div>
  );
};

export default OrganizationApply;
