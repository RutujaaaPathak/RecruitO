import { useState, useRef, useEffect, useCallback } from "react";
import type { ChangeEvent, KeyboardEvent, MouseEvent } from "react";
import {
  SendHorizonal,
  Sparkles,
  Trash2,
  Plus,
  Loader2,
  RefreshCw,
  ChevronDown,
  MessageSquare,
} from "lucide-react";
import { api } from "../../lib/api";

// ---------------------------------------------------------------------------
// Backend response shapes (mirror backend/app/schemas.py)
// ---------------------------------------------------------------------------

interface ChunkSource {
  chunk_id: number;
  chunk_index: number;
  section: string | null;
  score: number | null;
  content: string;
}

interface ApplicationData {
  id: number;
  job_id: number;
  status: string;
  match_score: number | null;
  created_at: string;
  job_title: string | null;
  company_name: string | null;
}

interface ChatSession {
  id: number;
  application_id: number | null;
  title: string | null;
  created_at: string;
  updated_at: string;
}

interface ChatSendIn {
  message: string;
  application_id: number | null;
  session_id: number | null;
}

interface ChatMessageOut {
  id: number;
  role: string;
  content: string;
  sources: ChunkSource[];
  model_used: string | null;
  generated_by: string | null;
  created_at: string;
}

interface ChatReply {
  session_id: number;
  application_id: number | null;
  message: ChatMessageOut;
  sources: ChunkSource[];
  generated_by: "llm" | "fallback";
  notice: string | null;
  model_used: string;
}

interface DisplayMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: ChunkSource[];
  notice: string | null;
  created_at: string;
  kind: "normal" | "error";
}

const ACTIVE_STATUSES = ["applied", "shortlisted", "interviewed", "accepted"];

const SESSION_STORAGE_KEY = "recruito-chat-session";

const SUGGESTIONS = [
  "How to improve my resume?",
  "Top skills for frontend developer?",
  "How to crack technical interviews?",
  "Best internships for AI/ML?",
];

function makeGreeting(): DisplayMessage {
  return {
    id: -1,
    role: "assistant",
    content:
      "Hi 👋 I'm RecruitO AI. Ask me about your resume, applications, skill gaps or interview prep — grounded in your RecruitO data.",
    sources: [],
    notice: null,
    created_at: new Date().toISOString(),
    kind: "normal",
  };
}

function mostRecentApplication(apps: ApplicationData[]): ApplicationData | null {
  if (apps.length === 0) return null;
  const active = apps.filter((a) => ACTIVE_STATUSES.includes(a.status));
  const pool = active.length > 0 ? active : apps;
  return pool.reduce((best, a) => (a.created_at > best.created_at ? a : best), pool[0]);
}

function sessionTitleFromMessage(message: string): string {
  const cleaned = message.trim();
  if (!cleaned) return "Chat";
  return cleaned.length > 60 ? `${cleaned.slice(0, 57)}...` : cleaned;
}

function timeAgo(iso: string): string {
  const diffMs = Math.max(0, Date.now() - new Date(iso).getTime());
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function readStoredSession(): number | null {
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

export default function AIChatbot() {
  const [messages, setMessages] = useState<DisplayMessage[]>(() => [makeGreeting()]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [initLoading, setInitLoading] = useState(true);
  const [initError, setInitError] = useState<string | null>(null);

  const [applications, setApplications] = useState<ApplicationData[]>([]);
  const [selectedAppId, setSelectedAppId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [expandedSources, setExpandedSources] = useState<Record<number, boolean>>({});

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const localIdRef = useRef(0);

  const nextLocalId = useCallback((): number => {
    localIdRef.current -= 1;
    return localIdRef.current;
  }, []);

  const selectedApplication = applications.find((a) => a.id === selectedAppId) ?? null;
  const hasConversation = messages.some((m) => m.role === "user");
  const showSuggestions = !hasConversation && !sending && !historyLoading;

  // ---------------------------------------------------------------------------
  // Session loading / deletion
  // ---------------------------------------------------------------------------

  const loadSessionMessages = useCallback(async (sessionId: number): Promise<void> => {
    setHistoryLoading(true);
    try {
      const list = await api.get<ChatMessageOut[]>(`/chat/sessions/${sessionId}/messages`);
      setMessages(
        list.length > 0
          ? list
              .filter((m) => m.role === "user" || m.role === "assistant")
              .map((m) => ({
                id: m.id,
                role: m.role === "user" ? "user" : "assistant",
                content: m.content,
                sources: m.sources ?? [],
                notice: null,
                created_at: m.created_at,
                kind: "normal" as const,
              }))
          : [makeGreeting()]
      );
      setExpandedSources({});
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to load conversation";
      setMessages([
        {
          id: nextLocalId(),
          role: "assistant",
          content: `Couldn't load this conversation: ${message}`,
          sources: [],
          notice: null,
          created_at: new Date().toISOString(),
          kind: "error",
        },
      ]);
    } finally {
      setHistoryLoading(false);
    }
  }, [nextLocalId]);

  // ---------------------------------------------------------------------------
  // Initial load: applications + sessions
  // ---------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;

    const init = async (): Promise<void> => {
      setInitLoading(true);
      setInitError(null);
      try {
        const [apps, sess] = await Promise.all([
          api.get<ApplicationData[]>("/applications"),
          api.get<ChatSession[]>("/chat/sessions"),
        ]);
        if (cancelled) return;

        setApplications(apps);
        setSessions(sess);

        const defaultApp = mostRecentApplication(apps);
        setSelectedAppId(defaultApp ? defaultApp.id : null);

        const storedId = readStoredSession();
        const stored = storedId != null ? sess.find((s) => s.id === storedId) : undefined;
        const target = stored ?? sess[0] ?? null;

        if (target) {
          setActiveSessionId(target.id);
          if (target.application_id != null) setSelectedAppId(target.application_id);
          await loadSessionMessages(target.id);
        }
      } catch (e) {
        if (!cancelled) {
          setInitError(e instanceof Error ? e.message : "Failed to load your data");
        }
      } finally {
        if (!cancelled) setInitLoading(false);
      }
    };

    void init();
    return () => {
      cancelled = true;
    };
  }, [loadSessionMessages]);

  // Persist the active session so a page refresh restores the conversation.
  useEffect(() => {
    try {
      if (activeSessionId != null) {
        localStorage.setItem(SESSION_STORAGE_KEY, String(activeSessionId));
      } else {
        localStorage.removeItem(SESSION_STORAGE_KEY);
      }
    } catch {
      // localStorage unavailable — refresh persistence is best-effort.
    }
  }, [activeSessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending, historyLoading]);

  // ---------------------------------------------------------------------------
  // Sending
  // ---------------------------------------------------------------------------

  const handleSend = useCallback(
    async (suggestionText?: string): Promise<void> => {
      const messageText = (suggestionText ?? input).trim();
      if (!messageText || sending) return;

      const userMessage: DisplayMessage = {
        id: nextLocalId(),
        role: "user",
        content: messageText,
        sources: [],
        notice: null,
        created_at: new Date().toISOString(),
        kind: "normal",
      };
      setMessages((prev) => [...prev, userMessage]);
      setInput("");
      setSending(true);

      const payload: ChatSendIn = {
        message: messageText,
        application_id: selectedAppId,
        session_id: activeSessionId,
      };

      try {
        const reply = await api.post<ChatReply>("/chat", payload);

        setActiveSessionId(reply.session_id);
        setMessages((prev) => [
          ...prev,
          {
            id: reply.message.id,
            role: "assistant",
            content: reply.message.content,
            sources: reply.sources ?? [],
            notice: reply.notice,
            created_at: reply.message.created_at,
            kind: "normal",
          },
        ]);

        setSessions((prev) => {
          const existing = prev.find((s) => s.id === reply.session_id);
          const nowIso = new Date().toISOString();
          const entry: ChatSession = {
            id: reply.session_id,
            application_id: reply.application_id ?? existing?.application_id ?? null,
            title: existing?.title ?? sessionTitleFromMessage(messageText),
            created_at: existing?.created_at ?? nowIso,
            updated_at: nowIso,
          };
          return [entry, ...prev.filter((s) => s.id !== reply.session_id)].sort((a, b) =>
            b.updated_at.localeCompare(a.updated_at)
          );
        });
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Something went wrong. Please try again.";
        setMessages((prev) => [
          ...prev,
          {
            id: nextLocalId(),
            role: "assistant",
            content: `Sorry, I couldn't reply: ${message}`,
            sources: [],
            notice: null,
            created_at: new Date().toISOString(),
            kind: "error",
          },
        ]);
      } finally {
        setSending(false);
      }
    },
    [input, sending, selectedAppId, activeSessionId, nextLocalId]
  );

  const handleInputChange = (e: ChangeEvent<HTMLTextAreaElement>): void => {
    setInput(e.target.value);
    const el = inputRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  // ---------------------------------------------------------------------------
  // Session actions
  // ---------------------------------------------------------------------------

  const openSession = useCallback(
    async (session: ChatSession): Promise<void> => {
      if (session.id === activeSessionId) return;
      setActiveSessionId(session.id);
      if (session.application_id != null) setSelectedAppId(session.application_id);
      await loadSessionMessages(session.id);
    },
    [activeSessionId, loadSessionMessages]
  );

  const startNewChat = (): void => {
    setActiveSessionId(null);
    setMessages([makeGreeting()]);
    setExpandedSources({});
  };

  const deleteChatSession = async (
    e: MouseEvent<HTMLButtonElement>,
    session: ChatSession
  ): Promise<void> => {
    e.stopPropagation();
    try {
      await api.del<void>(`/chat/sessions/${session.id}`);
    } catch {
      // Deletion is best-effort; remove from the sidebar either way.
    }
    setSessions((prev) => prev.filter((s) => s.id !== session.id));
    if (activeSessionId === session.id) {
      setActiveSessionId(null);
      setMessages([makeGreeting()]);
      setExpandedSources({});
    }
  };

  const toggleSources = (messageId: number): void => {
    setExpandedSources((prev) => ({ ...prev, [messageId]: !prev[messageId] }));
  };

  const handleApplicationSelect = (e: ChangeEvent<HTMLSelectElement>): void => {
    const value = e.target.value;
    setSelectedAppId(value === "" ? null : Number(value));
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const sendDisabled = sending || input.trim().length === 0;

  return (
    <div className="flex h-[88vh] w-full rounded-3xl overflow-hidden shadow-2xl bg-gradient-to-br from-[#0f172a] via-[#111827] to-[#0b1120] border border-white/10">

      {/* LEFT CHAT HISTORY */}
      <div className="w-64 border-r border-white/10 p-6 hidden lg:flex flex-col">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-white font-semibold flex items-center gap-2">
            <Sparkles size={16} />
            AI Sessions
          </h2>
          <button
            onClick={startNewChat}
            title="New chat"
            className="text-white/60 hover:text-white hover:bg-white/10 h-8 w-8 flex items-center justify-center rounded-lg transition"
          >
            <Plus size={16} />
          </button>
        </div>

        <div className="space-y-3 text-sm flex-1 overflow-y-auto pr-1">
          {sessions.length === 0 && !initLoading && (
            <p className="text-white/40 text-xs">
              No past sessions yet. Start a conversation to see it here.
            </p>
          )}

          {sessions.map((session) => {
            const app = applications.find((a) => a.id === session.application_id) ?? null;
            const isActive = session.id === activeSessionId;
            return (
              <div
                key={session.id}
                onClick={() => void openSession(session)}
                className={`group p-3 rounded-xl cursor-pointer transition ${
                  isActive
                    ? "bg-gradient-to-r from-violet-600/40 to-blue-600/40 border border-white/10"
                    : "bg-white/5 hover:bg-white/10 border border-transparent"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-white/80 line-clamp-2">
                      {session.title ?? "Chat"}
                    </p>
                    <p className="text-white/40 text-[11px] mt-1">
                      {timeAgo(session.updated_at)}
                      {app?.job_title ? ` • ${app.job_title}` : ""}
                    </p>
                  </div>
                  <button
                    onClick={(e) => void deleteChatSession(e, session)}
                    title="Delete session"
                    className="text-white/40 hover:text-red-400 opacity-0 group-hover:opacity-100 transition shrink-0"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* MAIN CHAT AREA */}
      <div className="flex flex-col flex-1 p-10 relative min-w-0">

        {/* HEADER */}
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-white">
            RecruitO AI Assistant
          </h1>
          <p className="text-white/50 mt-1">
            Your personal 24/7 career mentor
          </p>
        </div>

        {/* APPLICATION CONTEXT */}
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <label htmlFor="chat-application" className="text-white/50 text-sm">
            Chatting about:
          </label>
          {initLoading ? (
            <span className="text-white/40 text-sm flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" /> Loading...
            </span>
          ) : applications.length > 0 ? (
            <select
              id="chat-application"
              value={selectedAppId != null ? String(selectedAppId) : ""}
              onChange={handleApplicationSelect}
              disabled={sending}
              className="flex-1 min-w-[220px] max-w-md px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-white text-sm outline-none focus:border-white/30 disabled:opacity-60"
            >
              {applications.map((app) => (
                <option key={app.id} value={app.id} className="bg-[#111827]">
                  {app.job_title ?? `Application #${app.id}`}
                  {app.company_name ? ` — ${app.company_name}` : ""}
                </option>
              ))}
            </select>
          ) : (
            <p className="text-white/40 text-sm">
              No applications yet — I'll answer using your resume only.
            </p>
          )}

          {selectedApplication && (
            <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/10 text-white/60 border border-white/10">
              {selectedApplication.status} • ATS{" "}
              {selectedApplication.match_score != null
                ? `${selectedApplication.match_score}%`
                : "N/A"}
            </span>
          )}
        </div>

        {initError && (
          <div className="mb-6 p-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-300 text-sm flex items-center justify-between gap-4">
            <span>Couldn't load your chat data: {initError}</span>
            <button
              onClick={() => window.location.reload()}
              className="flex items-center gap-1.5 text-white/80 hover:text-white bg-white/10 hover:bg-white/15 px-3 py-1.5 rounded-lg transition shrink-0"
            >
              <RefreshCw size={14} /> Retry
            </button>
          </div>
        )}

        {/* SUGGESTIONS */}
        {showSuggestions && !initError && (
          <div className="grid grid-cols-2 gap-4 mb-6">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => void handleSend(s)}
                disabled={sending}
                className="p-4 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-white text-sm transition disabled:opacity-60"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {/* CHAT MESSAGES */}
        <div className="flex-1 overflow-y-auto space-y-6 pr-4">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`px-6 py-4 rounded-3xl max-w-xl text-sm leading-relaxed shadow-lg ${
                  msg.kind === "error"
                    ? "bg-red-500/10 backdrop-blur-xl text-red-300 border border-red-500/20"
                    : msg.role === "user"
                    ? "bg-gradient-to-r from-violet-600 to-blue-600 text-white"
                    : "bg-white/10 backdrop-blur-xl text-white border border-white/10"
                }`}
              >
                <p className="whitespace-pre-wrap">{msg.content}</p>

                {msg.notice && (
                  <p className="mt-3 text-yellow-300/90 text-xs">{msg.notice}</p>
                )}

                {msg.role === "assistant" && msg.sources.length > 0 && (
                  <div className="mt-3 border-t border-white/10 pt-2">
                    <button
                      onClick={() => toggleSources(msg.id)}
                      className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-white/40 hover:text-white/70 transition"
                    >
                      <span>Resume context · {msg.sources.length}</span>
                      <ChevronDown
                        size={12}
                        className={`transition-transform ${
                          expandedSources[msg.id] ? "rotate-180" : ""
                        }`}
                      />
                    </button>

                    {expandedSources[msg.id] && (
                      <div className="space-y-2 mt-2">
                        {msg.sources.map((src) => (
                          <div
                            key={src.chunk_id}
                            className="p-2.5 rounded-xl bg-white/5 border border-white/10"
                          >
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-300">
                                {src.section ?? "Resume"}
                              </span>
                              {src.score != null && (
                                <span className="text-[10px] text-white/40">
                                  relevance {src.score}%
                                </span>
                              )}
                            </div>
                            <p className="text-white/60 text-xs whitespace-pre-wrap">
                              {src.content}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}

          {historyLoading && (
            <div className="flex justify-start">
              <div className="px-5 py-3 rounded-3xl bg-white/10 backdrop-blur-xl text-white/50 text-sm border border-white/10 flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" />
                Loading conversation...
              </div>
            </div>
          )}

          {sending && (
            <div className="flex justify-start">
              <div className="px-6 py-4 rounded-3xl bg-white/10 backdrop-blur-xl text-white border border-white/10 shadow-lg flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-white/40 animate-bounce" />
                <span
                  className="h-2 w-2 rounded-full bg-white/40 animate-bounce"
                  style={{ animationDelay: "0.15s" }}
                />
                <span
                  className="h-2 w-2 rounded-full bg-white/40 animate-bounce"
                  style={{ animationDelay: "0.3s" }}
                />
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* INPUT */}
        <div className="mt-8">
          <div className="flex items-end bg-white/5 backdrop-blur-xl border border-white/10 rounded-3xl px-6 py-4 shadow-xl">
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder="Ask about skills, jobs, interview tips... (Enter to send, Shift+Enter for a new line)"
              disabled={sending || initLoading}
              className="flex-1 bg-transparent outline-none text-white placeholder-white/40 text-sm resize-none max-h-[120px] disabled:opacity-60"
            />

            <button
              onClick={() => void handleSend()}
              disabled={sendDisabled}
              title="Send message"
              className="ml-4 h-11 w-11 flex items-center justify-center rounded-2xl bg-gradient-to-r from-violet-600 to-blue-600 text-white hover:scale-110 transition-all duration-200 shadow-lg disabled:opacity-50 disabled:hover:scale-100"
            >
              {sending ? (
                <Loader2 size={18} className="animate-spin" />
              ) : (
                <SendHorizonal size={18} />
              )}
            </button>
          </div>

          {applications.length === 0 && !initLoading && (
            <p className="mt-3 text-white/40 text-xs flex items-center gap-1.5">
              <MessageSquare size={12} />
              Without a selected job, I can still help with resume and interview
              questions.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}