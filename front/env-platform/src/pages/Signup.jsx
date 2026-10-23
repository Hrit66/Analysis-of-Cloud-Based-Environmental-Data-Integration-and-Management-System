import React, { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/useAuth';
import { Database, Mail, Lock, User, Building2, GraduationCap, FlaskConical, BadgeCheck } from 'lucide-react';

const Signup = () => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [signupType, setSignupType] = useState('student');
  const [institution, setInstitution] = useState('');
  const [orcid, setOrcid] = useState('');
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [options, setOptions] = useState({ institutions: [], allowed_domains: [], terms_version: '' });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [pendingApproval, setPendingApproval] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const { signup, fetchSignupOptions } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    fetchSignupOptions()
      .then(setOptions)
      .catch(() => setOptions({ institutions: [], allowed_domains: [], terms_version: '' }));
  }, [fetchSignupOptions]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (password.length < 10) {
      setError('Password must be at least 10 characters.');
      return;
    }
    if (!termsAccepted) {
      setError('Accept the terms to create an account.');
      return;
    }
    setSubmitting(true);
    try {
      const result = await signup({
        email,
        password,
        full_name: name,
        signup_type: signupType,
        institution,
        orcid,
        terms_accepted: termsAccepted,
      });
      if (result?.pendingApproval) {
        setPendingApproval(true);
        setNotice('Your email is verified. Your account is awaiting administrator approval.');
        return;
      }
      if (result?.verificationRequired) {
        setNotice('Account created. Check your email to verify it, then sign in.');
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
    } catch (err) {
      setError(err.message || 'Registration failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-lg animate-fade-in-up">
        <div className="flex justify-center">
          <Database className="w-12 h-12 text-blue-600 drop-shadow-md" />
        </div>
        <h2 className="mt-6 text-center text-3xl font-extrabold text-slate-900">
          Create your account
        </h2>
        <p className="mt-2 text-center text-sm text-slate-500">
          Student and researcher accounts are reviewed by your institution's administrators.
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-lg animate-fade-in-up" style={{ animationDelay: '100ms' }}>
        <div className="glass-panel py-8 px-4 sm:rounded-2xl sm:px-10">
          {pendingApproval ? (
            <div className="space-y-4 text-center">
              <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-4 text-sm text-amber-900">
                {notice}
              </div>
              <p className="text-sm text-slate-600">
                You will receive an email once an administrator reviews your account.
              </p>
              <Link to="/login" className="inline-block text-blue-600 hover:text-blue-500 font-medium">
                Back to sign in
              </Link>
            </div>
          ) : (
            <form className="space-y-5" onSubmit={handleSubmit}>
              <div>
                <label className="block text-sm font-medium text-slate-700">I am a</label>
                <div className="mt-2 grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setSignupType('student')}
                    className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-2.5 text-sm font-medium transition ${
                      signupType === 'student'
                        ? 'border-blue-500 bg-blue-50 text-blue-700'
                        : 'border-white/60 bg-white/40 text-slate-600'
                    }`}
                  >
                    <GraduationCap className="h-4 w-4" /> Student
                  </button>
                  <button
                    type="button"
                    onClick={() => setSignupType('researcher')}
                    className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-2.5 text-sm font-medium transition ${
                      signupType === 'researcher'
                        ? 'border-blue-500 bg-blue-50 text-blue-700'
                        : 'border-white/60 bg-white/40 text-slate-600'
                    }`}
                  >
                    <FlaskConical className="h-4 w-4" /> Researcher
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700">Full name</label>
                <div className="mt-1 relative rounded-md shadow-sm">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <User className="h-5 w-5 text-slate-500" />
                  </div>
                  <input
                    type="text"
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="focus:ring-blue-500 focus:border-blue-500 block w-full pl-10 sm:text-sm border-white/60 bg-white/40 backdrop-blur-sm rounded-xl p-2.5 border placeholder-slate-400"
                    placeholder="John Doe"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700">
                  {signupType === 'student' ? 'Institutional email' : 'Email address'}
                </label>
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
                    placeholder={signupType === 'student' ? 'you@university.ac.in' : 'you@example.com'}
                  />
                </div>
                {signupType === 'student' && options.allowed_domains?.length > 0 && (
                  <p className="mt-1 text-xs text-slate-500">
                    Recognised academic domains: {options.allowed_domains.join(', ')}
                  </p>
                )}
                {signupType === 'researcher' && (
                  <p className="mt-1 text-xs text-slate-500">
                    Institutional email is preferred. Other addresses are reviewed by an administrator.
                  </p>
                )}
              </div>

              {signupType === 'researcher' && (
                <div>
                  <label className="block text-sm font-medium text-slate-700">ORCID iD (optional)</label>
                  <div className="mt-1 relative rounded-md shadow-sm">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <BadgeCheck className="h-5 w-5 text-slate-500" />
                    </div>
                    <input
                      type="text"
                      value={orcid}
                      onChange={(e) => setOrcid(e.target.value)}
                      className="focus:ring-blue-500 focus:border-blue-500 block w-full pl-10 sm:text-sm border-white/60 bg-white/40 backdrop-blur-sm rounded-xl p-2.5 border placeholder-slate-400"
                      placeholder="0000-0000-0000-0000"
                    />
                  </div>
                  <p className="mt-1 text-xs text-slate-500">Adding an ORCID iD helps reviewers verify your researcher account.</p>
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-slate-700">Institution</label>
                <div className="mt-1 relative rounded-md shadow-sm">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Building2 className="h-5 w-5 text-slate-500" />
                  </div>
                  <input
                    type="text"
                    list="institution-options"
                    value={institution}
                    onChange={(e) => setInstitution(e.target.value)}
                    className="focus:ring-blue-500 focus:border-blue-500 block w-full pl-10 sm:text-sm border-white/60 bg-white/40 backdrop-blur-sm rounded-xl p-2.5 border placeholder-slate-400"
                    placeholder="Start typing your institution"
                  />
                  <datalist id="institution-options">
                    {options.institutions?.map((item) => (
                      <option key={item.name} value={item.name} />
                    ))}
                  </datalist>
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
                    placeholder="At least 10 characters"
                    minLength={10}
                  />
                </div>
              </div>

              <label className="flex items-start gap-2 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={termsAccepted}
                  onChange={(e) => setTermsAccepted(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                <span>
                  I accept the terms of use and privacy policy
                  {options.terms_version ? ` (version ${options.terms_version})` : ''}.
                </span>
              </label>

              {notice && (
                <div className="rounded-lg bg-blue-50 border border-blue-200 px-3 py-2 text-sm text-blue-800">
                  {notice}
                </div>
              )}

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
                {submitting ? 'Creating account...' : 'Create account'}
              </button>
            </form>
          )}

          <div className="mt-6 text-center text-sm space-y-2">
            <div>
              <span className="text-slate-500">Already have an account? </span>
              <Link to="/login" className="text-blue-600 hover:text-blue-500 font-medium">
                Sign in
              </Link>
            </div>
            <div>
              <span className="text-slate-500">Represent a government body or international organization? </span>
              <Link to="/organization/apply" className="text-blue-600 hover:text-blue-500 font-medium">
                Apply for an organization account
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Signup;
