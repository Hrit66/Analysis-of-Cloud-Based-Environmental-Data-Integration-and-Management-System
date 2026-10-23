import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { API_BASE } from '../lib/api';
import { Building2, Mail, MailCheck } from 'lucide-react';

const VerifyOrganizationContact = () => {
  const [params] = useSearchParams();
  const token = params.get('token');
  const [state, setState] = useState({ loading: Boolean(token), message: '' });
  const [email, setEmail] = useState('');
  const [resendMessage, setResendMessage] = useState('');
  const [devLink, setDevLink] = useState('');
  const [resending, setResending] = useState(false);

  useEffect(() => {
    if (!token) return;
    fetch(`${API_BASE}/organizations/applications/verify-contact`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    })
      .then(async (res) => {
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Verification failed');
        setState({ loading: false, message: 'Contact email verified. Your application is now awaiting review.' });
      })
      .catch((err) => setState({ loading: false, message: err.message }));
  }, [token]);

  const handleResend = async (e) => {
    e.preventDefault();
    setResendMessage('');
    setDevLink('');
    setResending(true);
    try {
      const res = await fetch(`${API_BASE}/organizations/applications/resend-contact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contact_email: email }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not resend the link');
      setResendMessage(body.message);
      if (body.verification_token) setDevLink(`/organization/verify?token=${body.verification_token}`);
    } catch (err) {
      setResendMessage(err.message);
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="flex justify-center"><Building2 className="w-12 h-12 text-blue-600" /></div>
        <div className="mt-8 glass-panel py-8 px-6 sm:rounded-2xl text-center space-y-4">
          <MailCheck className="w-10 h-10 text-blue-600 mx-auto" />
          <h1 className="text-2xl font-bold text-slate-900">Organization contact verification</h1>
          {state.loading ? (
            <p className="text-slate-600">Checking your link...</p>
          ) : (
            state.message && <p className="text-slate-600">{state.message}</p>
          )}
          {!state.loading && state.message && (
            <Link to="/login" className="inline-block text-blue-600 font-medium">Back to sign in</Link>
          )}
          {!token && (
            <form className="mt-4 space-y-3 text-left" onSubmit={handleResend}>
              <label className="block text-sm font-medium text-slate-700">Need a new verification link?</label>
              <div className="relative">
                <Mail className="absolute left-3 top-3 h-4 w-4 text-slate-500" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="contact@organization.org"
                  className="w-full rounded-xl border border-white/60 bg-white/40 p-2.5 pl-9 text-sm"
                />
              </div>
              {resendMessage && <p className="text-sm text-slate-600">{resendMessage}</p>}
              {devLink && <Link to={devLink} className="block text-sm text-blue-600">Open development verification link</Link>}
              <button type="submit" disabled={resending} className="w-full rounded-xl bg-blue-600 py-2.5 text-sm font-medium text-white disabled:opacity-50">
                {resending ? 'Sending...' : 'Resend verification email'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default VerifyOrganizationContact;
