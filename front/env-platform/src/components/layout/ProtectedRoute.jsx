import React from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/useAuth';
import Navbar from './Navbar';

const ProtectedRoute = () => {
  const { token, user } = useAuth();
  const location = useLocation();

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  if (user?.must_change_password && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }

  if (
    user?.onboarding_required
    && !user?.must_change_password
    && !['/onboarding', '/change-password'].includes(location.pathname)
  ) {
    return <Navigate to="/onboarding" replace />;
  }

  const platformAdminPaths = new Set(['/', '/admin', '/change-password', '/mfa']);
  if (
    user?.platform_role === 'platform_admin'
    && !platformAdminPaths.has(location.pathname)
  ) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="flex flex-col h-screen bg-transparent overflow-hidden">
      <Navbar />
      <main className="flex-1 overflow-x-hidden overflow-y-auto px-6 py-4 animate-fade-in">
        <Outlet />
      </main>
    </div>
  );
};

export default ProtectedRoute;
