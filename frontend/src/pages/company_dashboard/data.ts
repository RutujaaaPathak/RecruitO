export interface Job {
  id: number;
  title: string;
  department: string;
  location: string;
  type: string; // Full-time / Internship / Contract
  experience: string;
  salary: string;
  skills: string[];
  vacancies: number;
  applicants: number;
  shortlisted: number;
  interviews: number;
  avgMatch: number;
  postedOn: string;
  deadline: string;
  status: "Open" | "Closed";
  company_id?: number;
  description?: string;
}

/**
 * Shape returned by the backend /jobs endpoints (JobOut).
 */
export interface ApiJob {
  id: number;
  title: string;
  department?: string | null;
  location?: string | null;
  type?: string | null;
  experience?: string | null;
  salary?: string | null;
  skills?: string[] | null;
  vacancies: number;
  description?: string | null;
  deadline?: string | null;
  status: "Open" | "Closed";
  posted_on: string;
  company_id?: number;
  company_name?: string | null;
  applicant_count?: number;
}

/**
 * Map a backend JobOut into the frontend Job shape used by the UI.
 */
export function toUIFrontJob(apiJob: ApiJob): Job {
  return {
    id: apiJob.id,
    title: apiJob.title,
    department: apiJob.department || "General",
    location: apiJob.location || "Not specified",
    type: apiJob.type || "Full-time",
    experience: apiJob.experience || "",
    salary: apiJob.salary || "Not specified",
    skills: apiJob.skills || [],
    vacancies: apiJob.vacancies ?? 1,
    applicants: apiJob.applicant_count ?? 0,
    shortlisted: 0,
    interviews: 0,
    avgMatch: 0,
    postedOn: apiJob.posted_on ? new Date(apiJob.posted_on).toLocaleDateString() : "",
    deadline: apiJob.deadline || "Not Set",
    status: apiJob.status,
    company_id: apiJob.company_id,
    description: apiJob.description || "",
  };
}

export interface ApiJobInput {
  title: string;
  department?: string;
  location?: string;
  type?: string;
  experience?: string;
  salary?: string;
  skills?: string[];
  vacancies?: number;
  description?: string;
  deadline?: string | null;
  status?: "Open" | "Closed";
}
