import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Braces,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Clock,
  Cpu,
  FileText,
  HelpCircle,
  Lightbulb,
  ListChecks,
  Loader2,
  Play,
  RotateCcw,
  Send,
  Terminal,
  Trophy,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "../../lib/api";

// ---------------------------------------------------------------------------
// Backend response shapes (mirror backend/app/schemas.py)
// ---------------------------------------------------------------------------

type AssignmentStatus = "assigned" | "in_progress" | "submitted";
type QuestionType = "mcq" | "coding";
type SectionType =
  | "aptitude"
  | "technical"
  | "coding"
  | "hr"
  | "technical_interview";

interface CandidateAssessmentAssignmentOut {
  id: number;
  assessment_id: number;
  title: string;
  description: string | null;
  instructions: string | null;
  company_name: string;
  duration_minutes: number | null;
  starts_at: string | null;
  ends_at: string | null;
  status: AssignmentStatus;
  assigned_at: string;
  started_at: string | null;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
}

interface CandidateAssessmentSectionOut {
  id: number;
  section_type: SectionType;
  title: string;
  section_order: number;
}

interface CandidateAssessmentAssignmentDetailOut
  extends CandidateAssessmentAssignmentOut {
  sections: CandidateAssessmentSectionOut[];
}

interface CandidateAssessmentQuestionOut {
  id: number;
  question_type: QuestionType;
  question_text: string;
  question_order: number;
  options: string[] | null;
  title: string | null;
  category: string | null;
  difficulty: string | null;
  input_format: string | null;
  output_format: string | null;
  constraints: string | null;
  sample_cases: Array<{ input: string; expected: string }> | null;
  time_limit_seconds: number | null;
  supported_languages: string[] | null;
}

interface CandidateAssessmentSectionDetailOut {
  id: number;
  section_type: SectionType;
  title: string;
  section_order: number;
  questions: CandidateAssessmentQuestionOut[];
}

interface CodingTestCaseResultOut {
  case_index: number;
  passed: boolean;
  status: string;
  stdout: string;
  stderr: string;
  time_ms: number;
}

interface AssessmentAnswerOut {
  question_id: number;
  question_type: QuestionType;
  selected_option: number | null;
  language: string | null;
  status: string | null;
  passed_cases: number | null;
  total_cases: number | null;
  score: number | null;
  execution_time_ms: number | null;
  error_message: string | null;
  results: CodingTestCaseResultOut[];
  created_at: string;
  updated_at: string;
}

interface CandidateAssessmentStartOut {
  attempt_id: number;
  assessment_id: number;
  title: string;
  description: string | null;
  instructions: string | null;
  company_name: string;
  status: AssignmentStatus;
  duration_minutes: number | null;
  started_at: string;
  deadline_at: string | null;
  starts_at: string | null;
  ends_at: string | null;
  sections: CandidateAssessmentSectionDetailOut[];
}

interface CandidateAssessmentAttemptOut extends CandidateAssessmentStartOut {
  answers: AssessmentAnswerOut[];
}

interface CandidateAssessmentSubmitOut {
  attempt_id: number;
  assessment_id: number;
  status: AssignmentStatus;
  submitted_at: string | null;
  answered_count: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CODING_LANGS = ["python", "java", "cpp"] as const;
type CodingLang = (typeof CODING_LANGS)[number];

const LANG_LABELS: Record<CodingLang, string> = {
  python: "Python",
  java: "Java",
  cpp: "C++",
};

const SECTION_LABELS: Record<SectionType, string> = {
  aptitude: "Aptitude",
  technical: "Technical",
  coding: "Coding",
  hr: "HR",
  technical_interview: "Technical Interview",
};

const OPTION_LETTERS = ["A", "B", "C", "D", "E", "F"];

function sectionLabel(sectionType: SectionType): string {
  return SECTION_LABELS[sectionType] ?? sectionType.replace(/_/g, " ");
}

function errMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

function isExpiredError(e: unknown): boolean {
  return (
    typeof e === "object" &&
    e !== null &&
    (e as { status?: number }).status === 409
  );
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatTime(totalSeconds: number): string {
  const safe = Math.max(0, totalSeconds);
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60)
    .toString()
    .padStart(2, "0");
  const s = Math.floor(safe % 60)
    .toString()
    .padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function defaultLang(q: CandidateAssessmentQuestionOut): string {
  const first = q.supported_languages?.[0] ?? "python";
  return CODING_LANGS.includes(first as CodingLang) ? first : "python";
}

function isWindowPending(a: CandidateAssessmentAssignmentOut): boolean {
  return (
    a.status === "assigned" &&
    a.starts_at != null &&
    Date.now() < new Date(a.starts_at).getTime()
  );
}

function isWindowOver(a: CandidateAssessmentAssignmentOut): boolean {
  return (
    a.status === "assigned" &&
    a.ends_at != null &&
    Date.now() > new Date(a.ends_at).getTime()
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type View = "loading" | "list" | "instructions" | "active" | "completed";

const mcqDraftKey = (assessmentId: number) =>
  `recruito.ca.${assessmentId}.mcq`;
const codeDraftKey = (assessmentId: number, questionId: number) =>
  `recruito.ca.${assessmentId}.code.${questionId}`;
const langDraftKey = (assessmentId: number, questionId: number) =>
  `recruito.ca.${assessmentId}.lang.${questionId}`;

export default function CompanyAssessments() {
  const [view, setView] = useState<View>("loading");

  const [assignments, setAssignments] = useState<
    CandidateAssessmentAssignmentOut[]
  >([]);
  const [selected, setSelected] =
    useState<CandidateAssessmentAssignmentOut | null>(null);
  const [detail, setDetail] =
    useState<CandidateAssessmentAssignmentDetailOut | null>(null);

  const [attempt, setAttempt] = useState<CandidateAssessmentAttemptOut | null>(
    null
  );

  const [initError, setInitError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [beginning, setBeginning] = useState(false);

  // Attempt-local answer state (keyed by question id).
  const [mcqSelections, setMcqSelections] = useState<Record<number, number>>(
    {}
  );
  const [savedSelections, setSavedSelections] = useState<
    Record<number, number>
  >({});
  const [codeByQ, setCodeByQ] = useState<Record<number, string>>({});
  const [langByQ, setLangByQ] = useState<Record<number, string>>({});
  const [savedCode, setSavedCode] = useState<Record<number, string>>({});
  const [savedLang, setSavedLang] = useState<Record<number, string>>({});
  const [verdictByQ, setVerdictByQ] = useState<
    Record<number, AssessmentAnswerOut>
  >({});

  const [activeQ, setActiveQ] = useState(0);

  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const [timerLeft, setTimerLeft] = useState<number | null>(null);

  // Flatten the attempt's questions (only sections that carry questions).
  const activeSections = useMemo(
    () =>
      (attempt?.sections ?? []).filter((s) => s.questions.length > 0),
    [attempt]
  );

  const flatQuestions = useMemo(() => {
    const out: Array<{
      section: CandidateAssessmentSectionDetailOut;
      question: CandidateAssessmentQuestionOut;
    }> = [];
    for (const section of activeSections) {
      for (const question of section.questions) {
        out.push({ section, question });
      }
    }
    return out;
  }, [activeSections]);

  const currentItem = flatQuestions[activeQ] ?? null;

  // The section of the active question drives the pills + the question map.
  const activeSectionIndex = useMemo(() => {
    if (!currentItem) return 0;
    const idx = activeSections.findIndex(
      (s) => s.id === currentItem.section.id
    );
    return idx === -1 ? 0 : idx;
  }, [currentItem, activeSections]);

  const answeredCount = useMemo(
    () =>
      flatQuestions.filter(({ question }) => {
        if (question.question_type === "mcq") {
          return mcqSelections[question.id] !== undefined;
        }
        return Boolean(
          (codeByQ[question.id] ?? "").trim() || verdictByQ[question.id]
        );
      }).length,
    [flatQuestions, mcqSelections, codeByQ, verdictByQ]
  );

  const totalQuestions = flatQuestions.length;
  const progress =
    totalQuestions > 0 ? (answeredCount / totalQuestions) * 100 : 0;

  // -------------------------------------------------------------------------
  // Data loading
  // -------------------------------------------------------------------------

  const loadList = useCallback(async (): Promise<void> => {
    try {
      const data = await api.get<CandidateAssessmentAssignmentOut[]>(
        "/me/assessments"
      );
      setAssignments(data);
    } catch {
      // Best-effort refresh; the screen still renders from last state.
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const init = async (): Promise<void> => {
      setInitError(null);
      try {
        const data = await api.get<CandidateAssessmentAssignmentOut[]>(
          "/me/assessments"
        );
        if (cancelled) return;
        setAssignments(data);
        setView("list");
      } catch (e) {
        if (!cancelled) {
          setInitError(
            errMessage(e, "Failed to load your company assessments")
          );
          setView("list");
        }
      }
    };

    void init();
    return () => {
      cancelled = true;
    };
  }, []);

  // -------------------------------------------------------------------------
  // Attempt restore / drafts
  // -------------------------------------------------------------------------

  const persistMcqDraft = (assessmentId: number, sel: Record<number, number>): void => {
    try {
      localStorage.setItem(mcqDraftKey(assessmentId), JSON.stringify(sel));
    } catch {
      // localStorage unavailable — the server copy is the source of truth.
    }
  };

  const clearDrafts = (attempt_: CandidateAssessmentAttemptOut): void => {
    try {
      localStorage.removeItem(mcqDraftKey(attempt_.assessment_id));
      for (const section of attempt_.sections) {
        for (const question of section.questions) {
          if (question.question_type === "coding") {
            localStorage.removeItem(codeDraftKey(attempt_.assessment_id, question.id));
            localStorage.removeItem(langDraftKey(attempt_.assessment_id, question.id));
          }
        }
      }
    } catch {
      // ignore
    }
  };

  const restoreAttempt = (data: CandidateAssessmentAttemptOut): void => {
    const sel: Record<number, number> = {};
    const savedSel: Record<number, number> = {};
    const verdicts: Record<number, AssessmentAnswerOut> = {};
    for (const answer of data.answers) {
      if (answer.selected_option !== null && answer.selected_option !== undefined) {
        sel[answer.question_id] = answer.selected_option;
        savedSel[answer.question_id] = answer.selected_option;
      }
      if (answer.language) {
        verdicts[answer.question_id] = answer;
      }
    }

    // Local drafts are a resilience net: the backend never returns the stored
    // code, so a re-entered coding editor restores its draft from localStorage.
    // Server answers are authoritative — drafts only fill unanswered questions.
    try {
      const raw = localStorage.getItem(mcqDraftKey(data.assessment_id));
      if (raw) {
        const parsed = JSON.parse(raw) as Record<string, number>;
        for (const key of Object.keys(parsed)) {
          const qid = Number(key);
          if (sel[qid] === undefined && Number.isInteger(qid)) {
            sel[qid] = parsed[key];
          }
        }
      }
    } catch {
      // Corrupt or unavailable draft — ignore.
    }

    const code: Record<number, string> = {};
    const lang: Record<number, string> = {};
    for (const section of data.sections) {
      for (const question of section.questions) {
        if (question.question_type !== "coding") continue;
        const draftCode = localStorage.getItem(
          codeDraftKey(data.assessment_id, question.id)
        );
        if (draftCode) code[question.id] = draftCode;
        const draftLang = localStorage.getItem(
          langDraftKey(data.assessment_id, question.id)
        );
        lang[question.id] =
          draftLang ||
          verdicts[question.id]?.language ||
          defaultLang(question);
      }
    }

    setMcqSelections(sel);
    setSavedSelections(savedSel);
    setCodeByQ(code);
    setLangByQ(lang);
    setSavedCode({ ...code });
    setSavedLang({ ...lang });
    setVerdictByQ(verdicts);
    setActiveQ(0);
    setTimerLeft(null);
    setActionError(null);
  };

  const resetAttemptState = (): void => {
    setAttempt(null);
    setMcqSelections({});
    setSavedSelections({});
    setCodeByQ({});
    setLangByQ({});
    setSavedCode({});
    setSavedLang({});
    setVerdictByQ({});
    setActiveQ(0);
    setTimerLeft(null);
  };

  // -------------------------------------------------------------------------
  // Navigation between screens
  // -------------------------------------------------------------------------

  const openInstructions = async (a: CandidateAssessmentAssignmentOut): Promise<void> => {
    setActionError(null);
    setSelected(a);
    setView("instructions");
    try {
      const d = await api.get<CandidateAssessmentAssignmentDetailOut>(
        `/me/assessments/${a.assessment_id}`
      );
      setDetail(d);
    } catch {
      // The list row already carries title/description/instructions; the
      // section pipeline is a nice-to-have, so a failed detail fetch is not
      // fatal.
      setDetail(null);
    }
  };

  const openCompletedAttempt = async (
    a: CandidateAssessmentAssignmentOut
  ): Promise<void> => {
    setBeginning(true);
    setActionError(null);
    setSelected(a);
    try {
      const data = await api.get<CandidateAssessmentAttemptOut>(
        `/me/assessments/${a.assessment_id}/attempt`
      );
      setAttempt(data);
      restoreAttempt(data);
      setView("completed");
    } catch (e) {
      setActionError(
        errMessage(e, "Failed to load your submitted assessment")
      );
    } finally {
      setBeginning(false);
    }
  };

  const beginAttempt = async (a: CandidateAssessmentAssignmentOut): Promise<void> => {
    setBeginning(true);
    setActionError(null);
    try {
      let data: CandidateAssessmentAttemptOut;
      if (a.status === "assigned") {
        try {
          const started = await api.post<CandidateAssessmentStartOut>(
            `/me/assessments/${a.assessment_id}/start`
          );
          data = { ...started, answers: [] };
        } catch (e) {
          // A concurrent start won the race: treat as already started.
          if (isExpiredError(e)) {
            data = await api.get<CandidateAssessmentAttemptOut>(
              `/me/assessments/${a.assessment_id}/attempt`
            );
          } else {
            throw e;
          }
        }
        if (data.status === "submitted") {
          // e.g. the window ended at the same instant we started.
          const finalAttempt = await api.get<CandidateAssessmentAttemptOut>(
            `/me/assessments/${data.assessment_id}/attempt`
          );
          setAttempt(finalAttempt);
          restoreAttempt(finalAttempt);
          await loadList();
          setView("completed");
          return;
        }
      } else {
        data = await api.get<CandidateAssessmentAttemptOut>(
          `/me/assessments/${a.assessment_id}/attempt`
        );
        if (data.status === "submitted") {
          setAttempt(data);
          restoreAttempt(data);
          await loadList();
          setView("completed");
          return;
        }
      }
      setAttempt(data);
      restoreAttempt(data);
      setView("active");
    } catch (e) {
      setActionError(errMessage(e, "Failed to open this assessment"));
    } finally {
      setBeginning(false);
    }
  };

  const backToList = async (): Promise<void> => {
    if (view === "active" && attempt) {
      try {
        await saveCurrentAnswer();
      } catch (e) {
        if (!isExpiredError(e)) {
          setActionError(errMessage(e, "Failed to save your answer before leaving"));
          return;
        }
      }
    }
    await loadList();
    resetAttemptState();
    setSelected(null);
    setDetail(null);
    setActionError(null);
    setView("list");
  };

  // -------------------------------------------------------------------------
  // Answer saving + submission
  // -------------------------------------------------------------------------

  const saveCurrentAnswer = async (): Promise<void> => {
    if (!attempt || !currentItem) return;
    const question = currentItem.question;

    if (question.question_type === "mcq") {
      const selected = mcqSelections[question.id];
      if (selected === undefined) return;
      if (savedSelections[question.id] === selected) return;
      setSaving(true);
      try {
        await api.post<AssessmentAnswerOut>(
          `/me/assessments/${attempt.assessment_id}/answers`,
          {
            question_id: question.id,
            selected_option: selected,
          }
        );
        setSavedSelections((prev) => ({ ...prev, [question.id]: selected }));
      } finally {
        setSaving(false);
      }
      return;
    }

    // Coding: grading runs server-side against the hidden cases.
    const code = codeByQ[question.id] ?? "";
    const lang = langByQ[question.id] ?? defaultLang(question);
    if (!code.trim()) return; // the backend rejects empty code
    if (savedCode[question.id] === code && savedLang[question.id] === lang) {
      return;
    }
    setSaving(true);
    try {
      const res = await api.post<AssessmentAnswerOut>(
        `/me/assessments/${attempt.assessment_id}/answers`,
        {
          question_id: question.id,
          language: lang,
          code,
        }
      );
      setSavedCode((prev) => ({ ...prev, [question.id]: code }));
      setSavedLang((prev) => ({ ...prev, [question.id]: lang }));
      setVerdictByQ((prev) => ({ ...prev, [question.id]: res }));
    } finally {
      setSaving(false);
    }
  };

  const goTo = async (index: number): Promise<void> => {
    if (!attempt || saving || submitting || flatQuestions.length === 0) return;
    try {
      await saveCurrentAnswer();
    } catch (e) {
      setActionError(errMessage(e, "Failed to save this answer."));
      return; // keep the user on the current question
    }
    setActiveQ(Math.min(Math.max(0, index), flatQuestions.length - 1));
    setActionError(null);
  };

  const submitTest = async (auto = false): Promise<void> => {
    if (!attempt || submittingRef.current) return;
    if (
      !auto &&
      !window.confirm(
        "Submit your assessment? You will not be able to change your answers after submitting."
      )
    ) {
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setActionError(null);
    try {
      try {
        await saveCurrentAnswer();
      } catch (e) {
        // The deadline may have passed mid-save; the submit call below is
        // authoritative and auto-submits on expiry anyway.
        if (!isExpiredError(e)) throw e;
      }
      const res = await api.post<CandidateAssessmentSubmitOut>(
        `/me/assessments/${attempt.assessment_id}/submit`
      );
      clearDrafts(attempt);
      setTimerLeft(0);
      try {
        const finalAttempt = await api.get<CandidateAssessmentAttemptOut>(
          `/me/assessments/${attempt.assessment_id}/attempt`
        );
        setAttempt(finalAttempt);
        restoreAttempt(finalAttempt);
      } catch {
        setAttempt((prev) =>
          prev
            ? { ...prev, status: res.status, submitted_at: res.submitted_at }
            : prev
        );
      }
      await loadList();
      setView("completed");
    } catch (e) {
      if (isExpiredError(e)) {
        // Already submitted from another tab/window: show completion.
        try {
          const finalAttempt = await api.get<CandidateAssessmentAttemptOut>(
            `/me/assessments/${attempt.assessment_id}/attempt`
          );
          setAttempt(finalAttempt);
          restoreAttempt(finalAttempt);
          await loadList();
          setView("completed");
          return;
        } catch {
          // fall through to the error banner
        }
      }
      setActionError(errMessage(e, "Failed to submit the assessment"));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  const submitRef = useRef<(auto?: boolean) => Promise<void>>(async () => {});
  submitRef.current = submitTest;

  // Local countdown from the backend-enforced deadline. The deadline comes
  // from the server on every attempt load, so a refresh recalculates it.
  useEffect(() => {
    if (view !== "active" || !attempt?.deadline_at) return;

    const tick = (): void => {
      const remaining = Math.floor(
        (new Date(attempt.deadline_at as string).getTime() - Date.now()) / 1000
      );
      setTimerLeft(remaining);
      if (remaining <= 0 && !submittingRef.current) {
        void submitRef.current(true);
      }
    };
    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, [view, attempt?.deadline_at]);

  // -------------------------------------------------------------------------
  // Question interactions
  // -------------------------------------------------------------------------

  const selectOption = (question: CandidateAssessmentQuestionOut, option: number): void => {
    if (!attempt || saving || submitting) return;
    const next = { ...mcqSelections, [question.id]: option };
    setMcqSelections(next);
    persistMcqDraft(attempt.assessment_id, next);
  };

  const setCodeValue = (question: CandidateAssessmentQuestionOut, value: string): void => {
    if (!attempt || submitting) return;
    setCodeByQ((prev) => {
      const next = { ...prev, [question.id]: value };
      try {
        localStorage.setItem(
          codeDraftKey(attempt.assessment_id, question.id),
          value
        );
      } catch {
        // ignore
      }
      return next;
    });
  };

  const setLanguage = (question: CandidateAssessmentQuestionOut, lang: string): void => {
    if (!attempt || submitting) return;
    setLangByQ((prev) => {
      const next = { ...prev, [question.id]: lang };
      try {
        localStorage.setItem(
          langDraftKey(attempt.assessment_id, question.id),
          lang
        );
      } catch {
        // ignore
      }
      return next;
    });
  };

  // -------------------------------------------------------------------------
  // Derived state
  // -------------------------------------------------------------------------

  const inProgressAssignments = useMemo(
    () => assignments.filter((a) => a.status === "in_progress"),
    [assignments]
  );

  const pendingAssignments = useMemo(
    () => assignments.filter((a) => a.status === "assigned"),
    [assignments]
  );

  const completedAssignments = useMemo(
    () => assignments.filter((a) => a.status === "submitted"),
    [assignments]
  );

  const flatIndexForSection = (sectionId: number): number => {
    const idx = flatQuestions.findIndex(
      (item) => item.section.id === sectionId
    );
    return idx === -1 ? activeQ : idx;
  };

  const currentSectionQuestions =
    activeSections[activeSectionIndex]?.questions ?? [];

  const isAnsweredQuestion = (question: CandidateAssessmentQuestionOut): boolean => {
    if (question.question_type === "mcq") {
      return mcqSelections[question.id] !== undefined;
    }
    return Boolean((codeByQ[question.id] ?? "").trim() || verdictByQ[question.id]);
  };

  // -------------------------------------------------------------------------
  // Render helpers
  // -------------------------------------------------------------------------

  const ErrorBanner = ({ message }: { message: string }) => (
    <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
      {message}
    </div>
  );

  const WarnBanner = ({ message }: { message: string }) => (
    <div className="p-4 rounded-xl bg-yellow-500/10 border border-yellow-500/20 text-yellow-300 text-sm">
      {message}
    </div>
  );

  const backButton = (label: string) => (
    <button
      onClick={() => void backToList()}
      className="flex items-center gap-2 text-white/50 hover:text-white text-sm transition"
    >
      <ArrowLeft size={16} /> {label}
    </button>
  );

  const StatusBadge = ({ a }: { a: CandidateAssessmentAssignmentOut }) => {
    if (a.status === "submitted") {
      return (
        <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full border bg-emerald-500/15 border-emerald-500/30 text-emerald-300">
          Completed
        </span>
      );
    }
    if (a.status === "in_progress") {
      return (
        <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full border bg-violet-500/15 border-violet-500/30 text-violet-300">
          In progress
        </span>
      );
    }
    if (isWindowPending(a)) {
      return (
        <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full border bg-yellow-500/15 border-yellow-500/30 text-yellow-300">
          Not started
        </span>
      );
    }
    if (isWindowOver(a)) {
      return (
        <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full border bg-red-500/15 border-red-500/30 text-red-300">
          Window closed
        </span>
      );
    }
    return (
      <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full border bg-blue-500/15 border-blue-500/30 text-blue-300">
        Open
      </span>
    );
  };

  const SectionTypeChip = ({ sectionType }: { sectionType: SectionType }) => (
    <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full bg-violet-500/20 text-violet-300">
      {sectionLabel(sectionType)}
    </span>
  );

  // -------------------------------------------------------------------------
  // Screens
  // -------------------------------------------------------------------------

  const renderList = () => (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold flex items-center gap-3">
            <ClipboardList size={32} className="text-violet-400" />
            Company Assessments
          </h1>
          <p className="text-white/50 mt-2">
            Assessments scheduled by companies for your applications. Start
            them before their deadline — your progress is saved as you go.
          </p>
        </div>
      </div>

      {initError && <ErrorBanner message={initError} />}
      {actionError && <ErrorBanner message={actionError} />}

      {/* IN PROGRESS */}
      {inProgressAssignments.length > 0 && (
        <div className="p-6 rounded-3xl bg-gradient-to-r from-violet-900/30 to-blue-800/20 border border-white/10 shadow-2xl">
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Clock size={18} className="text-violet-300" /> In progress
          </h2>
          <div className="space-y-3">
            {inProgressAssignments.map((a) => (
              <motion.div
                key={a.assessment_id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4 hover:bg-white/10 transition"
              >
                <div>
                  <p className="font-semibold">{a.title}</p>
                  <p className="text-white/50 text-sm">{a.company_name}</p>
                  <p className="text-white/40 text-xs mt-1">
                    {a.duration_minutes
                      ? `${a.duration_minutes} min • `
                      : ""}
                    started {formatDate(a.started_at)}
                    {a.ends_at
                      ? ` • deadline ${formatDateTime(a.ends_at)}`
                      : ""}
                  </p>
                </div>
                <Button
                  onClick={() => void openInstructions(a)}
                  className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
                >
                  <Play size={16} /> Resume
                </Button>
              </motion.div>
            ))}
          </div>
        </div>
      )}

      {/* AVAILABLE */}
      <div>
        <h2 className="text-2xl font-semibold mb-4">Available for you</h2>
        {pendingAssignments.length === 0 ? (
          <p className="text-white/50">
            No new assessments have been assigned to you yet. When a company
            schedules one, it will appear here.
          </p>
        ) : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-5">
            {pendingAssignments.map((a, index) => {
              const pending = isWindowPending(a);
              const over = isWindowOver(a);
              return (
                <motion.div
                  key={a.assessment_id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className="p-6 rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 transition flex flex-col gap-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-lg font-semibold">{a.title}</h3>
                      <p className="text-white/60 text-sm">{a.company_name}</p>
                    </div>
                    <StatusBadge a={a} />
                  </div>
                  <p className="text-white/40 text-xs">
                    {a.duration_minutes ? `${a.duration_minutes} min` : "Untimed"}
                    {a.starts_at ? ` • opens ${formatDateTime(a.starts_at)}` : ""}
                    {!a.starts_at && a.ends_at
                      ? ` • closes ${formatDateTime(a.ends_at)}`
                      : ""}
                  </p>
                  <Button
                    size="sm"
                    disabled={pending || over}
                    onClick={() => void openInstructions(a)}
                    className="bg-gradient-to-r from-violet-600 to-blue-600 text-white mt-auto disabled:from-white/10 disabled:to-white/10 disabled:text-white/40"
                  >
                    {pending
                      ? "Opens later"
                      : over
                      ? "Window closed"
                      : "Start Assessment"}
                  </Button>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      {/* COMPLETED */}
      <div>
        <h2 className="text-2xl font-semibold mb-4">Completed</h2>
        {completedAssignments.length === 0 ? (
          <p className="text-white/50">
            No completed assessments yet. Your submitted assessments will
            appear here.
          </p>
        ) : (
          <div className="space-y-3">
            {completedAssignments.map((a) => (
              <motion.div
                key={a.assessment_id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <p className="font-semibold">
                    {a.title}
                    <span className="ml-2 text-white/40 text-sm font-normal">
                      {a.company_name}
                    </span>
                  </p>
                  <p className="text-white/40 text-xs mt-1">
                    Submitted {formatDate(a.submitted_at)}
                  </p>
                </div>
                <Button
                  size="sm"
                  onClick={() => void openCompletedAttempt(a)}
                  disabled={beginning}
                  className="bg-white/10 text-white hover:bg-white/20"
                >
                  {beginning ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <FileText size={14} />
                  )}
                  View
                </Button>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  const renderInstructions = () => {
    if (!selected) {
      return (
        <div className="space-y-8">
          <h1 className="text-4xl font-bold">Company Assessments</h1>
          <ErrorBanner message="Could not load this assessment's details." />
        </div>
      );
    }

    const pending = isWindowPending(selected);
    const over = isWindowOver(selected);
    const sections = detail?.sections ?? [];

    return (
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          {backButton("Back")}
          <StatusBadge a={selected} />
        </div>

        {actionError && <ErrorBanner message={actionError} />}
        {pending && (
          <WarnBanner
            message={`This assessment opens on ${formatDateTime(
              selected.starts_at
            )}. You cannot start it before then.`}
          />
        )}
        {over && (
          <WarnBanner message="The window for this assessment has closed." />
        )}

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-8 rounded-3xl bg-gradient-to-br from-violet-900/30 to-blue-800/20 border border-white/10 shadow-2xl"
        >
          <p className="text-sm text-white/50">{selected.company_name}</p>
          <h1 className="text-3xl md:text-4xl font-bold mt-1">
            {selected.title}
          </h1>
          <p className="text-white/60 text-sm mt-2">
            {selected.duration_minutes
              ? `${selected.duration_minutes} minute limit`
              : "No time limit"}
            {selected.starts_at || selected.ends_at
              ? ` • ${formatDateTime(selected.starts_at)} – ${formatDateTime(
                  selected.ends_at
                )}`
              : ""}
          </p>
        </motion.div>

        {selected.description && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-6 rounded-2xl bg-white/5 border border-white/10"
          >
            <h2 className="text-lg font-semibold mb-2">About this assessment</h2>
            <p className="text-white/70 leading-relaxed">
              {selected.description}
            </p>
          </motion.div>
        )}

        {sections.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-6 rounded-2xl bg-white/5 border border-white/10"
          >
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <ListChecks size={18} className="text-violet-400" /> Sections
            </h2>
            <div className="space-y-3">
              {sections.map((section) => (
                <div
                  key={section.id}
                  className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-xl bg-black/20 border border-white/10"
                >
                  <p className="font-medium">{section.title}</p>
                  <SectionTypeChip sectionType={section.section_type} />
                </div>
              ))}
            </div>
          </motion.div>
        )}

        {selected.instructions && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-6 rounded-2xl bg-white/5 border border-white/10"
          >
            <h2 className="text-lg font-semibold mb-2 flex items-center gap-2">
              <HelpCircle size={18} className="text-violet-400" /> Instructions
            </h2>
            <p className="text-white/70 leading-relaxed whitespace-pre-wrap">
              {selected.instructions}
            </p>
          </motion.div>
        )}

        <div className="p-4 rounded-xl bg-white/5 border border-white/10 text-white/50 text-sm">
          Multiple-choice answers are saved as you go. Coding answers are
          graded against the test cases when you save them, so you know how
          many you pass before submitting. Correct answers and hidden test
          cases are never shown.
        </div>

        <div className="flex flex-wrap justify-end gap-3">
          {selected.status === "submitted" ? (
            <Button
              onClick={() => void openCompletedAttempt(selected)}
              disabled={beginning}
              className="bg-white/10 text-white hover:bg-white/20"
            >
              {beginning ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <FileText size={16} />
              )}
              View Submission
            </Button>
          ) : selected.status === "in_progress" ? (
            <Button
              onClick={() => void beginAttempt(selected)}
              disabled={beginning}
              className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
            >
              {beginning ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Play size={16} />
              )}
              Continue
            </Button>
          ) : (
            <Button
              onClick={() => void beginAttempt(selected)}
              disabled={beginning || pending || over}
              className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
            >
              {beginning ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Play size={16} />
              )}
              {pending || over ? "Not Available" : "Start Assessment"}
            </Button>
          )}
        </div>
      </div>
    );
  };

  const renderQuestionMap = () => {
    const sectionQuestions = currentSectionQuestions;
    let start = 0;
    for (let i = 0; i < activeSectionIndex; i++) {
      start += activeSections[i].questions.length;
    }

    return (
      <div className="flex flex-wrap gap-2">
        {sectionQuestions.map((q, index) => {
          const absIndex = start + index;
          const isCurrent = absIndex === activeQ;
          const answered = isAnsweredQuestion(q);
          return (
            <button
              key={q.id}
              type="button"
              onClick={() => void goTo(absIndex)}
              disabled={saving || submitting}
              title={
                answered
                  ? `Question ${index + 1} — answered`
                  : `Question ${index + 1} — unanswered`
              }
              className={`w-9 h-9 rounded-lg border text-xs font-semibold transition flex items-center justify-center ${
                isCurrent
                  ? "bg-violet-500 text-white border-violet-400 ring-2 ring-violet-500/40"
                  : answered
                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/25"
                  : "bg-white/5 text-white/50 border-white/10 hover:bg-white/10"
              }`}
            >
              {answered ? <Check size={14} /> : index + 1}
            </button>
          );
        })}
      </div>
    );
  };

  const renderCodingQuestion = (question: CandidateAssessmentQuestionOut) => {
    const code = codeByQ[question.id] ?? "";
    const lang = langByQ[question.id] ?? defaultLang(question);
    const langs =
      (question.supported_languages?.filter(
        (l) => CODING_LANGS.includes(l as CodingLang)
      ) as string[]) ?? [...CODING_LANGS];
    const verdict = verdictByQ[question.id];

    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-3 mb-4">
            <Braces size={22} className="text-violet-400" />
            {question.title || "Coding question"}
          </h2>
          <p className="text-white/80 leading-relaxed whitespace-pre-wrap">
            {question.question_text}
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-4">
          {question.input_format && (
            <div className="p-4 rounded-xl bg-black/20 border border-white/10">
              <h3 className="text-xs uppercase tracking-wider text-violet-300 mb-1.5 flex items-center gap-1.5">
                <Terminal size={13} /> Input format
              </h3>
              <p className="text-white/70 text-sm whitespace-pre-wrap">
                {question.input_format}
              </p>
            </div>
          )}
          {question.output_format && (
            <div className="p-4 rounded-xl bg-black/20 border border-white/10">
              <h3 className="text-xs uppercase tracking-wider text-violet-300 mb-1.5 flex items-center gap-1.5">
                <ListChecks size={13} /> Output format
              </h3>
              <p className="text-white/70 text-sm whitespace-pre-wrap">
                {question.output_format}
              </p>
            </div>
          )}
        </div>

        {question.constraints && (
          <div className="p-4 rounded-xl bg-yellow-500/5 border border-yellow-500/20">
            <h3 className="text-xs uppercase tracking-wider text-yellow-300 mb-1.5 flex items-center gap-1.5">
              <Lightbulb size={13} /> Constraints
            </h3>
            <p className="text-white/70 text-sm whitespace-pre-wrap">
              {question.constraints}
            </p>
          </div>
        )}

        {question.sample_cases && question.sample_cases.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-white/80">
              Sample test cases
            </h3>
            {question.sample_cases.map((sc, i) => (
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
        )}

        <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <h3 className="text-base font-semibold flex items-center gap-2">
              <Cpu size={17} className="text-violet-400" /> Your solution
            </h3>
            <label className="text-xs text-white/50">Language</label>
            <select
              value={lang}
              onChange={(e) => setLanguage(question, e.target.value)}
              disabled={saving || submitting}
              className="bg-white/10 border border-white/20 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-500/50"
            >
              {langs.map((l) => (
                <option key={l} value={l} className="bg-slate-900">
                  {LANG_LABELS[l as CodingLang]}
                </option>
              ))}
            </select>
          </div>

          <textarea
            value={code}
            onChange={(e) => setCodeValue(question, e.target.value)}
            disabled={saving || submitting}
            spellCheck={false}
            placeholder={`Write your ${LANG_LABELS[lang as CodingLang]} solution here. Read the input from stdin and write the answer to stdout.`}
            className="w-full h-64 rounded-xl bg-black/40 border border-white/10 p-4 font-mono text-sm text-emerald-200 focus:outline-none focus:ring-2 focus:ring-violet-500/50 disabled:opacity-60 resize-y"
          />

          <div className="flex flex-wrap items-center gap-3 mt-4">
            <Button
              onClick={() => {
                void saveCurrentAnswer().catch((e) =>
                  setActionError(
                    errMessage(e, "Failed to save and grade your code")
                  )
                );
              }}
              disabled={saving || submitting}
              className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
            >
              {saving ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Play size={16} />
              )}
              Save &amp; Grade
            </Button>
            <span className="text-xs text-white/40">
              Saving runs your code against the test cases — you can re-submit
              a better answer before the timer ends.
            </span>
          </div>

          {verdict && (
            <div className="mt-5">
              <div className="flex flex-wrap items-center gap-3 mb-3">
                <h4 className="text-sm font-semibold text-white/80">
                  Grading results
                </h4>
                <span
                  className={`text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full border ${
                    verdict.status === "passed"
                      ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-300"
                      : verdict.status === "failed"
                      ? "bg-yellow-500/15 border-yellow-500/30 text-yellow-300"
                      : "bg-red-500/15 border-red-500/30 text-red-300"
                  }`}
                >
                  {verdict.status === "passed"
                    ? "All cases passed"
                    : verdict.status === "failed"
                    ? `${verdict.passed_cases ?? 0}/${verdict.total_cases ?? 0} passed`
                    : "Error"}
                </span>
                {verdict.score != null && (
                  <span className="text-xs text-white/50">
                    Score{" "}
                    <span className="text-white font-semibold">
                      {verdict.score}%
                    </span>
                  </span>
                )}
              </div>

              {verdict.status === "error" && verdict.error_message && (
                <pre className="bg-black/40 rounded-lg p-3 text-red-300 text-xs font-mono overflow-x-auto whitespace-pre-wrap mb-3">
                  {verdict.error_message}
                </pre>
              )}

              <div className="space-y-2">
                {verdict.results.map((r) => (
                  <div
                    key={r.case_index}
                    className={`p-3 rounded-xl border flex items-center justify-between gap-2 ${
                      r.passed
                        ? "bg-emerald-500/5 border-emerald-500/20"
                        : "bg-red-500/5 border-red-500/20"
                    }`}
                  >
                    <span className="flex items-center gap-2 text-sm">
                      {r.passed ? (
                        <CheckCircle2 size={15} className="text-emerald-400" />
                      ) : (
                        <XCircle size={15} className="text-red-400" />
                      )}
                      Test case {r.case_index + 1}
                    </span>
                    <span className="text-[11px] text-white/40 uppercase tracking-wider">
                      {r.status.replace(/_/g, " ")} • {r.time_ms} ms
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderActive = () => {
    if (!attempt) {
      return (
        <div className="space-y-8">
          <h1 className="text-4xl font-bold">{selected?.title || "Assessment"}</h1>
          <ErrorBanner message="Could not load the current assessment." />
        </div>
      );
    }

    if (totalQuestions === 0) {
      return (
        <div className="space-y-8">
          <div className="flex flex-wrap items-center justify-between gap-4">
            {backButton("Back")}
            <span className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full border bg-white/10 border-white/10 text-white/70">
              <Clock size={13} className="text-yellow-400" />
              {timerLeft != null ? formatTime(timerLeft) : "—"}
            </span>
          </div>
          <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
            <h2 className="text-xl font-semibold mb-2">{attempt.title}</h2>
            <p className="text-white/50">
              This assessment currently has no questions. Submit to mark it
              complete.
            </p>
          </div>
          <div className="flex flex-wrap justify-end">
            <Button
              onClick={() => void submitTest(false)}
              disabled={submitting}
              className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
            >
              {submitting ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Send size={15} />
              )}
              Submit Assessment
            </Button>
          </div>
        </div>
      );
    }

    const question = currentItem?.question ?? null;
    const timerDanger =
      timerLeft != null && timerLeft <= 60 && !submitting && !saving;

    return (
      <div className="space-y-6">
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
            <h1 className="text-3xl font-bold">{attempt.title}</h1>
            <p className="text-white/50 mt-1">
              {attempt.company_name}
              {attempt.duration_minutes
                ? ` • ${attempt.duration_minutes} minute limit`
                : ""}
              {attempt.deadline_at
                ? ` • ends ${formatDateTime(attempt.deadline_at)}`
                : ""}
            </p>
          </div>
          <span className="text-sm text-white/60">
            <span className="text-white font-semibold">{answeredCount}</span> of{" "}
            {totalQuestions} answered
          </span>
        </div>

        {/* Progress bar */}
        <div>
          <div className="flex items-center justify-between text-xs text-white/50 mb-1.5">
            <span>Your progress</span>
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
          <WarnBanner message="Less than a minute left — your answers will be auto-submitted when the timer runs out." />
        )}

        {/* Section pills */}
        <div className="flex flex-wrap gap-2">
          {activeSections.map((section, index) => {
            const sectionAnswered = section.questions.filter((q) =>
              isAnsweredQuestion(q)
            ).length;
            const isActive = index === activeSectionIndex;
            return (
              <button
                key={section.id}
                type="button"
                onClick={() => {
                  void goTo(flatIndexForSection(section.id));
                }}
                disabled={saving || submitting}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl border text-sm transition ${
                  isActive
                    ? "bg-violet-500/15 border-violet-500/40 text-white"
                    : "bg-white/5 border-white/10 text-white/60 hover:bg-white/10"
                }`}
              >
                <span className="text-[11px] uppercase tracking-wider text-violet-300">
                  {sectionLabel(section.section_type)}
                </span>
                {section.title}
                <span className="text-[11px] text-white/40">
                  {sectionAnswered}/{section.questions.length}
                </span>
              </button>
            );
          })}
        </div>

        {/* Question map for the current section */}
        <div className="p-4 rounded-xl bg-white/5 border border-white/10 space-y-2">
          <p className="text-[11px] uppercase tracking-wider text-white/40">
            Jump to question
          </p>
          {renderQuestionMap()}
        </div>

        {question && (
          <motion.div
            key={`${currentItem?.section.id}-${question.id}`}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-6 rounded-2xl bg-white/5 border border-white/10"
          >
            {question.question_type === "coding" ? (
              renderCodingQuestion(question)
            ) : (
              <div>
                <h2 className="text-xl leading-relaxed font-medium flex gap-3 mb-6">
                  <HelpCircle size={22} className="text-violet-400 shrink-0 mt-1" />
                  <span>{question.question_text}</span>
                </h2>

                <div className="space-y-3">
                  {(question.options ?? []).map((option, optionIndex) => {
                    const isSelected = mcqSelections[question.id] === optionIndex;
                    return (
                      <button
                        key={optionIndex}
                        type="button"
                        onClick={() => selectOption(question, optionIndex)}
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
                  {mcqSelections[question.id] !== undefined
                    ? `Selected ${OPTION_LETTERS[mcqSelections[question.id]]} — you can change your answer before submitting`
                    : "Correct answers are never shown during the test."}
                </p>
              </div>
            )}
          </motion.div>
        )}

        {/* Navigation */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Button
            variant="outline"
            onClick={() => void goTo(activeQ - 1)}
            disabled={activeQ === 0 || saving || submitting}
            className="border-white/15 text-white/70 hover:bg-white/5"
          >
            <ChevronLeft size={16} />
            Previous
          </Button>

          <div className="text-sm text-white/50">
            Question {activeQ + 1} of {totalQuestions}
          </div>

          <div className="flex items-center gap-2">
            {activeQ < totalQuestions - 1 ? (
              <Button
                onClick={() => void goTo(activeQ + 1)}
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
                  <Send size={15} /> Submit Assessment
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    );
  };

  const renderCompleted = () => {
    const title = selected?.title ?? attempt?.title ?? "Assessment";
    const company = selected?.company_name ?? attempt?.company_name ?? "";
    const submittedAt = selected?.submitted_at ?? null;

    return (
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          {backButton("Back")}
          <Button
            onClick={() => void backToList()}
            className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
          >
            <RotateCcw size={16} /> Back to Assessments
          </Button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-4xl font-bold flex items-center gap-3">
              <Trophy size={32} className="text-yellow-400" /> Assessment
              Submitted
            </h1>
            <p className="text-white/50 mt-2">
              {title} · {company}
            </p>
          </div>
          <div className="text-right">
            <span className="text-white/50 text-sm block">
              Submitted {formatDate(submittedAt)}
            </span>
            <span className="text-3xl font-bold text-white/80">
              {attempt ? attempt.answers.length : 0}
            </span>
            <span className="block text-[11px] text-white/40 uppercase tracking-wider">
              of {totalQuestions} answered
            </span>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-sm">
          Your assessment has been submitted. The company will review your
          answers — you can see what you submitted below.
        </div>

        {actionError && <ErrorBanner message={actionError} />}

        {!attempt ? (
          <ErrorBanner message="The submitted assessment could not be loaded." />
        ) : (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-6"
          >
            {activeSections.length === 0 ? (
              <p className="text-white/50">
                No questions were found in this assessment.
              </p>
            ) : (
              activeSections.map((section) => {
                const answersByQ = new Map(
                  attempt.answers.map((ans) => [ans.question_id, ans])
                );
                return (
                  <div
                    key={section.id}
                    className="p-6 rounded-2xl bg-white/5 border border-white/10"
                  >
                    <div className="flex flex-wrap items-center gap-2 mb-4">
                      <SectionTypeChip sectionType={section.section_type} />
                      <h2 className="text-lg font-semibold">{section.title}</h2>
                    </div>
                    <div className="space-y-3">
                      {section.questions.map((q, index) => {
                        const answer = answersByQ.get(q.id);
                        const answered =
                          answer &&
                          (answer.selected_option !== null ||
                            answer.language != null);
                        return (
                          <div
                            key={q.id}
                            className="p-4 rounded-xl bg-black/20 border border-white/10"
                          >
                            <div className="flex items-start gap-3">
                              {answered ? (
                                <CheckCircle2
                                  size={17}
                                  className="text-emerald-400 mt-0.5 shrink-0"
                                />
                              ) : (
                                <span className="w-[17px] h-[17px] rounded-full border-2 border-white/20 mt-1 shrink-0" />
                              )}
                              <div className="min-w-0">
                                <p className="text-sm text-white/70">
                                  {index + 1}. {q.question_text}
                                </p>
                                {answer && q.question_type === "mcq" && (
                                  <p className="text-sm text-white/50 mt-2">
                                    Your answer:{" "}
                                    <span className="text-white">
                                      {OPTION_LETTERS[answer.selected_option ?? -1] ??
                                        "—"}
                                    </span>
                                    {answer.selected_option != null &&
                                    q.options?.[answer.selected_option]
                                      ? ` — ${q.options[answer.selected_option]}`
                                      : ""}
                                  </p>
                                )}
                                {answer && q.question_type === "coding" && (
                                  <div className="flex flex-wrap items-center gap-2 mt-2">
                                    <span className="text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full border bg-white/10 border-white/10 text-white/60">
                                      {answer.status === "passed"
                                        ? "Passed"
                                        : answer.status === "failed"
                                        ? "Attempted"
                                        : "Error"}{" "}
                                      · {answer.passed_cases ?? 0}/
                                      {answer.total_cases ?? 0} cases
                                    </span>
                                    <span className="text-xs text-white/40">
                                      {answer.language}
                                      {answer.execution_time_ms != null
                                        ? ` • ${answer.execution_time_ms} ms`
                                        : ""}
                                    </span>
                                  </div>
                                )}
                                {!answered && (
                                  <p className="text-xs text-white/35 mt-2">
                                    Not answered
                                  </p>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })
            )}
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
        Loading your company assessments...
      </div>
    );
  }

  switch (view) {
    case "instructions":
      return renderInstructions();
    case "active":
      return renderActive();
    case "completed":
      return renderCompleted();
    case "list":
    default:
      return renderList();
  }
}