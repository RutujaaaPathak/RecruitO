import { useCallback, useEffect, useMemo, useState } from "react";
import { Search, Trash2, UserPlus, X } from "lucide-react";
import { api } from "../../lib/api";
import { formatDateTime } from "../../lib/assessments";
import {
  ASSIGNMENT_STATUS_LABELS,
  AssessmentAssignment,
  assignmentStatusBadgeClass,
  assignCandidates,
  listAssignments,
  removeAssignment,
} from "../../lib/assignments";

interface ApplicationOut {
  id: number;
  job_id: number;
  user_id: number;
  status: string;
  match_score?: number | null;
  created_at: string;
  job_title?: string | null;
  company_name?: string | null;
  applicant_name?: string | null;
  applicant_email?: string | null;
  applicant_phone?: string | null;
  applicant_skills?: string[] | null;
}

interface CandidateOption {
  user_id: number;
  name: string;
  email: string;
  phone: string | null;
  jobTitles: string[];
}

function buildCandidatePool(applications: ApplicationOut[]): CandidateOption[] {
  const byUser = new Map<number, CandidateOption>();
  for (const application of applications) {
    const jobTitle = application.job_title || "Unknown role";
    const existing = byUser.get(application.user_id);
    if (existing) {
      if (!existing.jobTitles.includes(jobTitle)) {
        existing.jobTitles.push(jobTitle);
      }
      continue;
    }
    byUser.set(application.user_id, {
      user_id: application.user_id,
      name: application.applicant_name || "Candidate",
      email: application.applicant_email || "",
      phone: application.applicant_phone ?? null,
      jobTitles: [jobTitle],
    });
  }
  return [...byUser.values()].sort((a, b) => a.name.localeCompare(b.name));
}

const inputClass = `
  w-full p-3 rounded-xl border
  bg-white text-gray-900
  dark:bg-gray-800 dark:text-white
  border-gray-300 dark:border-gray-700
  outline-none focus:ring-2 focus:ring-indigo-500
`;

const iconButtonClass = `
  p-2 rounded-lg transition
  text-gray-500 hover:text-gray-900 hover:bg-gray-100
  dark:text-gray-400 dark:hover:text-white dark:hover:bg-gray-800
  disabled:opacity-40 disabled:cursor-not-allowed
`;

export default function AssignedCandidates({
  assessmentId,
  onChanged,
}: {
  assessmentId: number;
  onChanged?: () => void;
}): JSX.Element {
  const [assignments, setAssignments] = useState<AssessmentAssignment[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [showAssignModal, setShowAssignModal] = useState<boolean>(false);
  const [allCandidates, setAllCandidates] = useState<CandidateOption[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState<boolean>(false);
  const [candidatesError, setCandidatesError] = useState<string | null>(null);
  const [search, setSearch] = useState<string>("");
  const [jobFilter, setJobFilter] = useState<string>("all");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [assigning, setAssigning] = useState<boolean>(false);
  const [assignFormError, setAssignFormError] = useState<string | null>(null);

  const [assignmentToRemove, setAssignmentToRemove] =
    useState<AssessmentAssignment | null>(null);
  const [removing, setRemoving] = useState<boolean>(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const data = await listAssignments(assessmentId);
      setAssignments(data);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to load assigned candidates"
      );
    }
  }, [assessmentId]);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  const reloadCandidates = useCallback(async (): Promise<void> => {
    setCandidatesLoading(true);
    setCandidatesError(null);
    try {
      const applications = await api.get<ApplicationOut[]>("/applications");
      setAllCandidates(buildCandidatePool(applications));
    } catch (e) {
      setCandidatesError(
        e instanceof Error ? e.message : "Failed to load candidates"
      );
    } finally {
      setCandidatesLoading(false);
    }
  }, []);

  const openAssignModal = (): void => {
    setAssignFormError(null);
    setSearch("");
    setJobFilter("all");
    setSelectedIds(new Set());
    setSuccess(null);
    setShowAssignModal(true);
    void reloadCandidates();
  };

  const assignedUserIds = useMemo(
    () => new Set(assignments.map((a) => a.candidate_id)),
    [assignments]
  );

  const jobTitles = useMemo(() => {
    const titles = new Set<string>();
    for (const candidate of allCandidates) {
      for (const title of candidate.jobTitles) {
        titles.add(title);
      }
    }
    return [...titles].sort();
  }, [allCandidates]);

  const availableCandidates = useMemo(() => {
    const query = search.trim().toLowerCase();
    return allCandidates.filter((candidate) => {
      if (assignedUserIds.has(candidate.user_id)) return false;
      if (jobFilter !== "all" && !candidate.jobTitles.includes(jobFilter)) {
        return false;
      }
      if (query) {
        const haystack = [
          candidate.name,
          candidate.email,
          candidate.phone || "",
        ]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    });
  }, [allCandidates, assignedUserIds, search, jobFilter]);

  const availableIds = useMemo(
    () => new Set(availableCandidates.map((c) => c.user_id)),
    [availableCandidates]
  );

  useEffect(() => {
    setSelectedIds((prev) => {
      const next = new Set<number>();
      let changed = false;
      for (const id of prev) {
        if (availableIds.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [availableIds]);

  const allVisibleSelected =
    availableCandidates.length > 0 &&
    availableCandidates.every((c) => selectedIds.has(c.user_id));

  const toggleCandidate = (userId: number): void => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        next.add(userId);
      }
      return next;
    });
  };

  const toggleAllVisible = (): void => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) {
        for (const candidate of availableCandidates) {
          next.delete(candidate.user_id);
        }
      } else {
        for (const candidate of availableCandidates) {
          next.add(candidate.user_id);
        }
      }
      return next;
    });
  };

  const handleAssign = async (): Promise<void> => {
    if (selectedIds.size === 0) return;

    setAssigning(true);
    setAssignFormError(null);
    setError(null);
    setSuccess(null);
    try {
      const ids = [...selectedIds].sort((a, b) => a - b);
      const created = await assignCandidates(assessmentId, ids);
      setSuccess(
        `Assigned ${created.length} candidate${
          created.length === 1 ? "" : "s"
        } to this assessment.`
      );
      setShowAssignModal(false);
      setSelectedIds(new Set());
      await refresh();
      onChanged?.();
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 409) {
        // Atomic backend: nothing was applied. Re-sync so already-assigned
        // candidates drop out of the pool instead of a partial success.
        await refresh();
        onChanged?.();
        setAssignFormError(
          "Some candidates were already assigned to this assessment, so none were assigned. The list has been refreshed."
        );
      } else if (status === 404) {
        setAssignFormError(
          "One or more selected candidates were not found, so none were assigned."
        );
      } else if (status === 403) {
        setAssignFormError(
          "You do not have permission to assign candidates to this assessment."
        );
      } else {
        setAssignFormError(
          e instanceof Error ? e.message : "Failed to assign candidates"
        );
      }
    } finally {
      setAssigning(false);
    }
  };

  const handleRemove = async (): Promise<void> => {
    if (!assignmentToRemove) return;

    const name =
      assignmentToRemove.candidate_name || `Candidate ${assignmentToRemove.candidate_id}`;
    setRemoving(true);
    setRemoveError(null);
    try {
      await removeAssignment(assessmentId, assignmentToRemove.id);
      setAssignmentToRemove(null);
      setSuccess(`Removed ${name} from this assessment.`);
      await refresh();
      onChanged?.();
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 404) {
        setAssignmentToRemove(null);
        setError(
          "This assignment no longer exists; it may have been removed already."
        );
        await refresh();
        onChanged?.();
      } else if (status === 409) {
        setRemoveError(
          "This candidate has already started the assessment, so it can no longer be removed."
        );
        await refresh();
        onChanged?.();
      } else if (status === 403) {
        setRemoveError(
          "You do not have permission to remove this assignment."
        );
      } else {
        setRemoveError(
          e instanceof Error ? e.message : "Failed to remove assignment"
        );
      }
    } finally {
      setRemoving(false);
    }
  };

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
          Assigned Candidates
        </h3>

        <button
          onClick={openAssignModal}
          className="
            flex items-center gap-2
            bg-indigo-600 hover:bg-indigo-700
            text-white px-4 py-2 rounded-lg
            text-sm font-medium transition
            disabled:opacity-60
          "
        >
          <UserPlus size={16} />
          Assign Candidates
        </button>
      </div>

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

      {success && (
        <div
          className="
            flex items-center justify-between gap-3
            mx-6 mb-5 p-4 rounded-xl text-sm
            bg-green-500/10 border border-green-500/20
            text-green-600 dark:text-green-400
          "
        >
          <span>{success}</span>
          <button
            onClick={() => setSuccess(null)}
            aria-label="Dismiss message"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {loading ? (
        <p className="px-6 pb-6 text-gray-500 dark:text-gray-400 text-sm">
          Loading assigned candidates...
        </p>
      ) : assignments.length === 0 ? (
        <p className="px-6 pb-6 text-gray-500 dark:text-gray-400 text-sm">
          No candidates are assigned to this assessment yet.
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
                <th className="px-6 py-4">Assigned</th>
                <th className="px-6 py-4">Started</th>
                <th className="px-6 py-4">Submitted</th>
                <th className="px-6 py-4">Action</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((assignment) => {
                const removable = assignment.status === "assigned";
                const displayName =
                  assignment.candidate_name ||
                  `Candidate ${assignment.candidate_id}`;
                return (
                  <tr
                    key={assignment.id}
                    className="
                      border-t border-gray-200 dark:border-gray-800
                      hover:bg-gray-50 dark:hover:bg-gray-800/50
                      transition
                    "
                  >
                    <td className="px-6 py-4">
                      <p className="font-medium text-gray-900 dark:text-white">
                        {displayName}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {assignment.candidate_email}
                      </p>
                    </td>

                    <td className="px-6 py-4">
                      <span
                        className={`px-3 py-1 rounded-full text-sm font-medium ${assignmentStatusBadgeClass(
                          assignment.status
                        )}`}
                      >
                        {ASSIGNMENT_STATUS_LABELS[assignment.status]}
                      </span>
                    </td>

                    <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300">
                      {formatDateTime(assignment.assigned_at)}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300">
                      {assignment.started_at
                        ? formatDateTime(assignment.started_at)
                        : "—"}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300">
                      {assignment.submitted_at
                        ? formatDateTime(assignment.submitted_at)
                        : "—"}
                    </td>

                    <td className="px-6 py-4">
                      <button
                        onClick={() => {
                          setRemoveError(null);
                          setAssignmentToRemove(assignment);
                        }}
                        disabled={!removable}
                        title={
                          removable
                            ? "Remove assignment"
                            : "This candidate has already started the assessment"
                        }
                        aria-label={
                          removable ? "Remove assignment" : "Cannot remove"
                        }
                        className={iconButtonClass}
                      >
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showAssignModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
          <div
            className="
              bg-white dark:bg-gray-900
              w-full max-w-2xl
              rounded-2xl
              border border-gray-200 dark:border-gray-800
              shadow-xl flex flex-col
              max-h-[90vh]
            "
          >
            <div className="flex items-center justify-between p-6 pb-4">
              <h3 className="text-gray-900 dark:text-white text-lg font-semibold">
                Assign Candidates
              </h3>
              <button
                onClick={() => setShowAssignModal(false)}
                aria-label="Close dialog"
              >
                <X className="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white" />
              </button>
            </div>

            {assignFormError && (
              <p className="mx-6 mb-3 text-sm text-red-600 dark:text-red-400">
                {assignFormError}
              </p>
            )}

            <div className="px-6 flex flex-col md:flex-row gap-3">
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
                  placeholder="Search by name or email"
                  className={`${inputClass} pl-9`}
                />
              </div>

              <select
                value={jobFilter}
                onChange={(e) => setJobFilter(e.target.value)}
                className={`${inputClass} md:w-56`}
              >
                <option value="all">All roles</option>
                {jobTitles.map((title) => (
                  <option key={title} value={title}>
                    {title}
                  </option>
                ))}
              </select>
            </div>

            <div className="px-6 py-4 flex-1 min-h-0 overflow-y-auto">
              {candidatesLoading ? (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Loading candidates...
                </p>
              ) : candidatesError ? (
                <div className="text-sm">
                  <p className="text-red-600 dark:text-red-400">
                    {candidatesError}
                  </p>
                  <button
                    onClick={() => void reloadCandidates()}
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
              ) : availableCandidates.length === 0 ? (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {allCandidates.length === 0
                    ? "No candidates available to assign yet. Candidates appear once they apply to your jobs."
                    : "All matching candidates are already assigned to this assessment."}
                </p>
              ) : (
                <div className="space-y-1">
                  <label
                    className="
                      flex items-center gap-3 px-3 py-2 rounded-lg
                      hover:bg-gray-50 dark:hover:bg-gray-800/50
                      cursor-pointer
                    "
                  >
                    <input
                      type="checkbox"
                      checked={allVisibleSelected}
                      onChange={toggleAllVisible}
                      className="
                        h-4 w-4 rounded border-gray-300 dark:border-gray-600
                        text-indigo-600 focus:ring-indigo-500
                      "
                    />
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                      Select all {availableCandidates.length} available
                    </span>
                  </label>

                  {availableCandidates.map((candidate) => (
                    <label
                      key={candidate.user_id}
                      className="
                        flex items-start gap-3 px-3 py-2 rounded-lg
                        hover:bg-gray-50 dark:hover:bg-gray-800/50
                        cursor-pointer
                      "
                    >
                      <input
                        type="checkbox"
                        checked={selectedIds.has(candidate.user_id)}
                        onChange={() => toggleCandidate(candidate.user_id)}
                        className="
                          mt-1 h-4 w-4 rounded
                          border-gray-300 dark:border-gray-600
                          text-indigo-600 focus:ring-indigo-500
                        "
                      />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium text-gray-900 dark:text-white">
                          {candidate.name}
                        </span>
                        <span className="block text-xs text-gray-500 dark:text-gray-400">
                          {candidate.email}
                          {candidate.phone && ` • ${candidate.phone}`}
                        </span>
                        <span className="block text-xs text-gray-500 dark:text-gray-400">
                          {candidate.jobTitles.join(", ")}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div
              className="
                flex items-center justify-between gap-3
                border-t border-gray-200 dark:border-gray-800
                p-6
              "
            >
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {selectedIds.size} selected
              </p>

              <div className="flex gap-3">
                <button
                  onClick={() => setShowAssignModal(false)}
                  disabled={assigning}
                  className="
                    px-4 py-2 rounded-lg
                    border border-gray-300 dark:border-gray-700
                    text-gray-600 dark:text-gray-400
                    hover:bg-gray-50 dark:hover:bg-gray-800
                    transition disabled:opacity-60
                  "
                >
                  Cancel
                </button>

                <button
                  onClick={handleAssign}
                  disabled={assigning || selectedIds.size === 0}
                  className="
                    px-4 py-2 rounded-lg
                    bg-indigo-600 hover:bg-indigo-700
                    text-white text-sm font-medium
                    transition disabled:opacity-60
                  "
                >
                  {assigning
                    ? "Assigning..."
                    : selectedIds.size > 0
                    ? `Assign (${selectedIds.size})`
                    : "Assign"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {assignmentToRemove && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
          <div
            className="
              bg-white dark:bg-gray-900
              border border-gray-200 dark:border-gray-800
              p-6 rounded-2xl w-full max-w-sm shadow-xl
            "
          >
            <h3 className="text-gray-900 dark:text-white text-lg font-semibold">
              Remove Candidate?
            </h3>

            <p className="text-gray-600 dark:text-gray-400 text-sm mt-2">
              Remove{" "}
              {assignmentToRemove.candidate_name ||
                `Candidate ${assignmentToRemove.candidate_id}`}{" "}
              from this assessment? They will no longer be able to take it.
            </p>

            {removeError && (
              <p className="text-sm text-red-600 dark:text-red-400 mt-3">
                {removeError}
              </p>
            )}

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setAssignmentToRemove(null)}
                disabled={removing}
                className="
                  px-4 py-2 rounded-lg
                  bg-gray-100 text-gray-700
                  hover:bg-gray-200
                  dark:bg-gray-800 dark:text-gray-300
                  transition disabled:opacity-60
                "
              >
                Cancel
              </button>

              <button
                onClick={handleRemove}
                disabled={removing}
                className="
                  px-4 py-2 rounded-lg
                  bg-red-600 text-white
                  hover:bg-red-700
                  transition disabled:opacity-60
                "
              >
                {removing ? "Removing..." : "Confirm Remove"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}