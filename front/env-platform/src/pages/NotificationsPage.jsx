import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchNotifications,
  fetchUnreadCount,
  markNotificationRead,
  markAllNotificationsRead,
  deleteNotification,
} from '../lib/api';

const SEVERITY_CONFIG = {
  info: { label: 'Info', color: 'bg-blue-100 text-blue-700', icon: 'info' },
  warning: { label: 'Warning', color: 'bg-amber-100 text-amber-700', icon: 'warning' },
  critical: { label: 'Critical', color: 'bg-red-100 text-red-700', icon: 'critical' },
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

function safeInternalLink(link) {
  return typeof link === 'string' && link.startsWith('/') && !link.startsWith('//') ? link : null;
}

function SeverityBadge({ severity }) {
  const config = SEVERITY_CONFIG[severity] || SEVERITY_CONFIG.info;
  return (
    <span className={`inline-flex items-center px-2 py-1 rounded-md text-xs font-medium ${config.color}`}>
      {config.label}
    </span>
  );
}

const NotificationsPage = () => {
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const [cursor, setCursor] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [filter, setFilter] = useState('all');
  const [loadingMore, setLoadingMore] = useState(false);

  const loadNotifications = useCallback(async (append = false) => {
    if (loadingMore && append) return;
    
    if (!append) {
      setLoading(true);
      setError(null);
    } else {
      setLoadingMore(true);
    }
    
    try {
      const params = { limit: 20 };
      if (filter === 'unread') params.unread_only = true;
      if (append && cursor) params.cursor = cursor;

      const data = await fetchNotifications(params);

      if (append) {
        setNotifications(prev => [...prev, ...data.items]);
      } else {
        setNotifications(data.items || []);
      }
      setHasMore(data.has_more);
      setCursor(data.next_cursor || null);
    } catch (e) {
      console.error('Failed to load notifications:', e);
      setError('Failed to load notifications');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [filter, cursor]);

  const loadUnreadCount = async () => {
    try {
      const data = await fetchUnreadCount();
      setUnreadCount(data.count || 0);
    } catch (e) {
      console.error('Failed to fetch unread count:', e);
    }
  };

  useEffect(() => {
    loadNotifications();
    loadUnreadCount();
  }, [filter]);

  const handleMarkRead = async (id) => {
    const wasUnread = notifications.some(n => n.id === id && !n.read_at);
    try {
      await markNotificationRead(id);
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, read_at: new Date().toISOString() } : n));
      if (wasUnread) {
        setUnreadCount(prev => Math.max(0, prev - 1));
        window.dispatchEvent(new Event('notifications:changed'));
      }
    } catch (e) {
      console.error('Failed to mark read:', e);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead();
      setNotifications(prev => prev.map(n => ({ ...n, read_at: n.read_at || new Date().toISOString() })));
      setUnreadCount(0);
      window.dispatchEvent(new Event('notifications:changed'));
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
      if (wasUnread) {
        setUnreadCount(prev => Math.max(0, prev - 1));
        window.dispatchEvent(new Event('notifications:changed'));
      }
    } catch (e) {
      console.error('Failed to delete notification:', e);
    }
  };

  const handleNotificationClick = (notification) => {
    if (!notification.read_at) handleMarkRead(notification.id);
    const link = safeInternalLink(notification.link);
    if (link) navigate(link);
  };

  if (loading && notifications.length === 0) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 bg-slate-200 rounded w-64"></div>
        <div className="glass-panel rounded-2xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead><tr><th className="px-6 py-4 h-12 bg-slate-200"></th></tr></thead>
              <tbody>
                {[1,2,3,4].map(i => <tr key={i}><td className="px-6 py-4 h-12 bg-slate-200"></td></tr>)}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  }

  const filteredNotifications = filter === 'unread'
    ? notifications.filter(n => !n.read_at)
    : filter === 'read'
    ? notifications.filter(n => n.read_at)
    : notifications;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Notifications</h1>
        <p className="text-slate-600 mt-1">Manage your notification preferences and history.</p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="glass-panel rounded-2xl overflow-hidden">
        <div className="p-4 border-b border-white/60 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-4">
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <span className="flex h-5 w-5 items-center justify-center">
                <svg className="h-5 w-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.599 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
              </span>
              Notifications
              {unreadCount > 0 && (
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-white text-xs font-medium">
                  {unreadCount > 9 ? '9+' : unreadCount}
                </span>
              )}
            </h2>
            <div className="flex gap-2">
              {['all', 'unread', 'read'].map(f => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    filter === f
                      ? 'bg-blue-600 text-white'
                      : 'bg-white text-slate-600 hover:bg-slate-50 border border-slate-200'
                  }`}
                >
                  {f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate('/notifications/preferences')}
              className="px-3 py-1.5 rounded-md text-sm font-medium border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
            >
              Preferences
            </button>
            {notifications.some(n => !n.read_at) && (
              <button
                onClick={handleMarkAllRead}
                className="px-3 py-1.5 rounded-md text-sm font-medium bg-blue-600 text-white hover:bg-blue-700"
              >
                Mark all read
              </button>
            )}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-white/40 text-slate-700 font-medium border-b border-white/50 backdrop-blur-md">
              <tr>
                <th className="px-6 py-3">Type</th>
                <th className="px-6 py-3">Message</th>
                <th className="px-6 py-3">Time</th>
                <th className="px-6 py-3 w-24">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/40">
              {filteredNotifications.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-6 py-12 text-center text-slate-500">
                    No notifications yet
                  </td>
                </tr>
              ) : (
                filteredNotifications.map((notification) => (
                  <tr
                    key={notification.id}
                    className={`hover:bg-white/50 transition-colors ${
                      !notification.read_at ? 'bg-blue-50/50' : ''
                    }`}
                    onClick={() => handleNotificationClick(notification)}
                  >
                    <td className="px-6 py-4">
                      <SeverityBadge severity={notification.severity} />
                    </td>
                    <td className="px-6 py-4 text-slate-700">{notification.body}</td>
                    <td className="px-6 py-4 text-sm text-slate-500">
                      {formatRelativeTime(notification.created_at)}
                      {!notification.read_at && (
                        <span className="ml-2 px-1.5 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700">Unread</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <button
                        onClick={(e) => handleDelete(notification.id, e)}
                        className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded"
                        aria-label="Delete"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {hasMore && (
          <div className="p-4 border-t border-white/60">
            <button
              onClick={() => loadNotifications(true)}
              disabled={loadingMore}
              className="w-full px-4 py-2 rounded-lg border border-white/60 bg-white/50 text-sm text-slate-700 hover:bg-white/80 disabled:opacity-50"
            >
              {loadingMore ? 'Loading...' : 'Load more'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default NotificationsPage;
