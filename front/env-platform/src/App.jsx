import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/layout/ProtectedRoute';
import Login from './pages/Login';
import Signup from './pages/Signup';
import Home from './pages/Home';

import UploadPage from './pages/UploadPage';
import DatasetsPage from './pages/DatasetsPage';
import AQIDashboard from './pages/AQIDashboard';
import WQIDashboard from './pages/WQIDashboard';
import TemperatureDashboard from './pages/TemperatureDashboard';
import RainfallDashboard from './pages/RainfallDashboard';
import AnomaliesPage from './pages/AnomaliesPage';
import ReportsPage from './pages/ReportsPage';
import VerifyEmail from './pages/VerifyEmail';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import ChangePassword from './pages/ChangePassword';
import MfaSettings from './pages/MfaSettings';
import Onboarding from './pages/Onboarding';
import OrganizationApply from './pages/OrganizationApply';
import VerifyOrganizationContact from './pages/VerifyOrganizationContact';
import OrganizationSetup from './pages/OrganizationSetup';
import AcceptInvite from './pages/AcceptInvite';
import OrganizationPage from './pages/OrganizationPage';
import AdminReviewPage from './pages/AdminReviewPage';
import NotificationsPage from './pages/NotificationsPage';
import NotificationPreferencesPage from './pages/NotificationPreferencesPage';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/organization/apply" element={<OrganizationApply />} />
        <Route path="/organization/verify" element={<VerifyOrganizationContact />} />
        <Route path="/organization/setup" element={<OrganizationSetup />} />
        <Route path="/accept-invite" element={<AcceptInvite />} />

        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<Home />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/datasets" element={<DatasetsPage />} />
          <Route path="/aqi" element={<AQIDashboard />} />
          <Route path="/wqi" element={<WQIDashboard />} />
          <Route path="/temperature" element={<TemperatureDashboard />} />
          <Route path="/rainfall" element={<RainfallDashboard />} />
          <Route path="/anomalies" element={<AnomaliesPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/organization" element={<OrganizationPage />} />
          <Route path="/admin" element={<AdminReviewPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/notifications/preferences" element={<NotificationPreferencesPage />} />
          <Route path="/change-password" element={<ChangePassword />} />
          <Route path="/mfa" element={<MfaSettings />} />
          <Route path="/onboarding" element={<Onboarding />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
