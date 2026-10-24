import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/useAuth';
import { Mail } from 'lucide-react';
import BrandLogo from '../components/common/BrandLogo';

const ForgotPassword = () => {
  const { forgotPassword } = useAuth();
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [devLink, setDevLink] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setMessage('');
    setDevLink('');
    setSubmitting(true);
    try {
      const data = await forgotPassword(email);
      setMessage(data.message);
      if (data.verification_token) {
        setDevLink(`/reset-password?token=${data.verification_token}`);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page min-h-screen flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="flex justify-center">
          <BrandLogo />
        </div>
        <div className="mt-8 glass-panel py-8 px-6 sm:rounded-2xl">
          <h1 className="text-2xl font-bold text-slate-900 text-center">Reset your password</h1>
          <form className="mt-6 space-y-5" onSubmit={handleSubmit}>
            <div>
              <label className="block text-sm font-medium text-slate-700">Email address</label>
              <div className="mt-1 relative rounded-md shadow-sm">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Mail className="h-5 w-5 text-slate-500" />
                </div>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="focus:ring-blue-500 focus:border-blue-500 block w-full pl-10 sm:text-sm border-white/60 bg-white/40 rounded-xl p-2.5 border"
                  placeholder="you@example.com"
                />
              </div>
            </div>
            {message && <div className="rounded-lg bg-blue-50 border border-blue-200 px-3 py-2 text-sm text-blue-800">{message}</div>}
            {devLink && <Link to={devLink} className="block text-sm text-blue-600">Open development reset link</Link>}
            {error && <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}
            <button type="submit" disabled={submitting} className="w-full rounded-xl bg-blue-600 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {submitting ? 'Sending...' : 'Send reset link'}
            </button>
          </form>
          <div className="mt-6 text-center text-sm">
            <Link to="/login" className="text-blue-600 hover:text-blue-500 font-medium">Back to sign in</Link>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ForgotPassword;
