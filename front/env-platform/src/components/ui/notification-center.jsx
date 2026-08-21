import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bell, Settings, MessageSquare, AlertTriangle, CloudRain, Wind, FileText } from 'lucide-react';
import { cn } from '../../lib/utils';

export const NotificationCenter = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('All');
  const dropdownRef = useRef(null);

  const tabs = ['All', 'Unread', 'Archived'];

  const notifications = [
    {
      id: 1,
      title: 'New notification 1',
      time: '1 min ago',
      icon: MessageSquare,
      iconColor: 'text-slate-400',
      unread: true,
    },
    {
      id: 2,
      title: 'New notification 2',
      time: '2 min ago',
      icon: MessageSquare,
      iconColor: 'text-slate-400',
      unread: true,
    },
    {
      id: 3,
      title: 'New notification 3',
      time: '3 min ago',
      icon: MessageSquare,
      iconColor: 'text-slate-400',
      unread: false,
    },
    {
      id: 4,
      title: 'New notification 4',
      time: '4 min ago',
      icon: MessageSquare,
      iconColor: 'text-slate-400',
      unread: false,
    },
    {
      id: 5,
      title: 'New notification 5',
      time: '5 min ago',
      icon: MessageSquare,
      iconColor: 'text-slate-400',
      unread: false,
    }
  ];

  // Filter based on tab
  const filteredNotifications = notifications.filter(n => {
    if (activeTab === 'Unread') return n.unread;
    if (activeTab === 'Archived') return false; 
    return true;
  });

  // Handle outside click
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="relative" ref={dropdownRef}>
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="hidden sm:block p-2 text-slate-500 hover:text-slate-700 rounded-full hover:bg-white/50 transition-colors relative focus:outline-none border border-slate-200 shadow-sm bg-white"
      >
        <Bell className="w-5 h-5" />
        <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-green-500 border-2 border-white rounded-full"></span>
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            className="absolute right-0 mt-3 w-80 bg-white rounded-xl shadow-[0_10px_40px_-10px_rgba(0,0,0,0.15)] border border-slate-200 overflow-hidden z-50"
          >
            {/* Header / Tabs */}
            <div className="flex items-center justify-between border-b border-slate-200 px-2 pt-2 bg-slate-50/50">
              <div className="flex">
                {tabs.map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={cn(
                      "px-4 py-2.5 text-sm font-medium transition-colors relative",
                      activeTab === tab ? "text-slate-900" : "text-slate-500 hover:text-slate-700"
                    )}
                  >
                    {tab}
                    {activeTab === tab && (
                      <motion.div
                        layoutId="activeTabIndicator"
                        className="absolute bottom-0 left-0 right-0 h-0.5 bg-slate-900"
                      />
                    )}
                  </button>
                ))}
              </div>
              <button className="p-2 text-slate-400 hover:text-slate-600 transition-colors mr-1">
                <Settings className="w-4 h-4" />
              </button>
            </div>

            {/* List */}
            <div className="max-h-[360px] overflow-y-auto">
              {filteredNotifications.length > 0 ? (
                filteredNotifications.map((notif) => (
                  <div 
                    key={notif.id} 
                    className="flex items-start gap-3 p-4 border-b border-slate-100 hover:bg-slate-50 transition-colors cursor-pointer"
                  >
                    <div className="mt-0.5">
                      <notif.icon className={cn("w-5 h-5", notif.iconColor)} strokeWidth={1} strokeDasharray="2 2" />
                    </div>
                    <div className="flex-1">
                      <h4 className="text-sm font-medium text-slate-900">
                        {notif.title}
                      </h4>
                      <p className="text-xs text-slate-500 mt-1">{notif.time}</p>
                    </div>
                  </div>
                ))
              ) : (
                <div className="p-8 text-center text-slate-500 text-sm">
                  No notifications
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
