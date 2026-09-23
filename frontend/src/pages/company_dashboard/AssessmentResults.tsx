import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, Search, X } from "lucide-react";
import {
  AssessmentQuestionResult,
  AssessmentResult,
  AssessmentResultDetail,
  SECTION_TYPE_LABELS,
  formatDateTime,
  getAssessmentResult,
  listAssessmentResults,
} from "../../lib/assessments";
import {
  ASSIGNMENT_STATUS_LABELS,
  AssessmentAssignmentStatus,
  assignmentStatusBadgeClass,
} from "../../lib/assignments";

interface AssessmentResultsProps {
  assessmentId: number;
  refreshSignal?: number;
}

const STATUS_FILTERS: Array<{
  value: "all" | AssessmentAssignmentStatus;
  label: string;
}> = [
  { value: "all", label: "All statuses" },
  { value: "assigned", label: "Assigned" },
  { value: "in_progress", label: "In Progress" },
  { value: "submitted", label: "Submitted" },
];

const inputClass = `
  w-full p-3 rounded-xl border
  bg-white text-gray-900
  dark:bg-gray-800 dark:text-white
  border-gray-300 dark:border-gray-700
  outline-none focus:ring-2 focus:ring-indigo-500
`;

function resultErrorMessage(e: unknown, fallback: string): string {
  const status = (e as { status?: number }).status;
  if (status === 403) {
    return "You do not have permission to view these results.";
  }
  if (status === 404) {
    return "No results were found for this assessment.";
  }
  return e instanceof Error ? e.message : fallback;
}

function percentageBadgeClass(percentage: number, maximum: number): string {
  if (maximum <= 0) {
    return "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400";
  }
  if (percentage >= 80) {
    return "bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400";
  }
  if (percentage >= 50) {
    return "bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400";
  }
  return "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400";
}

function progressBarClass(percentage: number): string {
  if (percentage >= 80) return "bg-green-500";
  if (percentage >= 50) return "bg-yellow-500";
  return "bg-red-500";
}

function ProgressBar({ percentage }: { percentage: number }): JSX.Element {
  const clamped = Math.max(0, Math.min(100, percentage));
  return (
    <div className="h-2 w-full rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
      <div
        className={`h-full rounded-full transition-all ${progressBarClass(
          percentage
        )}`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

function questionVerdict(q: AssessmentQuestionResult): {
  label: string;
  className: string;
} {
  if (!q.answered) {
    return {
      label: "Not Answered",
      className:
        "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
    };
  }
  if (q.question_type === "coding") {
    if (q.status === "passed") {
      return {
        label: "Passed",
        className:
          "bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400",
      };
    }
    if (q.status === "failed") {
      return {
        label: "Failed",
        className:
          "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400",
      };
    }
    if (q.status === "error") {
      return {
        label: "Error",
        className:
          "bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400",
      };
    }
    return {
      label: "Answered",
      className:
        "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-400",
    };
  }
  if (q.correct) {
    return {
      label: "Correct",
      className:
        "bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400",
    };
  }
  return {
    label: "Incorrect",
    className:
      "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400",
  };
}

function Info({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div>
      <p className="text-gray-500 dark:text-gray-400">{label}</p>
      <p className="text-gray-900 dark:text-white font-medium mt-1">
        {value}
      </p>
    </div>
  );
}

export default function AssessmentResults({
  assessmentId,
  refreshSignal = 0,
}: AssessmentResultsProps): JSX.Element {
  const [results, setResults] = useState<AssessmentResult[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<
    "all" | AssessmentAssignmentStatus
  >("all");
  const [selected, setSelected] = useState<{
    assignmentId: number;
    candidateName: string;
  } | null>(null);

  const load = useCallback(
    async (mode: "initial" | "refresh"): Promise<void> => {
      if (mode === "initial") {
        setLoading(true);
      } else {
        setRefreshing(true);
      }
      try {
        const data = await listAssessmentResults(assessmentId);
        setResults(data);
        setError(null);
      } catch (e) {
        setError(resultErrorMessage(e, "Failed to load results"));
      } finally {
        if (mode === "initial") {
          setLoading(false);
        } else {
          setRefreshing(false);
        }
      }
    },
    [assessmentId]
  );

  const firstRun = useRef(true);

  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      void load("initial");
    } else {
      void load("refresh");
    }
  }, [refreshSignal, load]);

  const filteredResults = useMemo(() => {
    const query = search.trim().toLowerCase();
    return results.filter((result) => {
      if (statusFilter !== "all" && result.status !== statusFilter) {
        return false;
      }
      if (!query) return true;
      const haystack = [
        result.candidate_name || "",
        result.candidate_email || "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [results, search, statusFilter]);

  return (
    <div
      className="
        bg-white dark:bg-gray-900
        border border-gray-200 dark:border-gray-800
        rounded-2xl overflow-hidden shadow-sm
      "
    >
      <div className="flex items-center justify-between p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          Results
        </h3>

        <button
          onClick={() => void load("refresh")}
          disabled={refreshing}
          className="
            flex items-center gap-2
            bg-indigo-600 hover:bg-indigo-700
            text-white px-4 py-2 rounded-lg
            text-sm font-medium transition
            disabled:opacity-60
          "
        >
          <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      <p className="px-6 pb-6 -mt-3 text-sm text-gray-500 dark:text-gray-400">
        Results are read from the assessment's recorded answers and never
        recomputed on the client. Click a candidate to view their detail.
      </p>

      {error && (
        <div
          className="
            flex items-center justify-between gap-3
            mx-6 mb-5 p-4 rounded-xl text-sm
            bg-red-500/10 border border-red-500/20
            text-red-600 dark:text-red-400
          "
        >
          <span>{error}</span>
          <button onClick={() => setError(null)} aria-label="Dismiss error">
            <X size={16} />
          </button>
        </div>
      )}

      {loading ? (
        <p className="px-6 pb-6 text-gray-500 dark:text-gray-400 text-sm">
          Loading results...
        </p>
      ) : results.length === 0 ? (
        <p className="px-6 pb-6 text-gray-500 dark:text-gray-400 text-sm">
          No results yet. Results appear once candidates are assigned to this
          assessment.
        </p>
      ) : (
        <>
          <div className="px-6 pb-4 flex flex-col md:flex-row gap-3">
            <div className="relative flex-1">
              <Search
                size={16}
                className="
                  absolute left-3 top-1/2 -translate-y-1/2
                  text-gray-400 dark:text-gray-500
                  pointer-events-none
                "
              />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by candidate name or email"
                className={`${inputClass} pl-9`}
              />
            </div>

            <select
              value={statusFilter}
              onChange={(e) =>
                setStatusFilter(
                  e.target.value as "all" | AssessmentAssignmentStatus
                )
              }
              className={`${inputClass} md:w-56`}
            >
              {STATUS_FILTERS.map((filter) => (
                <option key={filter.value} value={filter.value}>
                  {filter.label}
                </option>
              ))}
            </select>
          </div>

          {filteredResults.length === 0 ? (
            <p className="px-6 pb-6 text-gray-500 dark:text-gray-400 text-sm">
              No candidates match your search or filter.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead
                  className="
                    bg-gray-50 dark:bg-gray-800
                    text-gray-600 dark:text-gray-400
                    text-sm
                  "
                >
                  <tr>
                    <th className="px-6 py-4">Candidate</th>
                    <th className="px-6 py-4">Status</th>
                    <th className="px-6 py-4">Started</th>
                    <th className="px-6 py-4">Submitted</th>
                    <th className="px-6 py-4">Answered</th>
                    <th className="px-6 py-4">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredResults.map((result) => {
                    const displayName =
                      result.candidate_name ||
                      `Candidate ${result.candidate_id}`;
                    return (
                      <tr
                        key={result.assignment_id}
                        onClick={() =>
                          setSelected({
                            assignmentId: result.assignment_id,
                            candidateName: displayName,
                          })
                        }
                        className="
                          border-t border-gray-200 dark:border-gray-800
                          hover:bg-gray-50 dark:hover:bg-gray-800/50
                          transition cursor-pointer
                        "
                      >
                        <td className="px-6 py-4">
                          <p className="font-medium text-gray-900 dark:text-white">
                            {displayName}
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            {result.candidate_email}
                          </p>
                        </td>

                        <td className="px-6 py-4">
                          <span
                            className={`px-3 py-1 rounded-full text-sm font-medium ${assignmentStatusBadgeClass(
                              result.status
                            )}`}
                          >
                            {ASSIGNMENT_STATUS_LABELS[result.status]}
                          </span>
                        </td>

                        <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300">
                          {result.started_at
                            ? formatDateTime(result.started_at)
                            : "—"}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300">
                          {result.submitted_at
                            ? formatDateTime(result.submitted_at)
                            : "—"}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300">
                          {result.answered_questions}/{result.total_questions}
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <span className="text-sm font-medium text-gray-900 dark:text-white">
                              {result.total_score}/{result.maximum_score}
                            </span>
                            <span
                              className={`text-sm font-semibold ${percentageBadgeClass(
                                result.percentage,
                                result.maximum_score
                              )}`}
                            >
                              {result.percentage}%
                            </span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {selected && (
        <ResultDetailModal
          assessmentId={assessmentId}
          assignmentId={selected.assignmentId}
          candidateName={selected.candidateName}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

function ResultDetailModal({
  assessmentId,
  assignmentId,
  candidateName,
  onClose,
}: {
  assessmentId: number;
  assignmentId: number;
  candidateName: string;
  onClose: () => void;
}): JSX.Element {
  const [detail, setDetail] = useState<AssessmentResultDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadDetail = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAssessmentResult(assessmentId, assignmentId);
      setDetail(data);
    } catch (e) {
      setError(resultErrorMessage(e, "Failed to load this candidate's results"));
    } finally {
      setLoading(false);
    }
  }, [assessmentId, assignmentId]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const sectionsWithQuestions = useMemo(() => {
    if (!detail) return [];
    const bySection = new Map<number, AssessmentQuestionResult[]>();
    for (const question of detail.questions) {
      const list = bySection.get(question.section_id) ?? [];
      list.push(question);
      bySection.set(question.section_id, list);
    }
    return detail.sections.map((section) => ({
      section,
      questions: bySection.get(section.section_id) ?? [],
    }));
  }, [detail]);

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div
        className="
          bg-white dark:bg-gray-900
          w-full max-w-4xl
          rounded-2xl border border-gray-200 dark:border-gray-800
          shadow-xl flex flex-col
          max-h-[90vh]
        "
      >
        <div className="flex items-center justify-between p-6 pb-4">
          <div className="min-w-0">
            <h3 className="text-gray-900 dark:text-white text-lg font-semibold truncate">
              {candidateName}
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 truncate">
              Candidate Results
            </p>
          </div>
          <button onClick={onClose} aria-label="Close dialog">
            <X className="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white" />
          </button>
        </div>

        <div className="px-6 pb-4 flex-1 min-h-0 overflow-y-auto">
          {loading && (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Loading results...
            </p>
          )}

          {!loading && error && (
            <div className="text-sm">
              <p className="text-red-600 dark:text-red-400">{error}</p>
              <button
                onClick={() => void loadDetail()}
                className="
                  mt-3 px-4 py-2 rounded-lg
                  border border-gray-300 dark:border-gray-700
                  text-gray-600 dark:text-gray-400
                  hover:bg-gray-50 dark:hover:bg-gray-800
                  transition
                "
              >
                Retry
              </button>
            </div>
          )}

          {!loading && !error && detail && (
            <div className="space-y-6">
              <div
                className="
                  rounded-2xl border border-gray-200 dark:border-gray-800
                  p-6 space-y-4
                "
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xl font-semibold text-gray-900 dark:text-white">
                    {detail.assessment_title}
                  </p>
                  <span
                    className={`px-3 py-1 rounded-full text-sm font-medium shrink-0 ${assignmentStatusBadgeClass(
                      detail.status
                    )}`}
                  >
                    {ASSIGNMENT_STATUS_LABELS[detail.status]}
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 text-sm">
                  <Info
                    label="Candidate"
                    value={`${detail.candidate_name || ""}${
                      detail.candidate_email ? ` • ${detail.candidate_email}` : ""
                    }`}
                  />
                  <Info
                    label="Started"
                    value={
                      detail.started_at
                        ? formatDateTime(detail.started_at)
                        : "Not started"
                    }
                  />
                  <Info
                    label="Submitted"
                    value={
                      detail.submitted_at
                        ? formatDateTime(detail.submitted_at)
                        : "Not submitted"
                    }
                  />
                  <Info
                    label="Answered"
                    value={`${detail.answered_questions}/${detail.total_questions}`}
                  />
                  <Info
                    label="Marks"
                    value={`${detail.total_score}/${detail.maximum_score}`}
                  />
                  <div>
                    <p className="text-gray-500 dark:text-gray-400">Score</p>
                    <span
                      className={`mt-1 inline-block px-3 py-1 rounded-full text-sm font-semibold ${percentageBadgeClass(
                        detail.percentage,
                        detail.maximum_score
                      )}`}
                    >
                      {detail.percentage}%
                    </span>
                  </div>
                </div>
              </div>

              <div
                className="
                  rounded-2xl border border-gray-200 dark:border-gray-800
                  overflow-hidden
                "
              >
                <div className="px-6 py-4">
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">
                    Section Performance
                  </p>
                </div>
                {sectionsWithQuestions.length === 0 ? (
                  <p className="px-6 pb-6 text-sm text-gray-500 dark:text-gray-400">
                    No scored sections for this assessment.
                  </p>
                ) : (
                  <ul>
                    {sectionsWithQuestions.map(({ section }) => (
                      <li
                        key={section.section_id}
                        className="border-t border-gray-200 dark:border-gray-800"
                      >
                        <div className="px-6 py-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="font-medium text-gray-900 dark:text-white">
                              <span
                                className="
                                  inline-flex w-7 h-7 mr-2
                                  rounded-full bg-indigo-600/10
                                  text-indigo-600 dark:text-indigo-400
                                  items-center justify-center text-xs font-semibold
                                "
                              >
                                {section.section_order}
                              </span>
                              {section.title}
                              <span className="ml-2 text-xs font-normal text-gray-500 dark:text-gray-400">
                                {SECTION_TYPE_LABELS[section.section_type]}
                              </span>
                            </p>
                            <p className="text-sm font-medium text-gray-900 dark:text-white shrink-0">
                              {section.total_score}/{section.maximum_score} marks
                            </p>
                          </div>

                          <div className="mt-2 flex items-center gap-3">
                            <div className="flex-1">
                              <ProgressBar percentage={section.percentage} />
                            </div>
                            <p className="text-xs text-gray-500 dark:text-gray-400 shrink-0">
                              {section.answered_questions}/
                              {section.total_questions} answered •{" "}
                              {section.percentage}%
                            </p>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div
                className="
                  rounded-2xl border border-gray-200 dark:border-gray-800
                  overflow-hidden
                "
              >
                <div className="px-6 py-4">
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">
                    Question-wise Results
                  </p>
                </div>
                {detail.questions.length === 0 ? (
                  <p className="px-6 pb-6 text-sm text-gray-500 dark:text-gray-400">
                    No questions recorded for this assessment.
                  </p>
                ) : (
                  <ul>
                    {sectionsWithQuestions.map(({ section, questions }) => (
                      <li key={section.section_id}>
                        <p className="px-6 pt-4 pb-2 text-sm font-semibold text-gray-700 dark:text-gray-300">
                          {section.title}
                        </p>
                        <ul>
                          {questions.map((question) => {
                            const verdict = questionVerdict(question);
                            return (
                              <li
                                key={question.question_id}
                                className="
                                  border-t border-gray-200 dark:border-gray-800
                                  px-6 py-4
                                "
                              >
                                <div className="flex items-start gap-4">
                                  <span
                                    className="
                                      w-7 h-7 shrink-0 mt-0.5 rounded-full
                                      bg-gray-100 dark:bg-gray-800
                                      text-gray-600 dark:text-gray-400
                                      flex items-center justify-center text-xs font-semibold
                                    "
                                  >
                                    {question.question_order}
                                  </span>

                                  <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                                      {question.question_text}
                                    </p>
                                    <p className="text-xs text-gray-500 dark:text-gray-400">
                                      {question.question_type === "coding"
                                        ? "Coding"
                                        : "MCQ"}
                                      {question.title &&
                                        ` • ${question.title}`}
                                      {question.category &&
                                        ` • ${question.category}`}
                                      {question.answered_at &&
                                        ` • Answered ${formatDateTime(
                                          question.answered_at
                                        )}`}
                                    </p>

                                    {question.question_type === "coding" &&
                                      question.answered &&
                                      question.status !== "error" &&
                                      question.total_cases != null && (
                                        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                                          {question.passed_cases ?? 0}/
                                          {question.total_cases} cases passed
                                          {question.execution_time_ms != null &&
                                            ` • ${question.execution_time_ms} ms`}
                                        </p>
                                      )}
                                  </div>

                                  <div className="shrink-0 text-right">
                                    <span
                                      className={`inline-block px-3 py-1 rounded-full text-xs font-medium ${verdict.className}`}
                                    >
                                      {verdict.label}
                                    </span>
                                    <p className="mt-1 text-sm font-medium text-gray-900 dark:text-white">
                                      {question.earned_score}/
                                      {question.max_score} marks
                                    </p>
                                    {question.max_score > 0 && (
                                      <p className="text-xs text-gray-500 dark:text-gray-400">
                                        {question.percentage}%
                                      </p>
                                    )}
                                  </div>
                                </div>
                              </li>
                            );
                          })}
                        </ul>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}