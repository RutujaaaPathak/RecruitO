import { api } from "./api";

export type AssessmentAssignmentStatus =
  | "assigned"
  | "in_progress"
  | "submitted";

export interface AssessmentAssignment {
  id: number;
  assessment_id: number;
  candidate_id: number;
  status: AssessmentAssignmentStatus;
  assigned_at: string;
  started_at: string | null;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
  candidate_name: string | null;
  candidate_email: string | null;
  assessment_title: string | null;
}

export const ASSIGNMENT_STATUS_LABELS: Record<
  AssessmentAssignmentStatus,
  string
> = {
  assigned: "Assigned",
  in_progress: "In Progress",
  submitted: "Submitted",
};

export function assignmentStatusBadgeClass(
  status: AssessmentAssignmentStatus
): string {
  if (status === "submitted") {
    return "bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400";
  }
  if (status === "in_progress") {
    return "bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400";
  }
  return "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-400";
}

export function listAssignments(
  assessmentId: number
): Promise<AssessmentAssignment[]> {
  return api.get<AssessmentAssignment[]>(
    `/assessments/${assessmentId}/assignments`
  );
}

export function assignCandidates(
  assessmentId: number,
  candidateIds: number[]
): Promise<AssessmentAssignment[]> {
  return api.post<AssessmentAssignment[]>(
    `/assessments/${assessmentId}/assignments`,
    { candidate_ids: candidateIds }
  );
}

export function removeAssignment(
  assessmentId: number,
  assignmentId: number
): Promise<void> {
  return api.del<void>(
    `/assessments/${assessmentId}/assignments/${assignmentId}`
  );
}