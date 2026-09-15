import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Clock,
  FileText,
  HelpCircle,
  Loader2,
  Play,
  RotateCcw,
  Send,
  Trash2,
  Trophy,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "../../lib/api";

// ---------------------------------------------------------------------------
// Backend response shapes (mirror backend/app/schemas.py)
// ---------------------------------------------------------------------------

interface McqQuestionOut {
  id: number;
  question_index: number;
  category: string;
  question_text: string;
  options: string[];
  generated_by: "llm" | "fallback";
  notice: string | null;
  selected_option: number | null;
}

interface McqCategoryPerformanceOut {
  category: string;
  total: number;
  correct: number;
  percentage: number;
}

interface McqResultsOut {
  score: number;
  total: number;
  percentage: number;
  correct_count: number;
  incorrect_count: number;
  unanswered_count: number;
  passed: boolean;
  pass_percentage: number;
  category_performance: McqCategoryPerformanceOut[];
  expired: boolean;
  model_used: string;
  generated_by: "llm" | "mixed" | "fallback";
  used_fallback: boolean;
  notice: string | null;
}

interface McqAssessmentListOut {
  id: number;
  application_id: number;
  job_title: string | null;
  company_name: string | null;
  status: "in_progress" | "completed";
  total_questions: number;
  answered_count: number;
  time_limit_minutes: number;
  score: number | null;
  percentage: number | null;
  passed: boolean | null;
  started_at: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

interface McqAssessmentDetailOut {
  id: number;
  application_id: number;
  user_id: number;
  job_title: string | null;
  company_name: string | null;
  status: "in_progress" | "completed";
  total_questions: number;
  answered_count: number;
  time_limit_minutes: number;
  started_at: string;
  expires_at: string | null;
  questions: McqQuestionOut[];
  results: McqResultsOut | null;
  generated_by: "llm" | "mixed" | "fallback";
  used_fallback: boolean;
  model_used: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
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
  problem_solving: "Problem Solving",
  situational: "Situational",
  behavioral: "Behavioral",
};

const OPTION_LETTERS = ["A", "B", "C", "D"];

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

function formatTime(totalSeconds: number): string {
  const safe = Math.max(0, totalSeconds);
  const m = Math.floor(safe / 60)
    .toString()
    .padStart(2, "0");
  const s = Math.floor(safe % 60)
    .toString()
    .padStart(2, "0");
  return `${m}:${s}`;
}

function percentageColor(pct: number): string {
  if (pct >= 80) return "text-emerald-400";
  if (pct >= 60) return "text-yellow-400";
  return "text-red-400";
}

function barFill(pct: number): string {
  if (pct >= 80) return "#34d399";
  if (pct >= 60) return "#fbbf24";
  return "#f87171";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type View = "loading" | "home" | "active" | "results";

export default function MCQAssessment() {
  const [view, setView] = useState<View>("loading");

  const [apps, setApps] = useState<ApplicationData[]>([]);
  const [assessments, setAssessments] = useState<McqAssessmentListOut[]>([]);
  const [detail, setDetail] = useState<McqAssessmentDetailOut | null>(null);
  const [results, setResults] = useState<McqResultsOut | null>(null);

  const [initError, setInitError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [startingId, setStartingId] = useState<number | null>(null);
  const [resumingId, setResumingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [viewingId, setViewingId] = useState<number | null>(null);

  const [currentIndex, setCurrentIndex] = useState(0);
  const [selections, setSelections] = useState<Record<number, number>>({});
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const submittingRef = useRef(false);
  const [timerLeft, setTimerLeft] = useState<number | null>(null);

  // -------------------------------------------------------------------------
  // Data loading
  // -------------------------------------------------------------------------

  const refreshAssessments = useCallback(async (): Promise<void> => {
    try {
      const data = await api.get<McqAssessmentListOut[]>("/mcq-assessments");
      setAssessments(data);
    } catch {
      // Best-effort refresh; the home screen still renders from last state.
    }
  }, []);

  const openAssessment = useCallback(async (id: number): Promise<void> => {
    const data = await api.get<McqAssessmentDetailOut>(`/mcq-assessments/${id}`);
    setDetail(data);

    const selectionsFromServer: Record<number, number> = {};
    for (const q of data.questions) {
      if (q.selected_option != null) {
        selectionsFromServer[q.question_index] = q.selected_option;
      }
    }
    setSelections(selectionsFromServer);

    if (data.results || data.status === "completed") {
      setResults(data.results);
      setView("results");
    } else {
      // Resume at the first unanswered question.
      const firstUnanswered = data.questions.find(
        (q) => selectionsFromServer[q.question_index] === undefined
      );
      setCurrentIndex(
        firstUnanswered
          ? firstUnanswered.question_index
          : data.questions.length
          ? data.questions[0].question_index
          : 0
      );
      setResults(null);
      setView("active");
    }
    setActionError(null);
  }, []);

  useEffect(() => {
    let cancelled = false;

    const init = async (): Promise<void> => {
      setInitError(null);
      try {
        const [appsData, assessmentsData] = await Promise.all([
          api.get<ApplicationData[]>("/applications"),
          api.get<McqAssessmentListOut[]>("/mcq-assessments"),
        ]);
        if (cancelled) return;
        setApps(appsData);
        setAssessments(assessmentsData);

        const inProgress = assessmentsData.filter(
          (a) => a.status === "in_progress"
        );
        if (inProgress.length > 0) {
          await openAssessment(inProgress[0].id);
          return;
        }
        setView("home");
      } catch (e) {
        if (!cancelled) {
          setInitError(errMessage(e, "Failed to load assessment data"));
          setView("home");
        }
      }
    };

    void init();
    return () => {
      cancelled = true;
    };
  }, [openAssessment]);

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------

  const startAssessment = async (appId: number): Promise<void> => {
    setStartingId(appId);
    setActionError(null);
    try {
      const data = await api.post<McqAssessmentDetailOut>("/mcq-assessments", {
        application_id: appId,
      });
      setDetail(data);
      setSelections({});
      setCurrentIndex(data.questions[0]?.question_index ?? 0);
      setResults(null);
      setAssessments((prev) => [listOutFromDetail(data), ...prev]);
      setView("active");
    } catch (e) {
      setActionError(errMessage(e, "Failed to start the assessment"));
      await refreshAssessments();
    } finally {
      setStartingId(null);
    }
  };

  const resumeAssessment = async (id: number): Promise<void> => {
    setResumingId(id);
    setActionError(null);
    try {
      await openAssessment(id);
    } catch (e) {
      setActionError(errMessage(e, "Failed to resume the assessment"));
    } finally {
      setResumingId(null);
    }
  };

  const viewResult = async (a: McqAssessmentListOut): Promise<void> => {
    setViewingId(a.id);
    setActionError(null);
    try {
      const data = await api.get<McqAssessmentDetailOut>(`/mcq-assessments/${a.id}`);
      setDetail(data);
      setResults(data.results);
      setView("results");
    } catch (e) {
      setActionError(errMessage(e, "Failed to load the results"));
    } finally {
      setViewingId(null);
    }
  };

  const deleteAssessment = async (a: McqAssessmentListOut): Promise<void> => {
    setDeletingId(a.id);
    setActionError(null);
    try {
      await api.del<void>(`/mcq-assessments/${a.id}`);
      setAssessments((prev) => prev.filter((x) => x.id !== a.id));
    } catch (e) {
      setActionError(errMessage(e, "Failed to delete the assessment"));
    } finally {
      setDeletingId(null);
    }
  };

  const backToHome = async (): Promise<void> => {
    setView("home");
    setDetail(null);
    setResults(null);
    setSelections({});
    setCurrentIndex(0);
    setActionError(null);
    await refreshAssessments();
  };

  // -------------------------------------------------------------------------
  // Answer saving + submission
  // -------------------------------------------------------------------------

  const currentQuestion = detail?.questions[currentIndex] ?? null;

  const saveCurrentAnswer = useCallback(async (): Promise<void> => {
    if (!detail || !currentQuestion) return;
    const selected = selections[currentQuestion.question_index];
    if (selected === undefined) return;

    const serverSelected = currentQuestion.selected_option ?? null;
    if (selected === serverSelected) return;

    setSaving(true);
    try {
      await api.post<McqAssessmentDetailOut>(
        `/mcq-assessments/${detail.id}/answer`,
        {
          question_index: currentQuestion.question_index,
          selected_option: selected,
        }
      );
      // The backend response carries the refreshed saved selection + count.
    } catch (e) {
      setActionError(
        errMessage(e, "Failed to save this answer. Check the timer.")
      );
      throw e;
    } finally {
      setSaving(false);
    }
  }, [currentQuestion, detail, selections]);

  const goTo = async (index: number): Promise<void> => {
    if (!detail || saving || submitting) return;
    try {
      await saveCurrentAnswer();
    } catch {
      return; // keep the user on the question; the error is shown above
    }
    setCurrentIndex(index);
    setActionError(null);
  };

  const submitTest = async (auto = false): Promise<void> => {
    if (!detail || submittingRef.current) return;
    if (!auto && !window.confirm("Submit your answers and see the results?")) {
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setActionError(null);
    try {
      await saveCurrentAnswer();
      // The backend enforces the deadline: a late submit is auto-scored from
      // the answers saved before the timer ran out (results.expired = true).
      const res = await api.post<McqResultsOut>(
        `/mcq-assessments/${detail.id}/submit`
      );
      setResults(res);
      setDetail((prev) =>
        prev ? { ...prev, status: "completed" as const } : prev
      );
      setView("results");
    } catch (e) {
      setActionError(errMessage(e, "Failed to submit the assessment"));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  // Local countdown from the backend-enforced deadline.
  const submitRef = useRef<(auto?: boolean) => Promise<void>>(async () => {});
  submitRef.current = submitTest;

  useEffect(() => {
    if (view !== "active" || !detail?.expires_at) return;

    const tick = (): void => {
      const remaining = Math.floor(
        (new Date(detail.expires_at as string).getTime() - Date.now()) / 1000
      );
      setTimerLeft(remaining);
      if (remaining <= 0 && !submittingRef.current) {
        void submitRef.current(true);
      }
    };
    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, [view, detail?.id, detail?.expires_at]);

  // -------------------------------------------------------------------------
  // Derived state
  // -------------------------------------------------------------------------

  const inProgressByApp = useMemo(() => {
    const map: Record<number, McqAssessmentListOut> = {};
    assessments.forEach((a) => {
      if (a.status === "in_progress" && !map[a.application_id]) {
        map[a.application_id] = a;
      }
    });
    return map;
  }, [assessments]);

  const inProgressAssessments = useMemo(
    () => assessments.filter((a) => a.status === "in_progress"),
    [assessments]
  );

  const completedAssessments = useMemo(
    () => assessments.filter((a) => a.status === "completed"),
    [assessments]
  );

  const localAnswered = useMemo(
    () =>
      detail
        ? detail.questions.filter(
            (q) => selections[q.question_index] !== undefined
          ).length
        : 0,
    [detail, selections]
  );

  const totalQuestions = detail?.total_questions ?? 0;
  const progress =
    totalQuestions > 0 ? (localAnswered / totalQuestions) * 100 : 0;

  // -------------------------------------------------------------------------
  // Render helpers
  // -------------------------------------------------------------------------

  const ErrorBanner = ({ message }: { message: string }) => (
    <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
      {message}
    </div>
  );

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
            <ClipboardList size={32} className="text-violet-400" />
            MCQ Assessment
          </h1>
          <p className="text-white/50 mt-2">
            Take a timed, 20-question multiple-choice test for the roles you've
            applied to. Correct answers stay hidden until you submit.
          </p>
        </div>
      </div>

      {initError && <ErrorBanner message={initError} />}
      {actionError && <ErrorBanner message={actionError} />}

      {/* IN-PROGRESS */}
      {inProgressAssessments.length > 0 && (
        <div className="p-6 rounded-3xl bg-gradient-to-r from-violet-900/30 to-blue-800/20 border border-white/10 shadow-2xl">
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Clock size={18} className="text-violet-300" /> In progress
          </h2>
          <div className="space-y-3">
            {inProgressAssessments.map((a) => (
              <div
                key={a.id}
                className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <p className="font-semibold">{a.job_title || "Role"}</p>
                  <p className="text-white/50 text-sm">
                    {a.company_name || "Company"}{" "}
                    <span className="text-white/30">
                      • {a.time_limit_minutes} min limit
                    </span>
                  </p>
                  <p className="text-white/40 text-xs mt-1">
                    {a.answered_count} of {a.total_questions} answered • started{" "}
                    {formatDate(a.started_at)}
                  </p>
                </div>
                <Button
                  onClick={() => void resumeAssessment(a.id)}
                  disabled={resumingId === a.id}
                  className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
                >
                  {resumingId === a.id ? (
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
            You don't have any applications yet. Apply to a job first so you
            can take an assessment for it.
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
                      {app.match_score != null ? ` • ATS ${app.match_score}%` : ""}
                    </p>
                  </div>
                  {inProgress ? (
                    <div className="flex items-center justify-between mt-auto">
                      <span className="text-xs text-violet-300 flex items-center gap-1.5">
                        <Clock size={12} /> In progress
                      </span>
                      <Button
                        size="sm"
                        onClick={() => void resumeAssessment(inProgress.id)}
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
                      onClick={() => void startAssessment(app.id)}
                      disabled={isStarting}
                      className="bg-gradient-to-r from-violet-600 to-blue-600 text-white mt-auto"
                    >
                      {isStarting ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Play size={14} />
                      )}
                      Start Assessment
                    </Button>
                  )}
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      {/* PAST ATTEMPTS */}
      <div>
        <h2 className="text-2xl font-semibold mb-4">Previous attempts</h2>
        {completedAssessments.length === 0 ? (
          <p className="text-white/50">
            No completed assessments yet. Your results will appear here.
          </p>
        ) : (
          <div className="space-y-3">
            {completedAssessments.map((a) => (
              <motion.div
                key={a.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <p className="font-semibold">
                    {a.job_title || "Role"}
                    <span className="ml-2 text-white/40 text-sm font-normal">
                      {a.company_name || "Company"}
                    </span>
                  </p>
                  <p className="text-white/40 text-xs mt-1">
                    {a.total_questions} questions • completed{" "}
                    {formatDate(a.completed_at)}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {a.percentage != null && (
                    <div className="text-right">
                      <span
                        className={`text-xl font-bold ${percentageColor(
                          a.percentage
                        )}`}
                      >
                        {a.percentage}%
                      </span>
                      <span className="block text-[11px] text-white/40 uppercase tracking-wider">
                        {a.passed ? "Passed" : "Failed"}
                      </span>
                    </div>
                  )}
                  <Button
                    size="sm"
                    onClick={() => void viewResult(a)}
                    disabled={viewingId === a.id}
                    className="bg-white/10 text-white hover:bg-white/20"
                  >
                    {viewingId === a.id ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <FileText size={14} />
                    )}
                    View Results
                  </Button>
                  <button
                    onClick={() => void deleteAssessment(a)}
                    disabled={deletingId === a.id}
                    title="Delete assessment"
                    className="text-white/40 hover:text-red-400 transition disabled:opacity-50"
                  >
                    {deletingId === a.id ? (
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
          <h1 className="text-4xl font-bold">MCQ Assessment</h1>
          <ErrorBanner message="Could not load the current assessment." />
        </div>
      );
    }

    const qNumber = currentQuestion.question_index + 1;
    const selected = selections[currentQuestion.question_index];
    const isFirst = currentIndex === 0;
    const isLast = currentIndex === totalQuestions - 1;
    const timerDanger =
      timerLeft != null && timerLeft <= 60 && !submitting && !saving;

    return (
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          {backButton("Back")}
          <span
            className={`flex items-center gap-2 text-xs px-3 py-1.5 rounded-full border ${
              timerDanger
                ? "bg-red-500/15 border-red-500/30 text-red-300"
                : "bg-white/10 border-white/10 text-white/70"
            }`}
          >
            <Clock size={13} className="text-yellow-400" />
            {timerLeft != null ? formatTime(timerLeft) : "—"}
            {submitting ? (
              <Loader2 size={13} className="animate-spin" />
            ) : null}
          </span>
        </div>

        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">{detail.job_title || "Role"}</h1>
            <p className="text-white/50 mt-1">
              {detail.company_name || "Company"} •{" "}
              {detail.time_limit_minutes} minute timer
            </p>
          </div>
          <span className="text-sm text-white/60">
            Question <span className="text-white font-semibold">{qNumber}</span>{" "}
            of {detail.total_questions}
          </span>
        </div>

        {/* Progress bar */}
        <div>
          <div className="flex items-center justify-between text-xs text-white/50 mb-1.5">
            <span>
              {localAnswered} of {detail.total_questions} answered
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

        {timerDanger && !submitting && (
          <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-sm">
            Less than a minute left — your answers will be auto-submitted when
            the timer runs out.
          </div>
        )}

        {/* Question card */}
        <motion.div
          key={currentQuestion.question_index}
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
            <HelpCircle size={22} className="text-violet-400 shrink-0 mt-1" />
            <span>{currentQuestion.question_text}</span>
          </h2>

          {currentQuestion.notice && (
            <p className="mt-3 text-yellow-400/90 text-xs">
              {currentQuestion.notice}
            </p>
          )}

          {/* Options */}
          <div className="mt-6 space-y-3">
            {currentQuestion.options.map((option, optionIndex) => {
              const isSelected = selected === optionIndex;
              return (
                <button
                  key={optionIndex}
                  type="button"
                  onClick={() =>
                    setSelections((prev) => ({
                      ...prev,
                      [currentQuestion.question_index]: optionIndex,
                    }))
                  }
                  disabled={submitting || saving}
                  className={`w-full text-left p-4 rounded-xl border transition flex items-start gap-3 ${
                    isSelected
                      ? "bg-violet-500/15 border-violet-500/40"
                      : "bg-white/5 border-white/10 hover:bg-white/10"
                  }`}
                >
                  <span
                    className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold border ${
                      isSelected
                        ? "bg-violet-500 text-white border-violet-400"
                        : "border-white/20 text-white/50"
                    }`}
                  >
                    {OPTION_LETTERS[optionIndex]}
                  </span>
                  <span className="text-white/85 leading-relaxed">
                    {option}
                  </span>
                  {isSelected && (
                    <CheckCircle2
                      size={18}
                      className="ml-auto shrink-0 text-violet-400 mt-0.5"
                    />
                  )}
                </button>
              );
            })}
          </div>

          <p className="mt-4 text-xs text-white/35">
            {selected !== undefined
              ? `Selected ${OPTION_LETTERS[selected]} — you can change your answer before submitting`
              : "Correct answers are never shown during the test."}
          </p>
        </motion.div>

        {/* Navigation */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Button
            variant="outline"
            onClick={() => void goTo(currentIndex - 1)}
            disabled={isFirst || saving || submitting}
            className="border-white/15 text-white/70 hover:bg-white/5"
          >
            <ChevronLeft size={16} />
            {saving ? (
              <Loader2 size={14} className="animate-spin" />
            ) : null}
            Previous
          </Button>

          <div className="flex items-center gap-2">
            {!isLast ? (
              <Button
                onClick={() => void goTo(currentIndex + 1)}
                disabled={saving || submitting}
                className="bg-white/10 text-white hover:bg-white/15"
              >
                Next
                <ChevronRight size={16} />
              </Button>
            ) : null}
            <Button
              onClick={() => void submitTest(false)}
              disabled={submitting || saving || timerLeft === 0}
              className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
            >
              {submitting ? (
                <>
                  <Loader2 size={16} className="animate-spin" /> Submitting...
                </>
              ) : (
                <>
                  <Send size={15} /> Submit Test
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    );
  };

  const renderResults = () => {
    const res = results;

    return (
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          {backButton("Back")}
          <Button
            onClick={() => void backToHome()}
            className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
          >
            <RotateCcw size={16} /> Start New Assessment
          </Button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-4xl font-bold flex items-center gap-3">
              <Trophy size={32} className="text-yellow-400" /> Assessment Result
            </h1>
            <p className="text-white/50 mt-2">
              {detail?.job_title || "Role"} · {detail?.company_name || "Company"}
            </p>
          </div>
          {res && (
            <div className="text-right">
              <span className="text-white/50 text-sm block">
                Score {res.score}/{res.total}
              </span>
              <span className={`text-5xl font-bold ${percentageColor(res.percentage)}`}>
                {res.percentage}%
              </span>
              <span
                className={`block mt-1 text-xs px-3 py-1 rounded-full inline-flex items-center gap-1.5 ${
                  res.passed
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-red-500/15 text-red-300"
                }`}
              >
                {res.passed ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                {res.passed ? "Passed" : "Failed"} · {res.pass_percentage}% to pass
              </span>
            </div>
          )}
        </div>

        {!res ? (
          <ErrorBanner message="The results are not available yet." />
        ) : (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-6"
          >
            {res.expired && (
              <div className="p-4 rounded-xl bg-yellow-500/10 border border-yellow-500/20 text-yellow-300 text-sm">
                The timer ran out, so this attempt was auto-submitted. Answers
                saved before the deadline were scored.
              </div>
            )}
            {res.used_fallback && (
              <div className="p-4 rounded-xl bg-white/5 border border-white/10 text-white/60 text-sm">
                {res.generated_by === "llm"
                  ? "This assessment was generated by the AI model."
                  : "These questions came from the fallback question bank because the AI service was unavailable."}
                {res.notice ? ` ${res.notice}` : ""}
              </div>
            )}

            {/* Stat cards */}
            <div className="grid sm:grid-cols-3 gap-4">
              <div className="p-5 rounded-2xl bg-emerald-500/5 border border-emerald-500/20">
                <p className="text-[11px] uppercase tracking-wider text-emerald-300 mb-1 flex items-center gap-1.5">
                  <CheckCircle2 size={13} /> Correct
                </p>
                <p className="text-3xl font-bold text-emerald-400">
                  {res.correct_count}
                </p>
              </div>
              <div className="p-5 rounded-2xl bg-red-500/5 border border-red-500/20">
                <p className="text-[11px] uppercase tracking-wider text-red-300 mb-1 flex items-center gap-1.5">
                  <XCircle size={13} /> Incorrect
                </p>
                <p className="text-3xl font-bold text-red-400">
                  {res.incorrect_count}
                </p>
              </div>
              <div className="p-5 rounded-2xl bg-white/5 border border-white/10">
                <p className="text-[11px] uppercase tracking-wider text-white/40 mb-1 flex items-center gap-1.5">
                  <Clock size={13} /> Unanswered
                </p>
                <p className="text-3xl font-bold text-white/70">
                  {res.unanswered_count}
                </p>
              </div>
            </div>

            {/* Category-wise performance */}
            {res.category_performance.length > 0 ? (
              <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
                <h2 className="text-lg font-semibold mb-4">
                  Performance by category
                </h2>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={res.category_performance}>
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
                        domain={[0, 100]}
                        unit="%"
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
                        formatter={(value) => [
                          `${value ?? 0}%`,
                          "Correct",
                        ]}
                        labelFormatter={(label) =>
                          categoryLabel(String(label))
                        }
                      />
                      <Bar
                        dataKey="percentage"
                        radius={[8, 8, 0, 0]}
                        maxBarSize={56}
                      >
                        {res.category_performance.map((c, i) => (
                          <Cell key={i} fill={barFill(c.percentage)} />
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

            <div className="flex flex-wrap justify-end">
              <Button
                onClick={() => void backToHome()}
                className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
              >
                <RotateCcw size={16} /> Start New Assessment
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
        Loading your assessments...
      </div>
    );
  }

  switch (view) {
    case "active":
      return renderActive();
    case "results":
      return renderResults();
    case "home":
    default:
      return renderHome();
  }
}

function listOutFromDetail(detail: McqAssessmentDetailOut): McqAssessmentListOut {
  return {
    id: detail.id,
    application_id: detail.application_id,
    job_title: detail.job_title,
    company_name: detail.company_name,
    status: detail.status,
    total_questions: detail.total_questions,
    answered_count: detail.answered_count,
    time_limit_minutes: detail.time_limit_minutes,
    score: detail.results?.score ?? null,
    percentage: detail.results?.percentage ?? null,
    passed: detail.results?.passed ?? null,
    started_at: detail.started_at,
    completed_at: detail.completed_at,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  };
}