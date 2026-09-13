import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { motion } from "framer-motion";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  Clock,
  FileText,
  Loader2,
  MessageSquare,
  Play,
  RotateCcw,
  Sparkles,
  Trash2,
  Trophy,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
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

interface MockInterviewQuestionOut {
  id: number;
  question_index: number;
  category: string;
  question_text: string;
  generated_by: "llm" | "fallback";
  notice: string | null;
  sources: ChunkSource[];
}

interface EvaluationOut {
  score: number;
  correctness: string;
  strengths: string[];
  weaknesses: string[];
  missing_points: string[];
  feedback: string;
  generated_by: "llm" | "fallback";
  notice: string | null;
}

interface AnsweredQuestionOut {
  question: MockInterviewQuestionOut;
  answer: string;
  evaluation: EvaluationOut;
}

interface CategoryScoreOut {
  category: string;
  score: number;
  comment: string;
}

interface MockInterviewReportOut {
  overall_score: number;
  category_scores: CategoryScoreOut[];
  strengths: string[];
  weaknesses: string[];
  recommended_topics: string[];
  summary: string;
  generated_by: "llm" | "fallback";
  notice: string | null;
}

interface MockInterviewListOut {
  id: number;
  application_id: number;
  job_title: string | null;
  company_name: string | null;
  status: "in_progress" | "completed";
  max_questions: number;
  answered_count: number;
  overall_score: number | null;
  started_at: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

interface MockInterviewDetailOut {
  id: number;
  application_id: number;
  user_id: number;
  job_title: string | null;
  company_name: string | null;
  status: "in_progress" | "completed";
  max_questions: number;
  current_question: MockInterviewQuestionOut | null;
  answered: AnsweredQuestionOut[];
  matched_skills: string[];
  missing_skills: string[];
  model_used: string;
  used_fallback: boolean;
  report: MockInterviewReportOut | null;
  started_at: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

interface MockInterviewAnswerResponse {
  interview: MockInterviewDetailOut;
  evaluation: EvaluationOut;
  next_question: MockInterviewQuestionOut | null;
  report: MockInterviewReportOut | null;
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CATEGORY_LABELS: Record<string, string> = {
  technical: "Technical",
  project_experience: "Project Experience",
  problem_solving: "Problem Solving",
  behavioral: "Behavioral",
};

function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category.replace(/_/g, " ");
}

function errMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function scoreColor(score: number): string {
  if (score >= 8) return "text-green-400";
  if (score >= 5) return "text-yellow-400";
  return "text-red-400";
}

function scoreFill(score: number): string {
  if (score >= 8) return "#34d399";
  if (score >= 5) return "#fbbf24";
  return "#f87171";
}

function listOutFromDetail(detail: MockInterviewDetailOut): MockInterviewListOut {
  return {
    id: detail.id,
    application_id: detail.application_id,
    job_title: detail.job_title,
    company_name: detail.company_name,
    status: detail.status,
    max_questions: detail.max_questions,
    answered_count: detail.answered.length,
    overall_score: detail.report?.overall_score ?? null,
    started_at: detail.started_at,
    completed_at: detail.completed_at,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type View = "loading" | "home" | "active" | "report";

export default function MockInterview() {
  const [view, setView] = useState<View>("loading");

  const [apps, setApps] = useState<ApplicationData[]>([]);
  const [sessions, setSessions] = useState<MockInterviewListOut[]>([]);
  const [detail, setDetail] = useState<MockInterviewDetailOut | null>(null);
  const [report, setReport] = useState<MockInterviewReportOut | null>(null);

  const [initError, setInitError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [startingId, setStartingId] = useState<number | null>(null);
  const [resumingId, setResumingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [reportLoadingId, setReportLoadingId] = useState<number | null>(null);

  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [ending, setEnding] = useState(false);
  const [expandedSources, setExpandedSources] = useState(false);

  const nextQuestionRef = useRef<HTMLDivElement | null>(null);

  // -------------------------------------------------------------------------
  // Data loading
  // -------------------------------------------------------------------------

  const refreshSessions = useCallback(async (): Promise<void> => {
    try {
      const data = await api.get<MockInterviewListOut[]>("/mock-interviews");
      setSessions(data);
    } catch {
      // Best-effort refresh; the home screen still renders from last state.
    }
  }, []);

  const openInterview = useCallback(async (id: number): Promise<void> => {
    const data = await api.get<MockInterviewDetailOut>(`/mock-interviews/${id}`);
    setDetail(data);
    setReport(data.report);
    setAnswer("");
    setActionError(null);
    setExpandedSources(false);
    if (data.status === "completed") {
      setView("report");
    } else {
      setView("active");
    }
  }, []);

  // Initial load: applications + sessions. If a resume is already in progress,
  // load its current state from the backend so a page refresh resumes it.
  useEffect(() => {
    let cancelled = false;

    const init = async (): Promise<void> => {
      setInitError(null);
      try {
        const [appsData, sessionsData] = await Promise.all([
          api.get<ApplicationData[]>("/applications"),
          api.get<MockInterviewListOut[]>("/mock-interviews"),
        ]);
        if (cancelled) return;
        setApps(appsData);
        setSessions(sessionsData);

        const inProgress = sessionsData.filter((s) => s.status === "in_progress");
        if (inProgress.length > 0) {
          await openInterview(inProgress[0].id);
          return;
        }
        setView("home");
      } catch (e) {
        if (!cancelled) {
          setInitError(errMessage(e, "Failed to load mock interview data"));
          setView("home");
        }
      }
    };

    void init();
    return () => {
      cancelled = true;
    };
  }, [openInterview]);

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------

  const startInterview = async (appId: number): Promise<void> => {
    setStartingId(appId);
    setActionError(null);
    try {
      const data = await api.post<MockInterviewDetailOut>("/mock-interviews", {
        application_id: appId,
      });
      setDetail(data);
      setReport(data.report);
      setAnswer("");
      setExpandedSources(false);
      setSessions((prev) => [listOutFromDetail(data), ...prev]);
      setView("active");
    } catch (e) {
      setActionError(errMessage(e, "Failed to start the mock interview"));
      await refreshSessions();
    } finally {
      setStartingId(null);
    }
  };

  const resumeInterview = async (id: number): Promise<void> => {
    setResumingId(id);
    setActionError(null);
    try {
      await openInterview(id);
    } catch (e) {
      setActionError(errMessage(e, "Failed to resume the mock interview"));
    } finally {
      setResumingId(null);
    }
  };

  const viewReport = async (session: MockInterviewListOut): Promise<void> => {
    setReportLoadingId(session.id);
    setActionError(null);
    try {
      const rep = await api.get<MockInterviewReportOut>(
        `/mock-interviews/${session.id}/report`
      );
      setReport(rep);
      setDetail(null);
      setView("report");
    } catch (e) {
      setActionError(errMessage(e, "Failed to load the report"));
    } finally {
      setReportLoadingId(null);
    }
  };

  const deleteSession = async (session: MockInterviewListOut): Promise<void> => {
    setDeletingId(session.id);
    setActionError(null);
    try {
      await api.del<void>(`/mock-interviews/${session.id}`);
      setSessions((prev) => prev.filter((s) => s.id !== session.id));
    } catch (e) {
      setActionError(errMessage(e, "Failed to delete the session"));
    } finally {
      setDeletingId(null);
    }
  };

  const backToHome = async (): Promise<void> => {
    setView("home");
    setDetail(null);
    setReport(null);
    setAnswer("");
    setActionError(null);
    setExpandedSources(false);
    await refreshSessions();
  };

  const submitAnswer = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    const current = detail?.current_question;
    const text = answer.trim();
    if (!detail || !current || submitting || ending || text.length === 0) return;

    setSubmitting(true);
    setActionError(null);
    try {
      const res = await api.post<MockInterviewAnswerResponse>(
        `/mock-interviews/${detail.id}/answer`,
        { answer_text: text }
      );
      setDetail(res.interview);
      setAnswer("");
      setExpandedSources(false);
      if (res.report) {
        setReport(res.report);
        setView("report");
      } else {
        requestAnimationFrame(() => {
          nextQuestionRef.current?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
        });
      }
    } catch (e) {
      setActionError(errMessage(e, "Failed to submit your answer"));
    } finally {
      setSubmitting(false);
    }
  };

  const endInterview = async (): Promise<void> => {
    if (!detail || ending || submitting) return;
    setEnding(true);
    setActionError(null);
    try {
      const rep = await api.post<MockInterviewReportOut>(
        `/mock-interviews/${detail.id}/end`
      );
      setReport(rep);
      setDetail((prev) =>
        prev ? { ...prev, status: "completed" as const } : prev
      );
      setView("report");
    } catch (e) {
      setActionError(errMessage(e, "Failed to end the interview"));
    } finally {
      setEnding(false);
    }
  };

  // -------------------------------------------------------------------------
  // Derived state
  // -------------------------------------------------------------------------

  const inProgressByApp = useMemo(() => {
    const map: Record<number, MockInterviewListOut> = {};
    sessions.forEach((s) => {
      if (s.status === "in_progress" && !map[s.application_id]) {
        map[s.application_id] = s;
      }
    });
    return map;
  }, [sessions]);

  const inProgressSessions = useMemo(
    () => sessions.filter((s) => s.status === "in_progress"),
    [sessions]
  );

  const completedSessions = useMemo(
    () => sessions.filter((s) => s.status === "completed"),
    [sessions]
  );

  const currentQuestion = detail?.current_question ?? null;
  const answeredCount = detail?.answered.length ?? 0;
  const maxQuestions = detail?.max_questions ?? 0;
  const progress = maxQuestions > 0 ? (answeredCount / maxQuestions) * 100 : 0;
  const lastAnswered =
    detail && detail.answered.length > 0
      ? detail.answered[detail.answered.length - 1]
      : null;

  // -------------------------------------------------------------------------
  // Render helpers
  // -------------------------------------------------------------------------

  const ErrorBanner = ({ message }: { message: string }) => (
    <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
      {message}
    </div>
  );

  const SourcesSection = ({
    question,
  }: {
    question: MockInterviewQuestionOut;
  }) => {
    if (question.sources.length === 0) return null;
    return (
      <div className="mt-4 border-t border-white/10 pt-3">
        <button
          onClick={() => setExpandedSources((prev) => !prev)}
          className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-white/40 hover:text-white/70 transition"
        >
          <span>Resume context · {question.sources.length}</span>
          <ChevronDown
            size={12}
            className={`transition-transform ${expandedSources ? "rotate-180" : ""}`}
          />
        </button>
        {expandedSources && (
          <div className="space-y-2 mt-2">
            {question.sources.map((src) => (
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
    );
  };

  const backButton = (label: string) => (
    <button
      onClick={() => void backToHome()}
      className="flex items-center gap-2 text-white/50 hover:text-white text-sm transition"
    >
      <ArrowLeft size={16} /> {label}
    </button>
  );

  // -------------------------------------------------------------------------
  // Screens
  // -------------------------------------------------------------------------

  const renderHome = () => (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold flex items-center gap-3">
            <Sparkles size={32} className="text-violet-400" />
            AI Mock Interview
          </h1>
          <p className="text-white/50 mt-2">
            Practice a structured, AI-moderated interview for the roles you've
            applied to — with instant feedback on every answer.
          </p>
        </div>
      </div>

      {initError && <ErrorBanner message={initError} />}
      {actionError && <ErrorBanner message={actionError} />}

      {/* ACTIVE SESSIONS */}
      {inProgressSessions.length > 0 && (
        <div className="p-6 rounded-3xl bg-gradient-to-r from-violet-900/30 to-blue-800/20 border border-white/10 shadow-2xl">
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Clock size={18} className="text-violet-300" /> In progress
          </h2>
          <div className="space-y-3">
            {inProgressSessions.map((s) => (
              <div
                key={s.id}
                className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <p className="font-semibold">{s.job_title || "Role"}</p>
                  <p className="text-white/50 text-sm">
                    {s.company_name || "Company"}
                  </p>
                  <p className="text-white/40 text-xs mt-1">
                    {s.answered_count} of {s.max_questions} answered • started{" "}
                    {formatDate(s.started_at)}
                  </p>
                </div>
                <Button
                  onClick={() => void resumeInterview(s.id)}
                  disabled={resumingId === s.id}
                  className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
                >
                  {resumingId === s.id ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Play size={16} />
                  )}
                  Resume
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* APPLICATIONS */}
      <div>
        <h2 className="text-2xl font-semibold mb-4">Pick an application</h2>
        {apps.length === 0 ? (
          <p className="text-white/50">
            You don't have any applications yet. Apply to a job first so the AI
            can interview you for it.
          </p>
        ) : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-5">
            {apps.map((app, index) => {
              const inProgress = inProgressByApp[app.id];
              const isStarting = startingId === app.id;
              return (
                <motion.div
                  key={app.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className="p-6 rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 transition flex flex-col gap-3"
                >
                  <div>
                    <h3 className="text-lg font-semibold">
                      {app.job_title || "Role"}
                    </h3>
                    <p className="text-white/60 text-sm">
                      {app.company_name || "Company"}
                    </p>
                    <p className="text-white/40 text-xs mt-1">
                      Applied {formatDate(app.created_at)}
                      {app.match_score != null
                        ? ` • ATS ${app.match_score}%`
                        : ""}
                    </p>
                  </div>
                  {inProgress ? (
                    <div className="flex items-center justify-between mt-auto">
                      <span className="text-xs text-violet-300 flex items-center gap-1.5">
                        <Clock size={12} /> In progress
                      </span>
                      <Button
                        size="sm"
                        onClick={() => void resumeInterview(inProgress.id)}
                        disabled={resumingId === inProgress.id}
                        className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
                      >
                        {resumingId === inProgress.id ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : (
                          <Play size={14} />
                        )}
                        Resume
                      </Button>
                    </div>
                  ) : (
                    <Button
                      size="sm"
                      onClick={() => void startInterview(app.id)}
                      disabled={isStarting}
                      className="bg-gradient-to-r from-violet-600 to-blue-600 text-white mt-auto"
                    >
                      {isStarting ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Play size={14} />
                      )}
                      Start Mock Interview
                    </Button>
                  )}
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      {/* PAST SESSIONS */}
      <div>
        <h2 className="text-2xl font-semibold mb-4">Previous sessions</h2>
        {completedSessions.length === 0 ? (
          <p className="text-white/50">
            No completed interviews yet. Your reports will appear here.
          </p>
        ) : (
          <div className="space-y-3">
            {completedSessions.map((s) => (
              <motion.div
                key={s.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <p className="font-semibold">
                    {s.job_title || "Role"}
                    <span className="ml-2 text-white/40 text-sm font-normal">
                      {s.company_name || "Company"}
                    </span>
                  </p>
                  <p className="text-white/40 text-xs mt-1">
                    {s.answered_count} of {s.max_questions} answered •{" "}
                    completed {formatDate(s.completed_at)}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {s.overall_score != null && (
                    <span
                      className={`text-2xl font-bold ${scoreColor(s.overall_score)}`}
                    >
                      {s.overall_score}/10
                    </span>
                  )}
                  <Button
                    size="sm"
                    onClick={() => void viewReport(s)}
                    disabled={reportLoadingId === s.id}
                    className="bg-white/10 text-white hover:bg-white/20"
                  >
                    {reportLoadingId === s.id ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <FileText size={14} />
                    )}
                    View Report
                  </Button>
                  <button
                    onClick={() => void deleteSession(s)}
                    disabled={deletingId === s.id}
                    title="Delete session"
                    className="text-white/40 hover:text-red-400 transition disabled:opacity-50"
                  >
                    {deletingId === s.id ? (
                      <Loader2 size={15} className="animate-spin" />
                    ) : (
                      <Trash2 size={15} />
                    )}
                  </button>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  const renderActive = () => {
    if (!detail || !currentQuestion) {
      return (
        <div className="space-y-8">
          <h1 className="text-4xl font-bold">Mock Interview</h1>
          <ErrorBanner message="Could not load the current interview." />
        </div>
      );
    }

    const qNumber = currentQuestion.question_index + 1;
    const submitDisabled =
      submitting || ending || answer.trim().length === 0;

    return (
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          {backButton("Back to sessions")}
          <span className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full bg-white/10 text-white/70 border border-white/10">
            <Clock size={13} className="text-yellow-400" /> In Progress
          </span>
        </div>

        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">{detail.job_title || "Role"}</h1>
            <p className="text-white/50 mt-1">
              {detail.company_name || "Company"}
              {detail.model_used && detail.model_used !== "none"
                ? ` • grounded with ${detail.model_used}`
                : ""}
            </p>
          </div>
          <span className="text-sm text-white/60">
            Question{" "}
            <span className="text-white font-semibold">{qNumber}</span> of{" "}
            {detail.max_questions}
          </span>
        </div>

        {/* Progress bar */}
        <div>
          <div className="flex items-center justify-between text-xs text-white/50 mb-1.5">
            <span>
              {answeredCount} of {detail.max_questions} answered
            </span>
            <span>{Math.round(progress)}%</span>
          </div>
          <div className="h-2.5 w-full bg-white/10 rounded-full overflow-hidden">
            <motion.div
              className="h-2.5 rounded-full bg-gradient-to-r from-violet-500 to-blue-500"
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>

        {actionError && <ErrorBanner message={actionError} />}

        {/* Evaluation of the just-answered question (if any) */}
        {lastAnswered && currentQuestion.id !== lastAnswered.question.id && (
          <motion.div
            ref={nextQuestionRef}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-6 rounded-2xl bg-emerald-500/5 border border-emerald-500/20"
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-emerald-300 flex items-center gap-2">
                <CheckCircle2 size={17} />
                Answered · Question{" "}
                {lastAnswered.question.question_index + 1}
                <span className="text-white/40 text-sm font-normal">
                  {categoryLabel(lastAnswered.question.category)}
                </span>
              </h3>
              <span
                className={`text-2xl font-bold ${scoreColor(lastAnswered.evaluation.score)}`}
              >
                {lastAnswered.evaluation.score}/10
              </span>
            </div>

            <EvaluationPanel evaluation={lastAnswered.evaluation} />

            <button
              onClick={() =>
                nextQuestionRef.current?.scrollIntoView({
                  behavior: "smooth",
                  block: "start",
                })
              }
              className="mt-4 flex items-center gap-2 text-sm text-white/70 hover:text-white transition"
            >
              Next Question <ChevronDown size={15} className="rotate-180" />
            </button>
          </motion.div>
        )}

        {/* Question card */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-6 rounded-2xl bg-white/5 border border-white/10"
        >
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full bg-violet-500/20 text-violet-300">
              {categoryLabel(currentQuestion.category)}
            </span>
            {currentQuestion.generated_by === "fallback" && (
              <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full bg-yellow-500/15 text-yellow-300">
                Fallback question
              </span>
            )}
          </div>

          <h2 className="text-xl leading-relaxed font-medium flex gap-3">
            <MessageSquare size={22} className="text-violet-400 shrink-0 mt-1" />
            <span>{currentQuestion.question_text}</span>
          </h2>

          {currentQuestion.notice && (
            <p className="mt-3 text-yellow-400/90 text-xs">
              {currentQuestion.notice}
            </p>
          )}

          <SourcesSection question={currentQuestion} />

          <form onSubmit={(e) => void submitAnswer(e)} className="mt-5">
            <Textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Write your answer here... (the more specific you are, the better the feedback)"
              rows={5}
              maxLength={6000}
              disabled={submitting || ending}
              className="min-h-32 bg-white/5 border-white/10 text-white placeholder:text-white/40 focus-visible:border-white/30"
            />
            <div className="flex items-center justify-between mt-3">
              <span className="text-white/30 text-xs">
                {answer.length} / 6000
              </span>
              <Button
                type="submit"
                disabled={submitDisabled}
                className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
              >
                {submitting ? (
                  <>
                    <Loader2 size={16} className="animate-spin" /> Evaluating
                    answer...
                  </>
                ) : (
                  "Submit Answer"
                )}
              </Button>
            </div>
          </form>
        </motion.div>

        <div className="flex justify-end">
          <Button
            variant="outline"
            onClick={() => {
              if (window.confirm("End the interview and generate your report?")) {
                void endInterview();
              }
            }}
            disabled={ending || submitting}
            className="border-red-500/30 text-red-300 hover:bg-red-500/10"
          >
            {ending ? (
              <Loader2 size={16} className="animate-spin" />
            ) : null}
            End Interview
          </Button>
        </div>
      </div>
    );
  };

  const renderReport = () => {
    const rep = report;

    return (
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          {backButton("Back")}
          <Button
            onClick={() => void backToHome()}
            className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
          >
            <RotateCcw size={16} /> Start New Interview
          </Button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-4xl font-bold flex items-center gap-3">
              <Trophy size={32} className="text-yellow-400" /> Interview Report
            </h1>
            <p className="text-white/50 mt-2">
              {detail?.job_title || "Role"} · {detail?.company_name || "Company"}
            </p>
          </div>
          {rep && (
            <div className="text-right">
              <span className="text-white/50 text-sm block">Overall score</span>
              <span className={`text-5xl font-bold ${scoreColor(rep.overall_score)}`}>
                {rep.overall_score}
                <span className="text-xl text-white/40">/10</span>
              </span>
            </div>
          )}
        </div>

        {!rep ? (
          <ErrorBanner message="The report is not available yet." />
        ) : (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-6"
          >
            {rep.generated_by === "fallback" && (
              <div className="p-4 rounded-xl bg-yellow-500/10 border border-yellow-500/20 text-yellow-300 text-sm">
                This report was generated with a fallback evaluator because the
                AI service was unavailable.
              </div>
            )}
            {rep.notice && (
              <div className="p-4 rounded-xl bg-white/5 border border-white/10 text-white/60 text-sm">
                {rep.notice}
              </div>
            )}

            {/* Category scores */}
            {rep.category_scores.length > 0 ? (
              <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
                <h2 className="text-lg font-semibold mb-4">
                  Scores by category
                </h2>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={rep.category_scores}>
                      <CartesianGrid
                        strokeDasharray="3 3"
                        stroke="rgba(255,255,255,0.08)"
                      />
                      <XAxis
                        dataKey="category"
                        stroke="#94a3b8"
                        tick={{ fill: "#94a3b8", fontSize: 12 }}
                        tickFormatter={(value) => categoryLabel(String(value))}
                        interval={0}
                      />
                      <YAxis
                        domain={[0, 10]}
                        stroke="#94a3b8"
                        tick={{ fill: "#94a3b8", fontSize: 12 }}
                      />
                      <Tooltip
                        cursor={{ fill: "rgba(255,255,255,0.05)" }}
                        contentStyle={{
                          backgroundColor: "#1e293b",
                          border: "1px solid rgba(255,255,255,0.1)",
                          borderRadius: 12,
                          color: "#f1f5f9",
                        }}
                        labelStyle={{ color: "#cbd5e1" }}
                        formatter={(value) => [`${value}/10`, "Score"]}
                        labelFormatter={(label) =>
                          categoryLabel(String(label))
                        }
                      />
                      <Bar dataKey="score" radius={[8, 8, 0, 0]} maxBarSize={56}>
                        {rep.category_scores.map((c, i) => (
                          <Cell key={i} fill={scoreFill(c.score)} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ) : (
              <p className="text-white/50">
                No questions were answered, so no category breakdown is
                available.
              </p>
            )}

            {/* Summary */}
            {rep.summary && (
              <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
                <h2 className="text-lg font-semibold mb-2">Summary</h2>
                <p className="text-white/70 leading-relaxed">{rep.summary}</p>
              </div>
            )}

            <div className="grid md:grid-cols-2 gap-6">
              {/* Strengths */}
              {rep.strengths.length > 0 && (
                <div className="p-6 rounded-2xl bg-emerald-500/5 border border-emerald-500/20">
                  <h2 className="text-lg font-semibold mb-3 text-emerald-300 flex items-center gap-2">
                    <CheckCircle2 size={18} /> Strengths
                  </h2>
                  <ul className="space-y-2">
                    {rep.strengths.map((s, i) => (
                      <li key={i} className="text-sm text-white/75 flex gap-2">
                        <span className="text-emerald-400">•</span>
                        <span>{s}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Weaknesses */}
              {rep.weaknesses.length > 0 && (
                <div className="p-6 rounded-2xl bg-red-500/5 border border-red-500/20">
                  <h2 className="text-lg font-semibold mb-3 text-red-300 flex items-center gap-2">
                    <ChevronDown size={18} /> Weaknesses
                  </h2>
                  <ul className="space-y-2">
                    {rep.weaknesses.map((w, i) => (
                      <li key={i} className="text-sm text-white/75 flex gap-2">
                        <span className="text-red-400">•</span>
                        <span>{w}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Recommended topics */}
            {rep.recommended_topics.length > 0 && (
              <div className="p-6 rounded-2xl bg-blue-500/5 border border-blue-500/20">
                <h2 className="text-lg font-semibold mb-3 text-blue-300 flex items-center gap-2">
                  <BookOpen size={18} /> Recommended preparation topics
                </h2>
                <div className="flex flex-wrap gap-2">
                  {rep.recommended_topics.map((t, i) => (
                    <span
                      key={i}
                      className="px-3 py-1.5 text-xs rounded-full bg-blue-500/15 text-blue-300 border border-blue-500/20"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="flex flex-wrap justify-end">
              <Button
                onClick={() => void backToHome()}
                className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
              >
                <RotateCcw size={16} /> Start New Interview
              </Button>
            </div>
          </motion.div>
        )}
      </div>
    );
  };

  // -------------------------------------------------------------------------
  // Render switch
  // -------------------------------------------------------------------------

  if (view === "loading") {
    return (
      <div className="flex items-center gap-3 text-white/60 py-16">
        <Loader2 size={20} className="animate-spin" />
        Loading your mock interviews...
      </div>
    );
  }

  switch (view) {
    case "active":
      return renderActive();
    case "report":
      return renderReport();
    case "home":
    default:
      return renderHome();
  }
}

// ---------------------------------------------------------------------------
// Evaluation panel (shared by the active + resume views)
// ---------------------------------------------------------------------------

function EvaluationPanel({ evaluation }: { evaluation: EvaluationOut }) {
  const sections: Array<{
    label: string;
    items: string[];
    tone: "ok" | "warn" | "info";
  }> = [
    { label: "Strengths", items: evaluation.strengths, tone: "ok" },
    { label: "Weaknesses", items: evaluation.weaknesses, tone: "warn" },
    {
      label: "Missing points",
      items: evaluation.missing_points,
      tone: "info",
    },
  ];

  const chipColor = (tone: "ok" | "warn" | "info") => {
    if (tone === "ok")
      return "bg-emerald-500/10 border-emerald-500/20 text-emerald-300";
    if (tone === "warn")
      return "bg-red-500/10 border-red-500/20 text-red-300";
    return "bg-blue-500/10 border-blue-500/20 text-blue-300";
  };

  return (
    <div className="space-y-4">
      {(evaluation.correctness || evaluation.feedback) && (
        <div className="p-4 rounded-xl bg-white/5 border border-white/10">
          {evaluation.feedback && (
            <p className="text-sm text-white/80">{evaluation.feedback}</p>
          )}
          {evaluation.correctness && (
            <p className="text-xs text-white/50 mt-1.5">
              {evaluation.correctness}
            </p>
          )}
        </div>
      )}

      {evaluation.generated_by === "fallback" && (
        <p className="text-yellow-400/90 text-xs">
          This evaluation used a fallback evaluator because the AI service was
          unavailable.
          {evaluation.notice ? ` ${evaluation.notice}` : ""}
        </p>
      )}

      <div className="grid sm:grid-cols-3 gap-3">
        {sections.map(
          (section) =>
            section.items.length > 0 && (
              <div
                key={section.label}
                className={`p-3.5 rounded-xl border ${chipColor(section.tone)}`}
              >
                <p className="text-[11px] uppercase tracking-wider font-medium mb-1.5">
                  {section.label}
                </p>
                <ul className="space-y-1">
                  {section.items.map((item, i) => (
                    <li key={i} className="text-xs leading-relaxed">
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )
        )}
      </div>
    </div>
  );
}