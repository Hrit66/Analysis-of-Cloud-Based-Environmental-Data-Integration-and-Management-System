import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import Navbar from './Navbar';

const ProtectedRoute = () => {
  const { token } = useAuth();

  if (!token) {
    return <Navigate to="/login" replace />;
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
