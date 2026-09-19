import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { CheckCheck } from "lucide-react";
import {
  fetchNotifications,
  markNotificationRead,
  markAllNotificationsRead,
} from "../../lib/notifications";

interface Notification {
  id: number;
  title: string;
  description: string;
  type: "application" | "interview" | "assessment" | "system";
  time: string;
  read: boolean;
}

export default function Notifications() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    fetchNotifications()
      .then((items) => {
        if (!mounted) return;
        setNotifications(
          items.map((n) => ({
            id: n.id,
            title: n.title,
            description: n.message,
            type: n.type,
            time: new Date(n.created_at).toLocaleString(),
            read: n.read,
          }))
        );
      })
      .catch((e) => {
        if (mounted)
          setError(
            e instanceof Error ? e.message : "Failed to load notifications"
          );
      })
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, []);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const onMarkRead = (id: number) => {
    setNotifications((notes) =>
      notes.map((n) => (n.id === id ? { ...n, read: true } : n))
    );
    markNotificationRead(id).catch(() => undefined);
  };

  const onMarkAllRead = () => {
    setNotifications((notes) => notes.map((n) => ({ ...n, read: true })));
    markAllNotificationsRead().catch(() => undefined);
  };

  const typeColor = (type: string) => {
    if (type === "application") return "bg-blue-500";
    if (type === "interview") return "bg-green-500";
    return "bg-violet-500";
  };

  return (
    <div className="space-y-10">

      {/* ================= HEADER ================= */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2">
            Notifications
          </h1>
          <p className="text-gray-400">
            Recent recruitment activity
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="px-4 py-2 rounded-full bg-violet-600/20 text-violet-400 font-semibold">
            {unreadCount} Unread
          </div>
          {unreadCount > 0 && (
            <button
              onClick={onMarkAllRead}
              className="flex items-center gap-1.5 px-4 py-2 rounded-full bg-white/5 border border-white/10 text-gray-300 text-sm hover:bg-white/10 transition"
            >
              <CheckCheck size={16} />
              Mark all read
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
          {error}
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-gray-400">Loading notifications...</p>
      ) : notifications.length === 0 ? (
        <p className="text-gray-400">No notifications yet.</p>
      ) : (
      <div className="relative border-l border-white/10 ml-4 space-y-8">

        {notifications.map((note, index) => (
          <motion.div
            key={note.id}
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.05 }}
            className="relative pl-6"
          >
            {/* Dot Indicator */}
            <div
              className={`absolute -left-[9px] top-2 w-4 h-4 rounded-full ${typeColor(
                note.type
              )}`}
            />

            {/* Card */}
            <button
              onClick={() => onMarkRead(note.id)}
              className={`w-full text-left p-5 rounded-2xl backdrop-blur-md border shadow-lg transition cursor-pointer ${
                note.read
                  ? "bg-white/5 border-white/10"
                  : "bg-white/10 border-violet-500/30 hover:bg-white/15"
              }`}
            >
              <div className="flex justify-between items-start mb-2">
                <h2 className="text-lg font-semibold text-white">
                  {note.title}
                </h2>

                {!note.read && (
                  <span className="text-xs text-violet-400 font-semibold">
                    New
                  </span>
                )}
              </div>

              <p className="text-gray-300 text-sm mb-3">
                {note.description}
              </p>

              <div className="flex justify-between items-center text-sm text-gray-400">
                <span>{note.time}</span>
              </div>
            </button>
          </motion.div>
        ))}
      </div>
      )}

    </div>
  );
}