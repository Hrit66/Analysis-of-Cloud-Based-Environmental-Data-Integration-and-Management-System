import React, { useState, useEffect, useCallback } from 'react';
import { AuthContext } from './useAuth';
import { API_BASE, refreshAccessToken as sharedRefreshAccessToken } from '../lib/api';

const formatDetail = (detail) => {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const field = Array.isArray(item?.loc)
        ? item.loc.filter((part) => part !== 'body').join('.')
        : '';
      if (field === 'password' && item?.type === 'string_too_short') {
        return 'Password must be at least 10 characters.';
      }
      if (item?.msg) return field ? `${field}: ${item.msg}` : item.msg;
      return JSON.stringify(item);
    }).join(' ');
  }
  if (detail) return JSON.stringify(detail);
  return null;
};

const extractDetail = async (res, fallback) => {
  try {
    const body = await res.json();
    const formatted = formatDetail(body?.detail);
    if (formatted) return formatted;
  } catch {
    // ignore parse errors
  }
  return fallback;
};

const storeToken = (value) => {
  if (value) localStorage.setItem('token', value);
  else localStorage.removeItem('token');
};

const jsonPost = (url, payload, token) => fetch(url, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  },
  body: JSON.stringify(payload),
  credentials: 'include',
});

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token') || null);
  const [loading, setLoading] = useState(true);

  const applyAccessToken = useCallback((value) => {
    storeToken(value);
    setToken(value || null);
  }, []);

  const refreshAccessToken = useCallback(async () => {
    const value = await sharedRefreshAccessToken();
    if (!value) return null;
    applyAccessToken(value);
    return value;
  }, [applyAccessToken]);

  const fetchMe = useCallback(async (accessToken) => {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      credentials: 'include',
    });
    if (!res.ok) return null;
    return res.json();
  }, []);

  const setUserFromMe = useCallback((me) => {
    if (me) setUser({ ...me, name: me.full_name || me.email });
    return me;
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadUser = async () => {
      setLoading(true);
      let accessToken = token;
      let me = accessToken ? await fetchMe(accessToken) : null;
      if (!me) {
        accessToken = await refreshAccessToken();
        me = accessToken ? await fetchMe(accessToken) : null;
      }
      if (cancelled) return;
      if (me) {
        setUserFromMe(me);
      } else {
        applyAccessToken(null);
        setUser(null);
      }
      if (!cancelled) setLoading(false);
    };

    loadUser();
    return () => { cancelled = true; };
  }, [token, fetchMe, refreshAccessToken, applyAccessToken, setUserFromMe]);

  const login = async (email, password) => {
    const body = new URLSearchParams();
    body.append('username', email);
    body.append('password', password);

    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
      credentials: 'include',
    });

    if (!res.ok) {
      throw new Error(await extractDetail(res, 'Incorrect email or password'));
    }

    const data = await res.json();
    const flags = {
      mustChangePassword: Boolean(data.must_change_password),
      onboardingRequired: Boolean(data.onboarding_required),
    };
    if (data.mfa_required || data.mfa_setup_required) {
      return {
        mfaRequired: Boolean(data.mfa_required),
        mfaSetupRequired: Boolean(data.mfa_setup_required),
        mfaToken: data.mfa_token,
        ...flags,
      };
    }

    applyAccessToken(data.access_token);
    const me = await fetchMe(data.access_token);
    setUserFromMe(me);
    return { signedIn: true, ...flags };
  };

  const verifyMfa = async (mfaToken, code) => {
    const res = await jsonPost(`${API_BASE}/auth/mfa/verify`, { mfa_token: mfaToken, code });
    if (!res.ok) throw new Error(await extractDetail(res, 'Invalid authentication code'));
    const data = await res.json();
    applyAccessToken(data.access_token);
    const me = await fetchMe(data.access_token);
    setUserFromMe(me);
    return {
      signedIn: true,
      mustChangePassword: Boolean(data.must_change_password),
      onboardingRequired: Boolean(data.onboarding_required),
    };
  };

  const setupMfa = async (mfaToken) => {
    const res = await jsonPost(`${API_BASE}/auth/mfa/setup`, { mfa_token: mfaToken });
    if (!res.ok) throw new Error(await extractDetail(res, 'Could not start MFA setup'));
    return res.json();
  };

  const enableMfa = async (mfaToken, code) => {
    const res = await jsonPost(`${API_BASE}/auth/mfa/enable`, { mfa_token: mfaToken, code });
    if (!res.ok) throw new Error(await extractDetail(res, 'Invalid authentication code'));
    const data = await res.json();
    applyAccessToken(data.access_token);
    const me = await fetchMe(data.access_token);
    setUserFromMe(me);
    return {
      signedIn: true,
      mustChangePassword: Boolean(data.must_change_password),
      onboardingRequired: Boolean(data.onboarding_required),
    };
  };

  const fetchSignupOptions = async () => {
    const res = await fetch(`${API_BASE}/auth/signup-options`);
    if (!res.ok) throw new Error('Could not load signup options');
    return res.json();
  };

  const signup = async ({
    email, password, full_name, signup_type = 'student',
    institution = '', terms_accepted = false, orcid = '',
  }) => {
    const res = await jsonPost(`${API_BASE}/auth/register`, {
      email,
      password,
      full_name,
      signup_type,
      institution: institution || null,
      terms_accepted,
      orcid: orcid || null,
    });

    if (!res.ok) {
      throw new Error(await extractDetail(res, 'Registration failed'));
    }

    const data = await res.json();
    if (data.verification_required) {
      if (!data.verification_token) {
        return { verificationRequired: true, signedIn: false };
      }
      const verify = await jsonPost(`${API_BASE}/auth/verify-email`, {
        token: data.verification_token,
      });
      if (!verify.ok) {
        throw new Error(await extractDetail(verify, 'Email verification failed'));
      }
      const verified = await verify.json();
      if (!verified.can_login) {
        return {
          verificationRequired: false,
          pendingApproval: true,
          status: verified.status,
        };
      }
    }
    const result = await login(email, password);
    return { ...result, verificationRequired: false };
  };

  const verifyEmail = async (verificationToken) => {
    const res = await jsonPost(`${API_BASE}/auth/verify-email`, { token: verificationToken });
    if (!res.ok) throw new Error(await extractDetail(res, 'Email verification failed'));
    return res.json();
  };

  const resendVerification = async (email) => {
    const res = await jsonPost(`${API_BASE}/auth/resend-verification`, { email });
    if (!res.ok) throw new Error(await extractDetail(res, 'Could not resend verification email'));
    return res.json();
  };

  const forgotPassword = async (email) => {
    const res = await jsonPost(`${API_BASE}/auth/forgot-password`, { email });
    if (!res.ok) throw new Error(await extractDetail(res, 'Could not request a reset link'));
    return res.json();
  };

  const resetPassword = async (resetToken, newPassword) => {
    const res = await jsonPost(`${API_BASE}/auth/reset-password`, {
      token: resetToken,
      new_password: newPassword,
    });
    if (!res.ok) throw new Error(await extractDetail(res, 'Could not reset password'));
    return res.json();
  };

  const changePassword = async (currentPassword, newPassword) => {
    const res = await jsonPost(
      `${API_BASE}/auth/password`,
      { current_password: currentPassword, new_password: newPassword },
      token,
    );
    if (!res.ok) throw new Error(await extractDetail(res, 'Could not change password'));
    applyAccessToken(null);
    setUser(null);
    return res.json();
  };

  const completeOnboarding = async () => {
    const res = await fetch(`${API_BASE}/auth/onboarding/complete`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      credentials: 'include',
    });
    if (!res.ok) throw new Error(await extractDetail(res, 'Could not complete onboarding'));
    const me = await fetchMe(token);
    setUserFromMe(me);
    return res.json();
  };

  const logout = async () => {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      });
    } catch {
      // local logout still succeeds if the network is unavailable
    }
    applyAccessToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{
      user, token, loading, login, signup, logout,
      verifyMfa, setupMfa, enableMfa, refreshAccessToken,
      fetchSignupOptions, verifyEmail, resendVerification,
      forgotPassword, resetPassword, changePassword, completeOnboarding,
    }}>
      {!loading && children}
    </AuthContext.Provider>
  );
};

export default AuthProvider;
