import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, Info, AlertTriangle } from 'lucide-react';
import { fetchNotificationPreferences, updateNotificationPreferences } from '../lib/api';

const TYPE_LABELS = {
  upload_completed: 'Upload Completed',
  upload_failed: 'Upload Failed',
  reprocess_completed: 'Reprocess Completed',
  reprocess_failed: 'Reprocess Failed',
  forecast_unavailable: 'Forecast Unavailable',
  dataset_shared: 'Dataset Shared',
  publish_request_approved: 'Publish Approved',
  publish_request_declined: 'Publish Declined',
  account_approved: 'Account Approved',
  account_rejected: 'Account Rejected',
  password_changed: 'Password Changed',
  mfa_changed: 'MFA Changed',
  new_device_login: 'New Device Login',
  staff_invite_accepted: 'Staff Invite Accepted',
  member_removed: 'Member Removed',
  org_application_decision: 'Org Application Decision',
  new_signup_pending: 'New Signup Pending',
  org_application_pending: 'Org Application Pending',
  refresh_reuse_spike: 'Refresh Reuse Spike',
  storage_at_80_percent: 'Storage at 80%',
  backup_missing_or_stale: 'Backup Missing/Stale',
  admin_without_mfa: 'Admin Without MFA',
  failed_background_job: 'Failed Background Job',
  anomaly_detected: 'Anomaly Detected',
  daily_digest: 'Daily Digest',
};

const WARNING_TYPES = new Set([
  'upload_failed',
  'reprocess_failed',
  'forecast_unavailable',
  'publish_request_declined',
  'account_rejected',
  'new_device_login',
  'member_removed',
  'refresh_reuse_spike',
  'storage_at_80_percent',
  'backup_missing_or_stale',
  'admin_without_mfa',
  'failed_background_job',
  'anomaly_detected',
]);

function getTypeLabel(type) {
  return TYPE_LABELS[type] || type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function TypeIcon({ type }) {
  if (WARNING_TYPES.has(type)) {
    return (
      <div className="w-8 h-8 rounded-full flex items-center justify-center bg-amber-100">
        <AlertTriangle className="w-4 h-4 text-amber-600" />
      </div>
    );
  }
  return (
    <div className="w-8 h-8 rounded-full flex items-center justify-center bg-blue-100">
      <Info className="w-4 h-4 text-blue-600" />
    </div>
  );
}

const NotificationPreferencesPage = () => {
  const navigate = useNavigate();
  const [preferences, setPreferences] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  const loadPreferences = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchNotificationPreferences();
      setPreferences(data.preferences || {});
    } catch (e) {
      console.error('Failed to load preferences:', e);
      setError('Failed to load preferences');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPreferences();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const data = await updateNotificationPreferences(preferences);
      if (data.preferences) setPreferences(data.preferences);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e) {
      console.error(e);
      setError('Failed to save preferences');
    } finally {
      setSaving(false);
    }
  };

  const handleChange = (type, field, value) => {
    setPreferences(prev => ({
      ...prev,
      [type]: { ...prev[type], [field]: value },
    }));
  };

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 bg-slate-200 rounded w-64"></div>
        <div className="glass-panel rounded-2xl overflow-hidden">
          <div className="p-6 space-y-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-14 bg-slate-200 rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Notification Preferences</h1>
          <p className="text-slate-600 mt-1">Choose how you want to be notified for each event type.</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => navigate('/notifications')}
            className="px-4 py-2 rounded-xl border border-white/60 bg-white/50 text-sm text-slate-700 hover:bg-white/80"
          >
            View Notifications
          </button>
        </div>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}
      {success && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">Preferences saved!</div>}

      <div className="glass-panel rounded-2xl overflow-hidden">
        <div className="p-4 border-b border-white/60">
          <h2 className="text-lg font-semibold text-slate-900">Notification Types</h2>
          <p className="text-sm text-slate-500 mt-1">Toggle in-app and email notifications for each event type.</p>
        </div>
        <div className="divide-y divide-white/60">
          {Object.entries(preferences)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([type, prefs]) => (
              <div key={type} className="p-4 flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <TypeIcon type={type} />
                  <div>
                    <p className="font-medium text-slate-900">{getTypeLabel(type)}</p>
                    <p className="text-xs text-slate-500">Receive in-app and/or email notifications</p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={prefs.in_app !== false}
                      onChange={(e) => handleChange(type, 'in_app', e.target.checked)}
                      className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-slate-700">In-app</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={prefs.email === true}
                      onChange={(e) => handleChange(type, 'email', e.target.checked)}
                      className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-slate-700">Email</span>
                  </label>
                </div>
              </div>
            ))}
        </div>

        <div className="p-4 border-t border-white/60 flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-6 py-2.5 rounded-xl bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
          >
            {saving ? <Loader2 className="animate-spin w-4 h-4" /> : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default NotificationPreferencesPage;
