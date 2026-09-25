import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCheck, Inbox } from "lucide-react";
import type { NotificationItem } from "../lib/notifications";
import {
  fetchNotifications,
  fetchUnreadCount,
  markNotificationRead,
  markAllNotificationsRead,
} from "../lib/notifications";
import { parseApiDate } from "../lib/datetime";

interface NotificationsBellProps {
  /* Extra classes for the trigger button so it blends with its shell. */
  buttonClassName?: string;
}

export default function NotificationsBell({
  buttonClassName = "",
}: NotificationsBellProps) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const [items, count] = await Promise.all([
        fetchNotifications(),
        fetchUnreadCount().catch(() => ({ unread_count: 0 })),
      ]);
      setNotifications(items);
      setUnreadCount(count.unread_count);
    } catch {
      setNotifications([]);
    } finally {
      setLoading(false);
    }
  };

  // Initial unread badge, independent of the dropdown being open.
  useEffect(() => {
    fetchUnreadCount()
      .then((count) => setUnreadCount(count.unread_count))
      .catch(() => undefined);
  }, []);

  // Close when clicking outside the bell.
  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) refresh();
  };

  const onMarkAllRead = async () => {
    // Only clear the badge once the server has actually done it: a swallowed
    // failure would show "0 unread" while every notification stays unread.
    try {
      await markAllNotificationsRead();
    } catch {
      return;
    }
    setNotifications((items) => items.map((n) => ({ ...n, read: true })));
    setUnreadCount(0);
  };

  const onOpenNotification = async (note: NotificationItem) => {
    setOpen(false);
    if (!note.read) {
      try {
        await markNotificationRead(note.id);
        setUnreadCount((count) => Math.max(0, count - 1));
        setNotifications((items) =>
          items.map((n) => (n.id === note.id ? { ...n, read: true } : n))
        );
      } catch {
        // Keep the item unread so the badge still tells the truth.
      }
    }
    if (note.link) navigate(note.link);
  };

  const typeColor = (type: NotificationItem["type"]) => {
    if (type === "application") return "bg-blue-500";
    if (type === "interview") return "bg-green-500";
    if (type === "assessment") return "bg-amber-500";
    return "bg-violet-500";
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={toggle}
        className={`
          relative p-2 rounded-lg transition-all duration-200
          ${buttonClassName || "hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"}
        `}
        title="Notifications"
        aria-label="Notifications"
      >
        <Bell size={18} />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[11px] font-bold flex items-center justify-center">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 max-h-96 flex flex-col rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#111827] shadow-2xl overflow-hidden z-50">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-white/10">
            <span className="text-sm font-semibold text-gray-900 dark:text-white">
              Notifications
            </span>
            {unreadCount > 0 && (
              <button
                onClick={onMarkAllRead}
                className="flex items-center gap-1 text-xs text-indigo-600 dark:text-violet-400 hover:underline"
              >
                <CheckCheck size={14} />
                Mark all read
              </button>
            )}
          </div>

          <div className="overflow-y-auto">
            {loading && notifications.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-gray-400">
                Loading…
              </p>
            ) : notifications.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-4 py-10 text-gray-400">
                <Inbox size={28} />
                <p className="text-sm">No notifications yet.</p>
              </div>
            ) : (
              notifications.slice(0, 15).map((note) => (
                <button
                  key={note.id}
                  onClick={() => onOpenNotification(note)}
                  className={`w-full text-left px-4 py-3 border-b border-gray-100 dark:border-white/5 transition-colors hover:bg-gray-50 dark:hover:bg-white/5 ${
                    note.read ? "" : "bg-violet-500/5 dark:bg-violet-500/10"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={`mt-1.5 w-2.5 h-2.5 rounded-full shrink-0 ${typeColor(note.type)}`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                          {note.title}
                        </p>
                        {!note.read && (
                          <span className="text-[10px] font-semibold text-violet-400 shrink-0">
                            NEW
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">
                        {note.message}
                      </p>
                      <p className="text-[11px] text-gray-400 dark:text-gray-500 mt-1">
                        {parseApiDate(note.created_at)?.toLocaleString() ?? ""}
                      </p>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}