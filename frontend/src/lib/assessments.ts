import { api } from "./api";
import type { AssessmentAssignmentStatus } from "./assignments";

export type AssessmentStatus = "draft" | "published" | "closed";

export type AssessmentSectionType =
  | "aptitude"
  | "technical"
  | "coding"
  | "hr"
  | "technical_interview";

export interface Assessment {
  id: number;
  company_id: number;
  title: string;
  description: string | null;
  instructions: string | null;
  status: AssessmentStatus;
  duration_minutes: number | null;
  starts_at: string | null;
  ends_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssessmentSection {
  id: number;
  assessment_id: number;
  section_type: AssessmentSectionType;
  title: string;
  section_order: number;
  marks: number | null;
  settings: Record<string, unknown> | null;
  created_at: string;
}

export interface AssessmentAssignmentSummary {
  id: number;
  assessment_id: number;
  candidate_id: number;
  status: string;
  assigned_at: string;
  started_at: string | null;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssessmentDetail extends Assessment {
  sections: AssessmentSection[];
  assignments: AssessmentAssignmentSummary[];
}

export interface AssessmentPayload {
  title: string;
  description: string | null;
  instructions: string | null;
  status: AssessmentStatus;
  duration_minutes: number | null;
  starts_at: string | null;
  ends_at: string | null;
}

export interface AssessmentSectionPayload {
  section_type: AssessmentSectionType;
  title: string;
  marks: number | null;
}

export interface AssessmentSectionUpdatePayload {
  section_type: AssessmentSectionType;
  title: string;
  marks: number | null;
}

export interface AssessmentFormState {
  title: string;
  description: string;
  instructions: string;
  status: AssessmentStatus;
  duration: string;
  startsAt: string;
  endsAt: string;
}

export interface SectionFormState {
  section_type: AssessmentSectionType;
  title: string;
  marks: string;
}

export const ASSESSMENT_STATUSES: AssessmentStatus[] = [
  "draft",
  "published",
  "closed",
];

export const ASSESSMENT_STATUS_LABELS: Record<AssessmentStatus, string> = {
  draft: "Draft",
  published: "Published",
  closed: "Closed",
};

export const SECTION_TYPES: AssessmentSectionType[] = [
  "aptitude",
  "technical",
  "coding",
  "hr",
  "technical_interview",
];

export const SECTION_TYPE_LABELS: Record<AssessmentSectionType, string> = {
  aptitude: "Aptitude",
  technical: "Technical",
  coding: "Coding",
  hr: "HR",
  technical_interview: "Technical Interview",
};

export function assessmentStatusBadgeClass(status: AssessmentStatus): string {
  if (status === "published") {
    return "bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400";
  }
  if (status === "draft") {
    return "bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400";
  }
  return "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400";
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "Not set";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Not set";
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

function toDateTimeLocalValue(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate()
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function emptyAssessmentForm(): AssessmentFormState {
  return {
    title: "",
    description: "",
    instructions: "",
    status: "draft",
    duration: "",
    startsAt: "",
    endsAt: "",
  };
}

export function assessmentToFormState(
  assessment: Assessment
): AssessmentFormState {
  return {
    title: assessment.title,
    description: assessment.description ?? "",
    instructions: assessment.instructions ?? "",
    status: assessment.status,
    duration:
      assessment.duration_minutes != null
        ? String(assessment.duration_minutes)
        : "",
    startsAt: toDateTimeLocalValue(assessment.starts_at),
    endsAt: toDateTimeLocalValue(assessment.ends_at),
  };
}

export function validateAssessmentForm(
  form: AssessmentFormState
): string | null {
  if (!form.title.trim()) {
    return "Title is required.";
  }

  if (form.duration.trim()) {
    const duration = Number(form.duration);
    if (!Number.isInteger(duration) || duration < 1) {
      return "Duration must be a whole number of minutes (at least 1).";
    }
  }

  let startsAt: number | null = null;
  let endsAt: number | null = null;

  if (form.startsAt) {
    startsAt = new Date(form.startsAt).getTime();
    if (Number.isNaN(startsAt)) {
      return "Start date/time is invalid.";
    }
  }

  if (form.endsAt) {
    endsAt = new Date(form.endsAt).getTime();
    if (Number.isNaN(endsAt)) {
      return "End date/time is invalid.";
    }
  }

  if (startsAt !== null && endsAt !== null && endsAt < startsAt) {
    return "End date/time must be on or after start date/time.";
  }

  return null;
}

export function assessmentFormToPayload(
  form: AssessmentFormState
): AssessmentPayload {
  const trimmedDescription = form.description.trim();
  const trimmedInstructions = form.instructions.trim();

  return {
    title: form.title.trim(),
    description: trimmedDescription || null,
    instructions: trimmedInstructions || null,
    status: form.status,
    duration_minutes: form.duration.trim()
      ? Number(form.duration.trim())
      : null,
    starts_at: form.startsAt
      ? new Date(form.startsAt).toISOString()
      : null,
    ends_at: form.endsAt ? new Date(form.endsAt).toISOString() : null,
  };
}

export function emptySectionForm(): SectionFormState {
  return {
    section_type: "aptitude",
    title: "",
    marks: "",
  };
}

export function sectionToFormState(
  section: AssessmentSection
): SectionFormState {
  return {
    section_type: section.section_type,
    title: section.title,
    marks: section.marks != null ? String(section.marks) : "",
  };
}

export function validateSectionForm(form: SectionFormState): string | null {
  if (!form.title.trim()) {
    return "Section title is required.";
  }
  if (form.marks.trim()) {
    const marks = Number(form.marks);
    if (!Number.isInteger(marks) || marks < 0) {
      return "Marks must be a whole number of 0 or more.";
    }
  }
  return null;
}

export function sectionFormToPayload(
  form: SectionFormState
): AssessmentSectionPayload {
  return {
    section_type: form.section_type,
    title: form.title.trim(),
    marks: form.marks.trim() ? Number(form.marks.trim()) : null,
  };
}

export function listAssessments(): Promise<Assessment[]> {
  return api.get<Assessment[]>("/assessments");
}

export function getAssessment(id: number): Promise<AssessmentDetail> {
  return api.get<AssessmentDetail>(`/assessments/${id}`);
}

export function createAssessment(
  payload: AssessmentPayload
): Promise<Assessment> {
  return api.post<Assessment>("/assessments", payload);
}

export function updateAssessment(
  id: number,
  payload: AssessmentPayload
): Promise<Assessment> {
  return api.put<Assessment>(`/assessments/${id}`, payload);
}

export function deleteAssessment(id: number): Promise<void> {
  return api.del<void>(`/assessments/${id}`);
}

export function addSection(
  assessmentId: number,
  payload: AssessmentSectionPayload
): Promise<AssessmentSection> {
  return api.post<AssessmentSection>(
    `/assessments/${assessmentId}/sections`,
    payload
  );
}

export function updateSection(
  assessmentId: number,
  sectionId: number,
  payload: AssessmentSectionUpdatePayload
): Promise<AssessmentSection> {
  return api.put<AssessmentSection>(
    `/assessments/${assessmentId}/sections/${sectionId}`,
    payload
  );
}

export function deleteSection(
  assessmentId: number,
  sectionId: number
): Promise<void> {
  return api.del<void>(`/assessments/${assessmentId}/sections/${sectionId}`);
}

export function reorderSections(
  assessmentId: number,
  orderedSectionIds: number[]
): Promise<AssessmentSection[]> {
  return api.put<AssessmentSection[]>(
    `/assessments/${assessmentId}/sections/reorder`,
    { ordered_section_ids: orderedSectionIds }
  );
}

export interface AssessmentSectionResult {
  section_id: number;
  section_type: AssessmentSectionType;
  title: string;
  section_order: number;
  total_questions: number;
  answered_questions: number;
  total_score: number;
  maximum_score: number;
  percentage: number;
}

export interface AssessmentResult {
  assignment_id: number;
  assessment_id: number;
  assessment_title: string;
  candidate_id: number;
  candidate_name: string | null;
  candidate_email: string | null;
  status: AssessmentAssignmentStatus;
  assigned_at: string;
  started_at: string | null;
  submitted_at: string | null;
  total_questions: number;
  answered_questions: number;
  total_score: number;
  maximum_score: number;
  percentage: number;
  sections: AssessmentSectionResult[];
}

export interface AssessmentQuestionResult {
  question_id: number;
  section_id: number;
  section_type: AssessmentSectionType;
  section_title: string;
  question_order: number;
  question_type: "mcq" | "coding";
  question_text: string;
  title: string | null;
  category: string | null;
  answered: boolean;
  selected_option: number | null;
  correct: boolean | null;
  earned_score: number;
  max_score: number;
  percentage: number;
  status: string | null;
  passed_cases: number | null;
  total_cases: number | null;
  execution_time_ms: number | null;
  answered_at: string | null;
}

export interface AssessmentResultDetail extends AssessmentResult {
  questions: AssessmentQuestionResult[];
}

export function listAssessmentResults(
  assessmentId: number
): Promise<AssessmentResult[]> {
  return api.get<AssessmentResult[]>(`/assessments/${assessmentId}/results`);
}

export function getAssessmentResult(
  assessmentId: number,
  assignmentId: number
): Promise<AssessmentResultDetail> {
  return api.get<AssessmentResultDetail>(
    `/assessments/${assessmentId}/results/${assignmentId}`
  );
}
