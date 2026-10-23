import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/useAuth';
import { Database, Lock, ShieldCheck } from 'lucide-react';

const ChangePassword = () => {
  const { changePassword, user } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (password.length < 10) return setError('Password must be at least 10 characters.');
    if (password !== confirm) return setError('Passwords do not match.');
    setSubmitting(true);
    try {
      await changePassword(current, password);
      navigate('/login', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="flex justify-center">
          <Database className="w-12 h-12 text-blue-600 drop-shadow-md" />
        </div>
        <div className="mt-8 glass-panel py-8 px-6 sm:rounded-2xl">
          <div className="flex items-center justify-center gap-2 text-slate-900">
            <ShieldCheck className="h-6 w-6 text-blue-600" />
            <h1 className="text-2xl font-bold">Change your password</h1>
          </div>
          <p className="mt-2 text-center text-sm text-slate-500">
            {user?.must_change_password
              ? 'You must replace the temporary password before continuing.'
              : 'Choose a strong password. You will be signed out after changing it.'}
          </p>
          <form className="mt-6 space-y-5" onSubmit={handleSubmit}>
            {[['Current password', current, setCurrent], ['New password', password, setPassword], ['Confirm new password', confirm, setConfirm]].map(([label, value, setter]) => (
              <div key={label}>
                <label className="block text-sm font-medium text-slate-700">{label}</label>
                <div className="mt-1 relative rounded-md shadow-sm">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Lock className="h-5 w-5 text-slate-500" />
                  </div>
                  <input
                    type="password"
                    required
                    minLength={label === 'Current password' ? undefined : 10}
                    value={value}
                    onChange={(e) => setter(e.target.value)}
                    className="focus:ring-blue-500 focus:border-blue-500 block w-full pl-10 sm:text-sm border-white/60 bg-white/40 rounded-xl p-2.5 border"
                  />
                </div>
              </div>
            ))}
            {error && <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}
            <button type="submit" disabled={submitting} className="w-full rounded-xl bg-blue-600 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {submitting ? 'Saving...' : 'Change password'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default ChangePassword;
