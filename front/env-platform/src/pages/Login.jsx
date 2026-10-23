import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/useAuth';
import { Mail, Lock, ShieldCheck } from 'lucide-react';
import BrandLogo from '../components/common/BrandLogo';

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [mfaToken, setMfaToken] = useState(null);
  const [mfaMode, setMfaMode] = useState(null);
  const [setup, setSetup] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const { login, verifyMfa, setupMfa, enableMfa } = useAuth();
  const navigate = useNavigate();

  const finishLogin = async (result) => {
    if (result?.mfaRequired) {
      setMfaToken(result.mfaToken);
      setMfaMode('verify');
      return;
    }
    if (result?.mfaSetupRequired) {
      const details = await setupMfa(result.mfaToken);
      setSetup(details);
      setMfaToken(result.mfaToken);
      setMfaMode('setup');
      return;
    }
    if (result?.mustChangePassword) {
      navigate('/change-password');
      return;
    }
    if (result?.onboardingRequired) {
      navigate('/onboarding');
      return;
    }
    navigate('/');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await login(email, password);
      await finishLogin(result);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setSubmitting(false);
    }
  };

  const handleMfa = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = mfaMode === 'setup'
        ? await enableMfa(mfaToken, code)
        : await verifyMfa(mfaToken, code);
      await finishLogin(result);
    } catch (err) {
      setError(err.message || 'Verification failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md animate-fade-in-up">
        <div className="flex justify-center">
          <BrandLogo />
        </div>
        <h2 className="mt-6 text-center text-3xl font-extrabold text-slate-900">
          {mfaMode ? 'Verify your sign-in' : 'Sign in to your account'}
        </h2>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md animate-fade-in-up" style={{ animationDelay: '100ms' }}>
        <div className="glass-panel py-8 px-4 sm:rounded-2xl sm:px-10">
          {!mfaMode ? (
            <form className="space-y-6" onSubmit={handleSubmit}>
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
                    className="focus:ring-blue-500 focus:border-blue-500 block w-full pl-10 sm:text-sm border-white/60 bg-white/40 backdrop-blur-sm rounded-xl p-2.5 border placeholder-slate-400"
                    placeholder="you@example.com"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700">Password</label>
                <div className="mt-1 relative rounded-md shadow-sm">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Lock className="h-5 w-5 text-slate-500" />
                  </div>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="focus:ring-blue-500 focus:border-blue-500 block w-full pl-10 sm:text-sm border-white/60 bg-white/40 backdrop-blur-sm rounded-xl p-2.5 border placeholder-slate-400"
                    placeholder="••••••••"
                  />
                </div>
              </div>

              {error && (
                <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
                  {error}
                </div>
              )}

              <div className="flex justify-end">
                <Link to="/forgot-password" className="text-sm text-blue-600 hover:text-blue-500 font-medium">
                  Forgot password?
                </Link>
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="w-full flex justify-center py-2.5 px-4 border border-transparent rounded-xl shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 hover:shadow-md transition-all focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
              >
                {submitting ? 'Signing in...' : 'Sign in'}
              </button>
            </form>
          ) : (
            <form className="space-y-6" onSubmit={handleMfa}>
              {mfaMode === 'setup' && (
                <div className="rounded-xl bg-blue-50 border border-blue-200 px-4 py-3 text-sm text-blue-900 space-y-2">
                  <p className="font-medium">Set up authenticator MFA</p>
                  <p>Add this secret to your authenticator app, then enter the 6-digit code.</p>
                  <code className="block break-all rounded-lg bg-white/80 px-2 py-2 text-xs">{setup?.secret}</code>
                </div>
              )}
              <div>
                <label className="block text-sm font-medium text-slate-700">Authentication code</label>
                <div className="mt-1 relative rounded-md shadow-sm">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <ShieldCheck className="h-5 w-5 text-slate-500" />
                  </div>
                  <input
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    required
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    className="focus:ring-blue-500 focus:border-blue-500 block w-full pl-10 sm:text-sm border-white/60 bg-white/40 backdrop-blur-sm rounded-xl p-2.5 border placeholder-slate-400 tracking-[0.3em]"
                    placeholder="000000"
                  />
                </div>
              </div>

              {error && (
                <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="w-full flex justify-center py-2.5 px-4 border border-transparent rounded-xl shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 hover:shadow-md transition-all focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
              >
                {submitting ? 'Verifying...' : mfaMode === 'setup' ? 'Enable MFA and sign in' : 'Verify and sign in'}
              </button>
              <button
                type="button"
                onClick={() => { setMfaMode(null); setMfaToken(null); setSetup(null); setCode(''); setError(null); }}
                className="w-full text-sm text-slate-500 hover:text-slate-700"
              >
                Back to sign in
              </button>
            </form>
          )}

          <div className="mt-6 text-center text-sm">
            <span className="text-slate-500">Don't have an account? </span>
            <Link to="/signup" className="text-blue-600 hover:text-blue-500 font-medium">
              Sign up
            </Link>
            <div className="mt-2">
              <Link to="/organization/apply" className="text-slate-500 hover:text-slate-700">
                Apply for an organization account
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Login;
