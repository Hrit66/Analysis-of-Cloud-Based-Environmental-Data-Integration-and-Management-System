import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
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

function App() {
  return (
    <AuthProvider>
      <Router>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            
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
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
    </AuthProvider>
  );
}

export default App;
