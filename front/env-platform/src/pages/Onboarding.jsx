import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/useAuth';
import { CheckCircle2, ShieldCheck } from 'lucide-react';
import BrandLogo from '../components/common/BrandLogo';

const Onboarding = () => {
  const { user, completeOnboarding } = useAuth();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleFinish = async () => {
    setSubmitting(true);
    setError('');
    try {
      await completeOnboarding();
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page min-h-screen flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-lg">
        <div className="flex justify-center">
          <BrandLogo />
        </div>
        <div className="mt-8 glass-panel py-8 px-6 sm:rounded-2xl">
          <h1 className="text-2xl font-bold text-slate-900 text-center">
            Welcome, {user?.full_name || user?.email}
          </h1>
          <p className="mt-2 text-center text-sm text-slate-500">
            Your account is ready. A few quick checks keep shared environmental data safe.
          </p>
          <div className="mt-6 space-y-3">
            {[
              'Use your institutional or organization email for collaboration.',
              'Datasets are private by default; share only what you intend to publish.',
              'Reports and exports are audited and may be rate-limited.',
            ].map((item) => (
              <div key={item} className="flex items-start gap-3 rounded-xl bg-white/50 border border-white/60 px-4 py-3">
                <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600 shrink-0" />
                <span className="text-sm text-slate-700">{item}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
            <ShieldCheck className="h-4 w-4" />
            <span>You can change these preferences later from your organization settings.</span>
          </div>
          {error && <div className="mt-4 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}
          <button
            onClick={handleFinish}
            disabled={submitting}
            className="mt-6 w-full rounded-xl bg-blue-600 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {submitting ? 'Finishing...' : 'Finish onboarding'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default Onboarding;
