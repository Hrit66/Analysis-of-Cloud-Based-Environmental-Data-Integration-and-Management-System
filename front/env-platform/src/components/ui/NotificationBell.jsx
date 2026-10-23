import React, { useState, useEffect, useRef } from 'react';
import { Bell, X, AlertTriangle, Info, ChevronRight, BellOff } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { fetchNotifications, fetchUnreadCount, markNotificationRead, markAllNotificationsRead, deleteNotification } from '../../lib/api';

const SEVERITY_ICONS = {
  info: Info,
  warning: AlertTriangle,
  critical: AlertTriangle,
};

const SEVERITY_COLORS = {
  info: 'text-blue-600 bg-blue-50 border-blue-100',
  warning: 'text-amber-600 bg-amber-50 border-amber-100',
  critical: 'text-red-600 bg-red-50 border-red-100',
};

function SeverityIcon({ severity, className = 'w-4 h-4' }) {
  const Icon = SEVERITY_ICONS[severity] || Info;
  return <Icon className={className} />;
}

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

function formatRelativeTime(dateString) {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  
  // IST format: DD Mon YYYY, HH:mm
  return date.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Kolkata',
  }).replace(',', '');
}

function getTypeLabel(type) {
  return TYPE_LABELS[type] || type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function safeInternalLink(link) {
  return typeof link === 'string' && link.startsWith('/') && !link.startsWith('//') ? link : null;
}

export default function NotificationBell() {
  const [unreadCount, setUnreadCount] = useState(0);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const dropdownRef = useRef(null);
  const navigate = useNavigate();

  // Fetch unread count
  const loadUnreadCount = async () => {
    try {
      const data = await fetchUnreadCount();
      setUnreadCount(data.count || 0);
    } catch (e) {
      console.error('Failed to fetch unread count:', e);
    }
  };

  // Fetch notifications for dropdown
  const loadNotifications = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchNotifications({ unread_only: false, limit: 10 });
      setNotifications(data.items || []);
    } catch (e) {
      setError('Failed to load notifications');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // Poll unread count
  useEffect(() => {
    loadUnreadCount();
    const interval = setInterval(loadUnreadCount, 45000); // 45 seconds
    return () => clearInterval(interval);
  }, []);

  // Refresh count when another view marks notifications read.
  useEffect(() => {
    const handleChanged = () => loadUnreadCount();
    window.addEventListener('notifications:changed', handleChanged);
    return () => window.removeEventListener('notifications:changed', handleChanged);
  }, []);

  // Refresh on tab visibility change
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        loadUnreadCount();
        if (dropdownOpen) loadNotifications();
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [dropdownOpen]);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleMarkRead = async (id) => {
    try {
      await markNotificationRead(id);
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, read_at: new Date().toISOString() } : n));
      setUnreadCount(prev => Math.max(0, prev - 1));
    } catch (e) {
      console.error('Failed to mark read:', e);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead();
      setNotifications(prev => prev.map(n => ({ ...n, read_at: new Date().toISOString() })));
      setUnreadCount(0);
    } catch (e) {
      console.error('Failed to mark all read:', e);
    }
  };

  const handleDelete = async (id, event) => {
    event.stopPropagation();
    const wasUnread = notifications.some(n => n.id === id && !n.read_at);
    try {
      await deleteNotification(id);
      setNotifications(prev => prev.filter(n => n.id !== id));
      if (wasUnread) setUnreadCount(prev => Math.max(0, prev - 1));
    } catch (e) {
      console.error('Failed to delete notification:', e);
    }
  };

  const handleNotificationClick = (notification) => {
    if (!notification.read_at) handleMarkRead(notification.id);
    const link = safeInternalLink(notification.link);
    if (link) {
      navigate(link);
      setDropdownOpen(false);
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => {
          setDropdownOpen(!dropdownOpen);
          if (!dropdownOpen) loadNotifications();
        }}
        className={`relative p-2 rounded-xl transition-colors ${
          dropdownOpen ? 'bg-white/80' : 'hover:bg-white/50'
        }`}
        aria-label={`Notifications${unreadCount > 0 ? `, ${unreadCount} unread` : ''}`}
        aria-expanded={dropdownOpen}
        aria-haspopup="true"
      >
        <Bell className="w-5 h-5 text-slate-600" />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-white text-xs font-medium">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {dropdownOpen && (
        <div className="absolute right-0 mt-2 w-96 max-h-[500px] glass-panel rounded-2xl shadow-xl border border-white/60 overflow-hidden z-50 animate-fade-in-up">
          <div className="flex items-center justify-between p-4 border-b border-white/60">
            <h3 className="font-semibold text-slate-900">Notifications</h3>
            <div className="flex items-center gap-2">
              {unreadCount > 0 && (
                <button
                  onClick={handleMarkAllRead}
                  className="text-xs text-blue-600 hover:text-blue-700 font-medium"
                >
                  Mark all read
                </button>
              )}
            </div>
          </div>

          {loading && (
            <div className="p-8 text-center text-slate-500">
              <div className="animate-spin rounded-full h-6 w-6 border-2 border-blue-500 border-t-transparent mx-auto"></div>
              <p className="mt-2 text-sm">Loading notifications...</p>
            </div>
          )}

          {!loading && error && (
            <div className="p-4 text-center text-red-600">{error}</div>
          )}

          {!loading && !error && notifications.length === 0 && (
            <div className="p-8 text-center text-slate-500">
              <BellOff className="w-10 h-10 mx-auto text-slate-300 mb-2" />
              <p>No notifications yet</p>
            </div>
          )}

          {!loading && !error && notifications.length > 0 && (
            <div className="divide-y divide-white/60">
              {notifications.map((notification) => (
                <div
                  key={notification.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleNotificationClick(notification)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleNotificationClick(notification);
                    }
                  }}
                  className={`w-full p-4 text-left cursor-pointer transition-colors ${
                    !notification.read_at ? 'bg-blue-50/50' : 'hover:bg-white/50'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${SEVERITY_COLORS[notification.severity] || SEVERITY_COLORS.info}`}>
                      <SeverityIcon severity={notification.severity} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className={`font-medium text-sm ${!notification.read_at ? 'text-slate-900' : 'text-slate-700'}`}>
                          {getTypeLabel(notification.type)}
                        </span>
                        <span className="text-xs text-slate-400 whitespace-nowrap">
                          {formatRelativeTime(notification.created_at)}
                        </span>
                      </div>
                      <p className="mt-1 text-sm text-slate-600 line-clamp-2">{notification.body}</p>
                      {!notification.read_at && (
                        <span className="inline-block mt-2 px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700">Unread</span>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(notification.id, e);
                        }}
                        className="p-1 text-slate-400 hover:text-red-500 rounded"
                        aria-label="Delete notification"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="p-3 border-t border-white/60">
            <button
              onClick={() => {
                navigate('/notifications');
                setDropdownOpen(false);
              }}
              className="w-full text-center text-sm text-blue-600 hover:text-blue-700 font-medium"
            >
              View all notifications <ChevronRight className="inline w-4 h-4 ml-1" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
