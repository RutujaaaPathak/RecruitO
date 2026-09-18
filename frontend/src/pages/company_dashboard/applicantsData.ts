export interface Applicant {
  name: string;
  role: string;
  match: number;
  status: string;
  strengths?: string[];
  gaps?: string[];
}

/**
 * Shape returned by the backend /applications endpoints (ApplicationOut).
 */
export interface ApiApplication {
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

/**
 * Map a backend application into the display shape used by the UI.
 */
export function toUIApplicant(app: ApiApplication): Applicant {
  return {
    name: app.applicant_name || "Candidate",
    role: app.job_title || "Unknown role",
    match: app.match_score ?? 0,
    status: app.status,
  };
}
