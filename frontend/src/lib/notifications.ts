import { api } from "./api";

export interface NotificationItem {
  id: number;
  type: "application" | "interview" | "assessment" | "system";
  title: string;
  message: string;
  link: string | null;
  read: boolean;
  created_at: string;
}

export function fetchNotifications(): Promise<NotificationItem[]> {
  return api.get<NotificationItem[]>("/notifications");
}

export function fetchUnreadCount(): Promise<{ unread_count: number }> {
  return api.get<{ unread_count: number }>("/notifications/unread-count");
}

export function markNotificationRead(id: number): Promise<NotificationItem> {
  return api.post<NotificationItem>(`/notifications/${id}/read`);
}

export function markAllNotificationsRead(): Promise<{
  message: string;
  marked: number;
}> {
  return api.post<{ message: string; marked: number }>(
    "/notifications/read-all"
  );
}