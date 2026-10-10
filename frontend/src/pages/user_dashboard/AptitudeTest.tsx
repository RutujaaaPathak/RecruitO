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
  BookOpen,
  Brain,
  Calculator,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Clock,
  FileText,
  HelpCircle,
  Layers,
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
import { apiTime, parseApiDate } from "../../lib/datetime";

// ---------------------------------------------------------------------------
// Backend response shapes (mirror backend/app/schemas.py)
// ---------------------------------------------------------------------------

interface AptitudeQuestionOut {
  id: number;
  question_index: number;
  category: string;
  question_text: string;
  options: string[];
  generated_by: "llm" | "fallback";
  notice: string | null;
  selected_option: number | null;
}

interface AptitudeCategoryPerformanceOut {
  category: string;
  total: number;
  correct: number;
  percentage: number;
}

interface AptitudeResultsOut {
  score: number;
  total: number;
  percentage: number;
  correct_count: number;
  incorrect_count: number;
  unanswered_count: number;
  passed: boolean;
  pass_percentage: number;
  category_performance: AptitudeCategoryPerformanceOut[];
  expired: boolean;
  model_used: string;
  generated_by: "llm" | "mixed" | "fallback";
  used_fallback: boolean;
  notice: string | null;
}

interface AptitudeTestListOut {
  id: number;
  application_id: number | null;
  section: string;
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

interface AptitudeTestDetailOut {
  id: number;
  application_id: number | null;
  section: string;
  user_id: number;
  job_title: string | null;
  company_name: string | null;
  status: "in_progress" | "completed";
  total_questions: number;
  answered_count: number;
  time_limit_minutes: number;
  started_at: string;
  expires_at: string | null;
  questions: AptitudeQuestionOut[];
  results: AptitudeResultsOut | null;
  generated_by: "llm" | "mixed" | "fallback";
  used_fallback: boolean;
  model_used: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

interface AptitudeConfigOut {
  sections: string[];
  question_count: number;
  section_question_count: number;
  time_limit_minutes: number;
  pass_percentage: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CATEGORY_LABELS: Record<string, string> = {
  quantitative: "Quantitative",
  logical_reasoning: "Logical Reasoning",
  verbal: "Verbal",
};

const OPTION_LETTERS = ["A", "B", "C", "D"];

function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category.replace(/_/g, " ");
}

function errMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

interface SectionCard {
  key: string;
  title: string;
  tagline: string;
  description: string;
  icon: typeof Calculator;
  gradient: string;
  iconColor: string;
  glow: string;
}

// The four practice modes: the three aptitude sections plus a mixed test.
const SECTION_CARDS: SectionCard[] = [
  {
    key: "quantitative",
    title: "Quantitative Aptitude",
    tagline: "Numbers & arithmetic",
    description:
      "Percentages, ratios, averages, speed, profit & loss and mental math.",
    icon: Calculator,
    gradient: "from-violet-600/20 to-blue-600/10",
    iconColor: "text-violet-400",
    glow: "group-hover:shadow-[0_20px_60px_rgba(139,92,246,0.25)] group-hover:ring-violet-500/30",
  },
  {
    key: "logical_reasoning",
    title: "Logical Reasoning",
    tagline: "Patterns & puzzles",
    description:
      "Sequences, coding-decoding, odd-one-out, clock angles and verbal logic.",
    icon: Brain,
    gradient: "from-blue-600/20 to-cyan-500/10",
    iconColor: "text-cyan-400",
    glow: "group-hover:shadow-[0_20px_60px_rgba(59,130,246,0.25)] group-hover:ring-blue-400/30",
  },
  {
    key: "verbal",
    title: "Verbal Ability",
    tagline: "English language",
    description:
      "Synonyms, antonyms, grammar, spelling and sentence-level usage.",
    icon: BookOpen,
    gradient: "from-emerald-600/20 to-teal-500/10",
    iconColor: "text-emerald-400",
    glow: "group-hover:shadow-[0_20px_60px_rgba(16,185,129,0.25)] group-hover:ring-emerald-400/30",
  },
  {
    key: "mixed",
    title: "Full Mixed Test",
    tagline: "All three sections",
    description:
      "Quantitative, logical reasoning and verbal in a single timed test.",
    icon: Layers,
    gradient: "from-amber-600/20 to-orange-500/10",
    iconColor: "text-amber-400",
    glow: "group-hover:shadow-[0_20px_60px_rgba(245,158,11,0.25)] group-hover:ring-amber-400/30",
  },
];

function sectionTitle(section: string | null | undefined): string {
  const key = section || "mixed";
  return (
    SECTION_CARDS.find((card) => card.key === key)?.title ?? "Aptitude Test"
  );
}

function formatDate(iso: string | null): string {
  const date = parseApiDate(iso);
  if (!date) return "—";
  return date.toLocaleDateString(undefined, {
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

export default function AptitudeTest() {
  const [view, setView] = useState<View>("loading");

  const [config, setConfig] = useState<AptitudeConfigOut | null>(null);
  const [tests, setTests] = useState<AptitudeTestListOut[]>([]);
  const [detail, setDetail] = useState<AptitudeTestDetailOut | null>(null);
  const [results, setResults] = useState<AptitudeResultsOut | null>(null);

  const [initError, setInitError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [startingSection, setStartingSection] = useState<string | null>(null);
  const [resumingId, setResumingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [viewingId, setViewingId] = useState<number | null>(null);

  const [currentIndex, setCurrentIndex] = useState(0);
  const [selections, setSelections] = useState<Record<number, number>>({});
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const submittingRef = useRef(false);
  const autoSubmittedRef = useRef(false);
  const [timerLeft, setTimerLeft] = useState<number | null>(null);

  // -------------------------------------------------------------------------
  // Data loading
  // -------------------------------------------------------------------------

  const refreshTests = useCallback(async (): Promise<void> => {
    try {
      const data = await api.get<AptitudeTestListOut[]>("/aptitude-tests");
      setTests(data);
    } catch {
      // Best-effort refresh; the home screen still renders from last state.
    }
  }, []);

  const openTest = useCallback(async (id: number): Promise<void> => {
    autoSubmittedRef.current = false;
    const data = await api.get<AptitudeTestDetailOut>(`/aptitude-tests/${id}`);
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
        const [testsData, configData] = await Promise.all([
          api.get<AptitudeTestListOut[]>("/aptitude-tests"),
          api.get<AptitudeConfigOut>("/aptitude-tests/config"),
        ]);
        if (cancelled) return;
        setTests(testsData);
        setConfig(configData);

        const inProgress = testsData.filter(
          (t) => t.status === "in_progress"
        );
        if (inProgress.length > 0) {
          await openTest(inProgress[0].id);
          return;
        }
        setView("home");
      } catch (e) {
        if (!cancelled) {
          setInitError(errMessage(e, "Failed to load aptitude test data"));
          setView("home");
        }
      }
    };

    void init();
    return () => {
      cancelled = true;
    };
  }, [openTest]);

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------

  const startTest = async (section: string): Promise<void> => {
    autoSubmittedRef.current = false;
    setStartingSection(section);
    setActionError(null);
    try {
      const data = await api.post<AptitudeTestDetailOut>("/aptitude-tests", {
        section,
      });
      setDetail(data);
      setSelections({});
      // Land the candidate on the FIRST question; never on a zero-score page.
      setCurrentIndex(data.questions[0]?.question_index ?? 0);
      setResults(null);
      setTests((prev) => [listOutFromDetail(data), ...prev]);
      setView("active");
    } catch (e) {
      setActionError(errMessage(e, "Failed to start the aptitude test"));
      await refreshTests();
    } finally {
      setStartingSection(null);
    }
  };

  const resumeTest = async (id: number): Promise<void> => {
    setResumingId(id);
    setActionError(null);
    try {
      await openTest(id);
    } catch (e) {
      setActionError(errMessage(e, "Failed to resume the aptitude test"));
    } finally {
      setResumingId(null);
    }
  };

  const viewResult = async (t: AptitudeTestListOut): Promise<void> => {
    setViewingId(t.id);
    setActionError(null);
    try {
      const data = await api.get<AptitudeTestDetailOut>(`/aptitude-tests/${t.id}`);
      setDetail(data);
      setResults(data.results);
      setView("results");
    } catch (e) {
      setActionError(errMessage(e, "Failed to load the results"));
    } finally {
      setViewingId(null);
    }
  };

  const deleteTest = async (t: AptitudeTestListOut): Promise<void> => {
    setDeletingId(t.id);
    setActionError(null);
    try {
      await api.del<void>(`/aptitude-tests/${t.id}`);
      setTests((prev) => prev.filter((x) => x.id !== t.id));
    } catch (e) {
      setActionError(errMessage(e, "Failed to delete the aptitude test"));
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
    await refreshTests();
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
      const updated = await api.post<AptitudeTestDetailOut>(
        `/aptitude-tests/${detail.id}/answer`,
        {
          question_index: currentQuestion.question_index,
          selected_option: selected,
        }
      );
      setDetail(updated);
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
      try {
        await saveCurrentAnswer();
      } catch {
        // The backend rejects an answer save once the timer has elapsed, but
        // submission must still happen: /submit re-checks the deadline and
        // scores the answers that were saved before it (results.expired=true).
      }
      // The backend enforces the deadline: a late submit is auto-scored from
      // the answers saved before the timer ran out (results.expired = true).
      const res = await api.post<AptitudeResultsOut>(
        `/aptitude-tests/${detail.id}/submit`
      );
      setResults(res);
      setDetail((prev) =>
        prev
          ? { ...prev, status: "completed" as const, expires_at: null }
          : prev
      );
      setView("results");
    } catch (e) {
      if (auto) autoSubmittedRef.current = false; // retry on the next tick
      setActionError(errMessage(e, "Failed to submit the aptitude test"));
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
      // expires_at is serialized as naive UTC by the backend; parseApiDate/app
      // treat it as the UTC instant it is, so the countdown can never look
      // already-expired (which used to auto-submit a 0-score test at start).
      const deadlineMs = apiTime(detail.expires_at);
      const remaining =
        deadlineMs == null ? 0 : Math.floor((deadlineMs - Date.now()) / 1000);
      setTimerLeft(remaining);
      if (
        remaining <= 0 &&
        !submittingRef.current &&
        !autoSubmittedRef.current
      ) {
        autoSubmittedRef.current = true;
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

  const inProgressBySection = useMemo(() => {
    const map: Record<string, AptitudeTestListOut> = {};
    tests.forEach((t) => {
      if (t.status === "in_progress") {
        const key = t.section || "mixed";
        if (!map[key]) {
          map[key] = t;
        }
      }
    });
    return map;
  }, [tests]);

  const inProgressTests = useMemo(
    () => tests.filter((t) => t.status === "in_progress"),
    [tests]
  );

  const completedTests = useMemo(
    () => tests.filter((t) => t.status === "completed"),
    [tests]
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
            Aptitude Test
          </h1>
          <p className="text-white/50 mt-2 max-w-2xl">
            Practice aptitude for career readiness — a common test independent
            of any job or company. Pick one section to focus on, or take a
            mixed test covering Quantitative, Logical Reasoning and Verbal.
            Correct answers stay hidden until you submit.
          </p>
        </div>
      </div>

      {initError && <ErrorBanner message={initError} />}
      {actionError && <ErrorBanner message={actionError} />}

      {/* IN-PROGRESS */}
      {inProgressTests.length > 0 && (
        <div className="p-6 rounded-3xl bg-gradient-to-r from-violet-900/30 to-blue-800/20 border border-white/10 shadow-2xl">
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Clock size={18} className="text-violet-300" /> In progress
          </h2>
          <div className="space-y-3">
            {inProgressTests.map((t) => (
              <div
                key={t.id}
                className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <p className="font-semibold">{sectionTitle(t.section)}</p>
                  <p className="text-white/50 text-sm">
                    <span className="text-white/30">
                      {t.time_limit_minutes} min limit
                    </span>
                  </p>
                  <p className="text-white/40 text-xs mt-1">
                    {t.answered_count} of {t.total_questions} answered • started{" "}
                    {formatDate(t.started_at)}
                  </p>
                </div>
                <Button
                  onClick={() => void resumeTest(t.id)}
                  disabled={resumingId === t.id}
                  className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
                >
                  {resumingId === t.id ? (
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

      {/* INSTRUCTIONS */}
      <div className="p-6 rounded-3xl bg-white/5 border border-white/10">
        <h2 className="text-xl font-semibold mb-3 flex items-center gap-2">
          <HelpCircle size={18} className="text-violet-300" /> Before you start
        </h2>
        <ul className="text-white/60 text-sm space-y-2 list-disc pl-5">
          <li>
            Time limit:{" "}
            <span className="text-white font-medium">
              {config?.time_limit_minutes ?? 20} minutes per test.
            </span>
          </li>
          <li>
            {config
              ? `${config.question_count} questions in a mixed test; each single section has up to ${config.section_question_count} questions.`
              : "Each test is a timed multiple-choice quiz."}
          </li>
          <li>
            You need at least{" "}
            <span className="text-white font-medium">
              {config?.pass_percentage ?? 60}%
            </span>{" "}
            to pass.
          </li>
          <li>
            Your answers are saved as you move between questions; you can change
            them until you submit.
          </li>
          <li>The test is auto-submitted when the timer runs out.</li>
        </ul>
      </div>

      {/* PRACTICE MODES */}
      <div>
        <h2 className="text-2xl font-semibold mb-4">Choose a test</h2>
        <div className="grid md:grid-cols-2 gap-5">
          {SECTION_CARDS.map((card) => {
            const Icon = card.icon;
            const inProgress = inProgressBySection[card.key];
            const isStarting = startingSection === card.key;
            const sectionQuestionCount =
              card.key === "mixed"
                ? config?.question_count
                : config?.section_question_count;
            return (
              <motion.div
                key={card.key}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className={`p-6 rounded-2xl bg-gradient-to-br ${card.gradient} border border-white/10 transition flex flex-col gap-3`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="p-3 rounded-2xl bg-white/10 border border-white/10">
                    <Icon size={24} className={card.iconColor} />
                  </div>
                  <span className="text-xs px-2.5 py-1 rounded-full bg-white/10 border border-white/10 text-white/70 whitespace-nowrap">
                    {sectionQuestionCount
                      ? `${sectionQuestionCount} questions`
                      : "Timed test"}{" "}
                    • {config?.time_limit_minutes ?? 20} min
                  </span>
                </div>
                <div>
                  <h3 className="text-lg font-semibold">{card.title}</h3>
                  <p className="text-white/40 text-xs uppercase tracking-wider mt-0.5">
                    {card.tagline}
                  </p>
                  <p className="text-white/50 text-sm mt-2 leading-relaxed">
                    {card.description}
                  </p>
                </div>
                {inProgress ? (
                  <div className="flex items-center justify-between mt-auto">
                    <span className="text-xs text-white/60 flex items-center gap-1.5">
                      <Clock size={12} /> In progress
                    </span>
                    <Button
                      size="sm"
                      onClick={() => void resumeTest(inProgress.id)}
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
                    onClick={() => void startTest(card.key)}
                    disabled={isStarting}
                    className="bg-gradient-to-r from-violet-600 to-blue-600 text-white mt-auto"
                  >
                    {isStarting ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Play size={14} />
                    )}
                    Start Test
                  </Button>
                )}
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* PAST ATTEMPTS */}
      <div>
        <h2 className="text-2xl font-semibold mb-4">Previous attempts</h2>
        {completedTests.length === 0 ? (
          <p className="text-white/50">
            No completed aptitude tests yet. Your results will appear here.
          </p>
        ) : (
          <div className="space-y-3">
            {completedTests.map((t) => (
              <motion.div
                key={t.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <p className="font-semibold">{sectionTitle(t.section)}</p>
                  <p className="text-white/40 text-xs mt-1">
                    {t.total_questions} questions • completed{" "}
                    {formatDate(t.completed_at)}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {t.percentage != null && (
                    <div className="text-right">
                      <span
                        className={`text-xl font-bold ${percentageColor(
                          t.percentage
                        )}`}
                      >
                        {t.percentage}%
                      </span>
                      <span className="block text-[11px] text-white/40 uppercase tracking-wider">
                        {t.passed ? "Passed" : "Failed"}
                      </span>
                    </div>
                  )}
                  <Button
                    size="sm"
                    onClick={() => void viewResult(t)}
                    disabled={viewingId === t.id}
                    className="bg-white/10 text-white hover:bg-white/20"
                  >
                    {viewingId === t.id ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <FileText size={14} />
                    )}
                    View Results
                  </Button>
                  <button
                    onClick={() => void deleteTest(t)}
                    disabled={deletingId === t.id}
                    title="Delete aptitude test"
                    className="text-white/40 hover:text-red-400 transition disabled:opacity-50"
                  >
                    {deletingId === t.id ? (
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
          <h1 className="text-4xl font-bold">Aptitude Test</h1>
          <ErrorBanner message="Could not load the current aptitude test." />
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
            <h1 className="text-3xl font-bold">{sectionTitle(detail.section)}</h1>
            <p className="text-white/50 mt-1">
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
            <RotateCcw size={16} /> Start New Test
          </Button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-4xl font-bold flex items-center gap-3">
              <Trophy size={32} className="text-yellow-400" /> Test Result
            </h1>
            <p className="text-white/50 mt-2">
              {sectionTitle(detail?.section)} · Aptitude Practice
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
                  ? "This practice test was generated by the AI model."
                  : "These practice questions come from the built-in aptitude question bank."}
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
                  Performance by section
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
                <RotateCcw size={16} /> Start New Test
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
        Loading your aptitude tests...
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

function listOutFromDetail(detail: AptitudeTestDetailOut): AptitudeTestListOut {
  return {
    id: detail.id,
    application_id: detail.application_id,
    section: detail.section,
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