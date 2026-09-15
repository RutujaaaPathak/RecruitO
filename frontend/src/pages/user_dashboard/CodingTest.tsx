import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Braces,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Code2,
  Cpu,
  FileText,
  Lightbulb,
  ListChecks,
  Loader2,
  Play,
  RotateCcw,
  Send,
  Terminal,
  Trash2,
  Trophy,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "../../lib/api";

interface CodingTestCaseResultOut {
  case_index: number;
  passed: boolean;
  status: string;
  stdout: string;
  stderr: string;
  time_ms: number;
}

interface CodingRunOut {
  problem_index: number;
  language: string;
  compile_error: boolean;
  compile_stderr: string;
  test_results: CodingTestCaseResultOut[];
}

interface CodingSubmissionOut {
  problem_index: number;
  language: string;
  status: string;
  passed_cases: number;
  total_cases: number;
  score: number;
  execution_time_ms: number | null;
  error_message: string | null;
  results: CodingTestCaseResultOut[];
  created_at: string;
}

interface SampleCase {
  input: string;
  expected: string;
}

interface CodingProblemOut {
  id: number;
  problem_index: number;
  title: string;
  category: string;
  difficulty: string;
  description: string;
  input_format: string;
  output_format: string;
  constraints: string;
  sample_cases: SampleCase[];
  supported_languages: string[];
  submission: CodingSubmissionOut | null;
}

interface CodingTestDetailOut {
  id: number;
  application_id: number;
  user_id: number;
  job_title: string | null;
  company_name: string | null;
  status: "in_progress" | "completed";
  total_problems: number;
  solved_count: number;
  score: number | null;
  passed: boolean | null;
  pass_percentage: number;
  problems: CodingProblemOut[];
  started_at: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

interface CodingTestListOut {
  id: number;
  application_id: number;
  job_title: string | null;
  company_name: string | null;
  status: "in_progress" | "completed";
  total_problems: number;
  solved_count: number;
  score: number | null;
  passed: boolean | null;
  pass_percentage: number;
  started_at: string;
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

const LANGUAGES = ["python", "java", "cpp"] as const;
type Language = (typeof LANGUAGES)[number];

const LANGUAGE_LABELS: Record<Language, string> = {
  python: "Python",
  java: "Java",
  cpp: "C++",
};

const DIFFICULTY_COLORS: Record<string, string> = {
  easy: "text-emerald-300 bg-emerald-500/15 border-emerald-500/30",
  medium: "text-yellow-300 bg-yellow-500/15 border-yellow-500/30",
  hard: "text-red-300 bg-red-500/15 border-red-500/30",
};

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

function scoreColor(pct: number): string {
  if (pct >= 80) return "text-emerald-400";
  if (pct >= 60) return "text-yellow-400";
  return "text-red-400";
}

type View = "loading" | "home" | "active" | "results";

export default function CodingTest() {
  const [view, setView] = useState<View>("loading");

  const [apps, setApps] = useState<ApplicationData[]>([]);
  const [tests, setTests] = useState<CodingTestListOut[]>([]);
  const [detail, setDetail] = useState<CodingTestDetailOut | null>(null);

  const [initError, setInitError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [startingId, setStartingId] = useState<number | null>(null);
  const [resumingId, setResumingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [viewingId, setViewingId] = useState<number | null>(null);

  const [activeIndex, setActiveIndex] = useState(0);
  const [codeByProblem, setCodeByProblem] = useState<Record<number, string>>({});
  const [languageByProblem, setLanguageByProblem] = useState<
    Record<number, Language>
  >({});
  const [runResult, setRunResult] = useState<CodingRunOut | null>(null);
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [finishing, setFinishing] = useState(false);

  const runningRef = useRef(false);

  const codeStorageKey = (testId: number, problemIndex: number): string =>
    `recruito.coding.${testId}.problem.${problemIndex}`;

  // -------------------------------------------------------------------------
  // Data loading
  // -------------------------------------------------------------------------

  const refreshTests = useCallback(async (): Promise<void> => {
    try {
      const data = await api.get<CodingTestListOut[]>("/coding-tests");
      setTests(data);
    } catch {
      // Best-effort refresh; the home screen still renders from last state.
    }
  }, []);

  const restoreCode = useCallback((testId: number, detail_: CodingTestDetailOut): void => {
    const restored: Record<number, string> = {};
    const languages: Record<number, Language> = {};
    for (const p of detail_.problems) {
      const saved = localStorage.getItem(
        codeStorageKey(testId, p.problem_index)
      );
      if (saved) restored[p.problem_index] = saved;
      if (p.submission) {
        const lang = p.submission.language as Language;
        if (LANGUAGES.includes(lang)) languages[p.problem_index] = lang;
      }
    }
    setCodeByProblem(restored);
    setLanguageByProblem(languages);
  }, []);

  const openTest = useCallback(async (id: number): Promise<void> => {
    const data = await api.get<CodingTestDetailOut>(`/coding-tests/${id}`);
    setDetail(data);
    restoreCode(id, data);
    if (data.status === "completed") {
      setView("results");
    } else {
      setActiveIndex(0);
      setRunResult(null);
      setView("active");
    }
    setActionError(null);
  }, [restoreCode]);

  useEffect(() => {
    let cancelled = false;

    const init = async (): Promise<void> => {
      setInitError(null);
      try {
        const [appsData, testsData] = await Promise.all([
          api.get<ApplicationData[]>("/applications"),
          api.get<CodingTestListOut[]>("/coding-tests"),
        ]);
        if (cancelled) return;
        setApps(appsData);
        setTests(testsData);

        const inProgress = testsData.filter((t) => t.status === "in_progress");
        if (inProgress.length > 0) {
          await openTest(inProgress[0].id);
          return;
        }
        setView("home");
      } catch (e) {
        if (!cancelled) {
          setInitError(errMessage(e, "Failed to load coding test data"));
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

  const startTest = async (appId: number): Promise<void> => {
    setStartingId(appId);
    setActionError(null);
    try {
      const data = await api.post<CodingTestDetailOut>("/coding-tests", {
        application_id: appId,
      });
      setDetail(data);
      restoreCode(data.id, data);
      setCodeByProblem({});
      setLanguageByProblem({});
      setActiveIndex(0);
      setRunResult(null);
      setTests((prev) => [listOutFromDetail(data), ...prev]);
      setView("active");
    } catch (e) {
      setActionError(errMessage(e, "Failed to start the coding test"));
      await refreshTests();
    } finally {
      setStartingId(null);
    }
  };

  const resumeTest = async (id: number): Promise<void> => {
    setResumingId(id);
    setActionError(null);
    try {
      await openTest(id);
    } catch (e) {
      setActionError(errMessage(e, "Failed to resume the coding test"));
    } finally {
      setResumingId(null);
    }
  };

  const viewResult = async (t: CodingTestListOut): Promise<void> => {
    setViewingId(t.id);
    setActionError(null);
    try {
      const data = await api.get<CodingTestDetailOut>(`/coding-tests/${t.id}`);
      setDetail(data);
      setView("results");
    } catch (e) {
      setActionError(errMessage(e, "Failed to load the results"));
    } finally {
      setViewingId(null);
    }
  };

  const deleteTest = async (t: CodingTestListOut): Promise<void> => {
    setDeletingId(t.id);
    setActionError(null);
    try {
      await api.del<void>(`/coding-tests/${t.id}`);
      setTests((prev) => prev.filter((x) => x.id !== t.id));
    } catch (e) {
      setActionError(errMessage(e, "Failed to delete the coding test"));
    } finally {
      setDeletingId(null);
    }
  };

  const backToHome = async (): Promise<void> => {
    setView("home");
    setDetail(null);
    setRunResult(null);
    setActionError(null);
    await refreshTests();
  };

  const setCode = (index: number, value: string): void => {
    setCodeByProblem((prev) => ({ ...prev, [index]: value }));
    if (detail) {
      localStorage.setItem(codeStorageKey(detail.id, index), value);
    }
  };

  const activeProblem = detail?.problems[activeIndex] ?? null;
  const activeCode = activeProblem
    ? codeByProblem[activeProblem.problem_index] ?? ""
    : "";
  const activeLanguage = activeProblem
    ? languageByProblem[activeProblem.problem_index] ?? "python"
    : "python";

  const runSample = async (): Promise<void> => {
    if (!detail || !activeProblem || runningRef.current) return;
    runningRef.current = true;
    setRunning(true);
    setActionError(null);
    try {
      const res = await api.post<CodingRunOut>(
        `/coding-tests/${detail.id}/run`,
        {
          problem_index: activeProblem.problem_index,
          language: activeLanguage,
          code: activeCode.length > 0 ? activeCode : " ",
        }
      );
      setRunResult(res);
    } catch (e) {
      setActionError(errMessage(e, "Failed to run your code"));
    } finally {
      runningRef.current = false;
      setRunning(false);
    }
  };

  const submitSolution = async (): Promise<void> => {
    if (!detail || !activeProblem || runningRef.current) return;
    if (
      !window.confirm(
        "Submit this solution for grading against the hidden test cases?"
      )
    ) {
      return;
    }
    runningRef.current = true;
    setSubmitting(true);
    setActionError(null);
    try {
      const res = await api.post<CodingSubmissionOut>(
        `/coding-tests/${detail.id}/submit`,
        {
          problem_index: activeProblem.problem_index,
          language: activeLanguage,
          code: activeCode.length > 0 ? activeCode : " ",
        }
      );
      setDetail((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          problems: prev.problems.map((p) =>
            p.problem_index === res.problem_index
              ? { ...p, submission: res }
              : p
          ),
        };
      });
      await refreshTests();
    } catch (e) {
      setActionError(errMessage(e, "Failed to submit your solution"));
    } finally {
      runningRef.current = false;
      setSubmitting(false);
    }
  };

  const finishTest = async (): Promise<void> => {
    if (!detail) return;
    if (
      !window.confirm(
        "Finish this coding test? You can no longer run or submit code after finishing."
      )
    ) {
      return;
    }
    setFinishing(true);
    setActionError(null);
    try {
      const data = await api.post<CodingTestDetailOut>(
        `/coding-tests/${detail.id}/finish`
      );
      setDetail(data);
      await refreshTests();
      setView("results");
    } catch (e) {
      setActionError(errMessage(e, "Failed to finish the coding test"));
    } finally {
      setFinishing(false);
    }
  };

  // -------------------------------------------------------------------------
  // Derived state
  // -------------------------------------------------------------------------

  const inProgressByApp = useMemo(() => {
    const map: Record<number, CodingTestListOut> = {};
    tests.forEach((t) => {
      if (t.status === "in_progress" && !map[t.application_id]) {
        map[t.application_id] = t;
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

  const solvedCount = useMemo(
    () =>
      detail
        ? detail.problems.filter(
            (p) => p.submission?.status === "passed"
          ).length
        : 0,
    [detail]
  );

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

  const DifficultyBadge = ({ difficulty }: { difficulty: string }) => (
    <span
      className={`text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full border capitalize ${
        DIFFICULTY_COLORS[difficulty] ?? "bg-white/10 border-white/10 text-white/60"
      }`}
    >
      {difficulty}
    </span>
  );

  const statusIcon = (status: string | null | undefined) => {
    if (status === "passed") {
      return <CheckCircle2 size={16} className="text-emerald-400" />;
    }
    if (status === "failed" || status === "error") {
      return <XCircle size={16} className="text-red-400" />;
    }
    return (
      <span className="w-4 h-4 rounded-full border-2 border-white/20" />
    );
  };

  // -------------------------------------------------------------------------
  // Screens
  // -------------------------------------------------------------------------

  const renderHome = () => (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold flex items-center gap-3">
            <Code2 size={32} className="text-violet-400" />
            Coding Test
          </h1>
          <p className="text-white/50 mt-2">
            Solve programming challenges in Python, Java or C++. Your score is
            based on the hidden test cases your solution passes.
          </p>
        </div>
      </div>

      {initError && <ErrorBanner message={initError} />}
      {actionError && <ErrorBanner message={actionError} />}

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
                  <p className="font-semibold">{t.job_title || "Role"}</p>
                  <p className="text-white/50 text-sm">
                    {t.company_name || "Company"}
                  </p>
                  <p className="text-white/40 text-xs mt-1">
                    {t.solved_count} of {t.total_problems} solved • started{" "}
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

      <div>
        <h2 className="text-2xl font-semibold mb-4">Pick an application</h2>
        {apps.length === 0 ? (
          <p className="text-white/50">
            You don't have any applications yet. Apply to a job first so you
            can take a coding test for it.
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
                      onClick={() => void startTest(app.id)}
                      disabled={isStarting}
                      className="bg-gradient-to-r from-violet-600 to-blue-600 text-white mt-auto"
                    >
                      {isStarting ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Play size={14} />
                      )}
                      Start Coding Test
                    </Button>
                  )}
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      <div>
        <h2 className="text-2xl font-semibold mb-4">Previous attempts</h2>
        {completedTests.length === 0 ? (
          <p className="text-white/50">
            No completed coding tests yet. Your results will appear here.
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
                  <p className="font-semibold">
                    {t.job_title || "Role"}
                    <span className="ml-2 text-white/40 text-sm font-normal">
                      {t.company_name || "Company"}
                    </span>
                  </p>
                  <p className="text-white/40 text-xs mt-1">
                    {t.total_problems} problems • completed{" "}
                    {formatDate(t.completed_at)}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {t.score != null && (
                    <div className="text-right">
                      <span
                        className={`text-xl font-bold ${scoreColor(t.score)}`}
                      >
                        {t.score}%
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
                    title="Delete coding test"
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
    if (!detail || !activeProblem) {
      return (
        <div className="space-y-8">
          <h1 className="text-4xl font-bold">Coding Test</h1>
          <ErrorBanner message="Could not load the current coding test." />
        </div>
      );
    }

    const problem = activeProblem;
    const runResults = runResult?.test_results ?? [];

    return (
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          {backButton("Back")}
          <Button
            onClick={() => void finishTest()}
            disabled={finishing || running || submitting}
            className="bg-gradient-to-r from-emerald-600 to-blue-600 text-white"
          >
            {finishing ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Send size={15} />
            )}
            Finish Test
          </Button>
        </div>

        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">
              {detail.job_title || "Role"}
            </h1>
            <p className="text-white/50 mt-1">
              {detail.company_name || "Company"} • {detail.total_problems}{" "}
              problems • no timer
            </p>
          </div>
          <span className="text-sm text-white/60">
            Solved{" "}
            <span className="text-white font-semibold">
              {detail.solved_count || solvedCount}
            </span>{" "}
            of {detail.total_problems}
          </span>
        </div>

        {actionError && <ErrorBanner message={actionError} />}

        {/* Problem selector */}
        <div className="flex flex-wrap gap-2">
          {detail.problems.map((p, index) => {
            const isActive = index === activeIndex;
            const sub = p.submission;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  setActiveIndex(index);
                  setRunResult(null);
                  setActionError(null);
                }}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border text-sm transition ${
                  isActive
                    ? "bg-violet-500/15 border-violet-500/40 text-white"
                    : "bg-white/5 border-white/10 text-white/60 hover:bg-white/10"
                }`}
              >
                {statusIcon(sub?.status ?? null)}
                <span>
                  {index + 1}. {p.title}
                </span>
                {sub && (
                  <span className="text-[11px] text-white/40">
                    {sub.score}%
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Problem statement */}
        <motion.div
          key={problem.problem_index}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-6 rounded-2xl bg-white/5 border border-white/10"
        >
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full bg-violet-500/20 text-violet-300">
              {problem.category.replace(/_/g, " ")}
            </span>
            <DifficultyBadge difficulty={problem.difficulty} />
            {problem.submission && (
              <span
                className={`text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full ${
                  problem.submission.status === "passed"
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-red-500/15 text-red-300"
                }`}
              >
                {problem.submission.status === "passed"
                  ? "Solved"
                  : problem.submission.status === "error"
                  ? "Error"
                  : "Attempted"}
              </span>
            )}
          </div>

          <h2 className="text-2xl font-bold flex items-center gap-3 mb-4">
            <Braces size={22} className="text-violet-400" />
            {problem.title}
          </h2>

          <p className="text-white/80 leading-relaxed whitespace-pre-wrap mb-5">
            {problem.description}
          </p>

          <div className="grid md:grid-cols-2 gap-4 mb-5">
            <div className="p-4 rounded-xl bg-black/20 border border-white/10">
              <h3 className="text-xs uppercase tracking-wider text-violet-300 mb-1.5 flex items-center gap-1.5">
                <Terminal size={13} /> Input format
              </h3>
              <p className="text-white/70 text-sm whitespace-pre-wrap">
                {problem.input_format}
              </p>
            </div>
            <div className="p-4 rounded-xl bg-black/20 border border-white/10">
              <h3 className="text-xs uppercase tracking-wider text-violet-300 mb-1.5 flex items-center gap-1.5">
                <ListChecks size={13} /> Output format
              </h3>
              <p className="text-white/70 text-sm whitespace-pre-wrap">
                {problem.output_format}
              </p>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-yellow-500/5 border border-yellow-500/20 mb-5">
            <h3 className="text-xs uppercase tracking-wider text-yellow-300 mb-1.5 flex items-center gap-1.5">
              <Lightbulb size={13} /> Constraints
            </h3>
            <p className="text-white/70 text-sm whitespace-pre-wrap">
              {problem.constraints}
            </p>
          </div>

          <h3 className="text-sm font-semibold mb-2 text-white/80">
            Sample test cases
          </h3>
          <div className="space-y-3">
            {problem.sample_cases.map((sc, i) => (
              <div
                key={i}
                className="grid md:grid-cols-2 gap-3 p-4 rounded-xl bg-black/20 border border-white/10"
              >
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-white/40 mb-1">
                    Sample input
                  </p>
                  <pre className="bg-black/40 rounded-lg p-3 text-emerald-300 text-xs font-mono overflow-x-auto whitespace-pre-wrap">
                    {sc.input}
                  </pre>
                </div>
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-white/40 mb-1">
                    Expected output
                  </p>
                  <pre className="bg-black/40 rounded-lg p-3 text-blue-300 text-xs font-mono overflow-x-auto whitespace-pre-wrap">
                    {sc.expected}
                  </pre>
                </div>
              </div>
            ))}
          </div>
        </motion.div>

        {/* Editor */}
        <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <Cpu size={18} className="text-violet-400" /> Your solution
            </h2>
            <div className="flex items-center gap-2">
              <label className="text-xs text-white/50">Language</label>
              <select
                value={activeLanguage}
                onChange={(e) => {
                  const lang = e.target.value as Language;
                  if (!LANGUAGES.includes(lang)) return;
                  setLanguageByProblem((prev) => ({
                    ...prev,
                    [problem.problem_index]: lang,
                  }));
                }}
                disabled={running || submitting}
                className="bg-white/10 border border-white/20 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-500/50"
              >
                {LANGUAGES.map((lang) => (
                  <option key={lang} value={lang} className="bg-slate-900">
                    {LANGUAGE_LABELS[lang]}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <textarea
            value={activeCode}
            onChange={(e) => setCode(problem.problem_index, e.target.value)}
            disabled={running || submitting}
            spellCheck={false}
            placeholder={`Write your ${LANGUAGE_LABELS[activeLanguage]} solution here. Read the input from stdin and write the answer to stdout.`}
            className="w-full h-72 rounded-xl bg-black/40 border border-white/10 p-4 font-mono text-sm text-emerald-200 focus:outline-none focus:ring-2 focus:ring-violet-500/50 disabled:opacity-60 resize-y"
          />

          <div className="flex flex-wrap items-center gap-3 mt-4">
            <Button
              onClick={() => void runSample()}
              disabled={running || submitting || finishing}
              className="bg-white/10 text-white hover:bg-white/20"
            >
              {running ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Play size={16} />
              )}
              Run Sample Cases
            </Button>
            <Button
              onClick={() => void submitSolution()}
              disabled={running || submitting || finishing}
              className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
            >
              {submitting ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Send size={15} />
              )}
              Submit Solution
            </Button>
            {problem.submission && (
              <span className="text-xs text-white/50 ml-auto">
                Last graded:{" "}
                <span className="text-white/80">
                  {problem.submission.passed_cases}/{problem.submission.total_cases}{" "}
                  hidden cases • score{" "}
                  <span className={scoreColor(problem.submission.score)}>
                    {problem.submission.score}%
                  </span>
                </span>
              </span>
            )}
          </div>

          {runResult && (
            <div className="mt-6">
              <div className="flex flex-wrap items-center gap-3 mb-3">
                <h3 className="text-sm font-semibold text-white/80">
                  Sample-case run results
                </h3>
                {runResult.compile_error ? (
                  <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full bg-red-500/15 text-red-300">
                    Compilation failed
                  </span>
                ) : (
                  <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full bg-emerald-500/15 text-emerald-300">
                    Compiled OK
                  </span>
                )}
              </div>

              {runResult.compile_error && runResult.compile_stderr ? (
                <pre className="bg-black/40 rounded-lg p-3 text-red-300 text-xs font-mono overflow-x-auto whitespace-pre-wrap mb-3">
                  {runResult.compile_stderr}
                </pre>
              ) : null}

              <div className="space-y-3">
                {runResults.map((r) => (
                  <div
                    key={r.case_index}
                    className={`p-4 rounded-xl border ${
                      r.passed
                        ? "bg-emerald-500/5 border-emerald-500/20"
                        : "bg-red-500/5 border-red-500/20"
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                      <span className="flex items-center gap-2 text-sm font-medium">
                        {r.passed ? (
                          <CheckCircle2 size={15} className="text-emerald-400" />
                        ) : (
                          <XCircle size={15} className="text-red-400" />
                        )}
                        Sample case {r.case_index + 1}
                      </span>
                      <span className="text-[11px] text-white/40 uppercase tracking-wider">
                        {r.status.replace(/_/g, " ")} • {r.time_ms} ms
                      </span>
                    </div>
                    {r.stdout ? (
                      <pre className="bg-black/40 rounded-lg p-3 text-emerald-200 text-xs font-mono overflow-x-auto whitespace-pre-wrap">
                        {r.stdout}
                      </pre>
                    ) : !r.passed ? (
                      <pre className="bg-black/40 rounded-lg p-3 text-red-300 text-xs font-mono overflow-x-auto whitespace-pre-wrap">
                        {r.stderr || "Wrong answer"}
                      </pre>
                    ) : null}
                  </div>
                ))}
              </div>

              {runResults.length === 0 && (
                <p className="text-white/50 text-sm">
                  No sample cases produced output.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Navigation between problems */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Button
            variant="outline"
            onClick={() => {
              setActiveIndex((idx) => Math.max(0, idx - 1));
              setRunResult(null);
              setActionError(null);
            }}
            disabled={activeIndex === 0 || running || submitting}
            className="border-white/15 text-white/70 hover:bg-white/5"
          >
            <ChevronLeft size={16} /> Previous Problem
          </Button>

          <div className="text-sm text-white/50">
            Problem {activeIndex + 1} of {detail.problems.length}
          </div>

          <Button
            onClick={() => {
              setActiveIndex((idx) =>
                Math.min(detail.problems.length - 1, idx + 1)
              );
              setRunResult(null);
              setActionError(null);
            }}
            disabled={activeIndex === detail.problems.length - 1 || running || submitting}
            className="bg-white/10 text-white hover:bg-white/15"
          >
            Next Problem <ChevronRight size={16} />
          </Button>
        </div>
      </div>
    );
  };

  const renderResults = () => {
    const score = detail?.score ?? null;

    return (
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          {backButton("Back")}
          <Button
            onClick={() => void backToHome()}
            className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
          >
            <RotateCcw size={16} /> Take Another Test
          </Button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-4xl font-bold flex items-center gap-3">
              <Trophy size={32} className="text-yellow-400" /> Coding Test Result
            </h1>
            <p className="text-white/50 mt-2">
              {detail?.job_title || "Role"} · {detail?.company_name || "Company"}
            </p>
          </div>
          {score != null && detail && (
            <div className="text-right">
              <span className="text-white/50 text-sm block">
                {detail.solved_count} of {detail.total_problems} problems solved
              </span>
              <span
                className={`text-5xl font-bold ${scoreColor(score)}`}
              >
                {score}%
              </span>
              <span
                className={`block mt-1 text-xs px-3 py-1 rounded-full inline-flex items-center gap-1.5 ${
                  detail.passed
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-red-500/15 text-red-300"
                }`}
              >
                {detail.passed ? (
                  <CheckCircle2 size={13} />
                ) : (
                  <XCircle size={13} />
                )}
                {detail.passed ? "Passed" : "Failed"} ·{" "}
                {detail.pass_percentage}% to pass
              </span>
            </div>
          )}
        </div>

        {!detail ? (
          <ErrorBanner message="The results are not available yet." />
        ) : (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-6"
          >
            <div className="p-4 rounded-xl bg-white/5 border border-white/10 text-white/60 text-sm">
              Your score is based on the hidden test cases each solution
              passed. Inputs and expected outputs of hidden cases are never
              shown.
            </div>

            <div className="space-y-3">
              {detail.problems.map((p, index) => (
                <div
                  key={p.id}
                  className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4"
                >
                  <div className="flex items-center gap-3">
                    {statusIcon(p.submission?.status ?? null)}
                    <div>
                      <p className="font-semibold">
                        {index + 1}. {p.title}
                      </p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <DifficultyBadge difficulty={p.difficulty} />
                        <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full bg-violet-500/20 text-violet-300">
                          {p.category.replace(/_/g, " ")}
                        </span>
                      </div>
                    </div>
                  </div>
                  {p.submission ? (
                    <div className="text-right">
                      <span className="text-xl font-bold">
                        {p.submission.score}%
                      </span>
                      <span className="block text-[11px] text-white/40 uppercase tracking-wider">
                        {p.submission.passed_cases}/{p.submission.total_cases}{" "}
                        hidden cases passed
                      </span>
                    </div>
                  ) : (
                    <span className="text-xs text-white/30">
                      Not attempted
                    </span>
                  )}
                </div>
              ))}
            </div>

            <div className="flex flex-wrap justify-end">
              <Button
                onClick={() => void backToHome()}
                className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
              >
                <RotateCcw size={16} /> Take Another Test
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
        Loading your coding tests...
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

function listOutFromDetail(detail: CodingTestDetailOut): CodingTestListOut {
  return {
    id: detail.id,
    application_id: detail.application_id,
    job_title: detail.job_title,
    company_name: detail.company_name,
    status: detail.status,
    total_problems: detail.total_problems,
    solved_count: detail.solved_count,
    score: detail.score,
    passed: detail.passed,
    pass_percentage: detail.pass_percentage,
    started_at: detail.started_at,
    completed_at: detail.completed_at,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  };
}