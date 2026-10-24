import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/useAuth';
import { Mail, MailCheck } from 'lucide-react';
import BrandLogo from '../components/common/BrandLogo';

const VerifyEmail = () => {
  const [params] = useSearchParams();
  const token = params.get('token');
  const { verifyEmail, resendVerification } = useAuth();
  const [state, setState] = useState({ loading: Boolean(token), message: '', canLogin: false });
  const [email, setEmail] = useState('');
  const [resendMessage, setResendMessage] = useState('');
  const [devLink, setDevLink] = useState('');
  const [resending, setResending] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    verifyEmail(token)
      .then((data) => {
        if (!cancelled) setState({ loading: false, message: data.message, canLogin: data.can_login });
      })
      .catch((err) => {
        if (!cancelled) setState({ loading: false, message: err.message, canLogin: false });
      });
    return () => { cancelled = true; };
  }, [token, verifyEmail]);

  const handleResend = async (e) => {
    e.preventDefault();
    setResendMessage('');
    setDevLink('');
    setResending(true);
    try {
      const data = await resendVerification(email);
      setResendMessage(data.message);
      if (data.verification_token) setDevLink(`/verify-email?token=${data.verification_token}`);
    } catch (err) {
      setResendMessage(err.message);
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="auth-page min-h-screen flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="flex justify-center">
          <BrandLogo />
        </div>
        <div className="mt-8 glass-panel py-8 px-6 sm:rounded-2xl text-center space-y-4">
          <MailCheck className="w-10 h-10 text-blue-600 mx-auto" />
          <h1 className="text-2xl font-bold text-slate-900">Email verification</h1>
          {state.loading ? (
            <p className="text-slate-600">Checking your link...</p>
          ) : (
            state.message && <p className="text-slate-600">{state.message}</p>
          )}
          {!state.loading && state.message && (
            <Link to="/login" className="inline-block text-blue-600 hover:text-blue-500 font-medium">
              {state.canLogin ? 'Sign in' : 'Back to sign in'}
            </Link>
          )}

          {!token && (
            <form className="mt-4 space-y-3 text-left" onSubmit={handleResend}>
              <label className="block text-sm font-medium text-slate-700">Need a new link?</label>
              <div className="relative">
                <Mail className="absolute left-3 top-3 h-4 w-4 text-slate-500" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
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

export default VerifyEmail;
