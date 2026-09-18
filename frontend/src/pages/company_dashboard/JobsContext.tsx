import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
  useCallback,
} from "react";
import { Job, ApiJob, toUIFrontJob, ApiJobInput } from "./data";
import { api } from "../../lib/api";

interface JobsContextType {
  jobs: Job[];
  setJobs: React.Dispatch<React.SetStateAction<Job[]>>;
  loading: boolean;
  error: string | null;
  refreshJobs: () => Promise<void>;
  createJob: (input: ApiJobInput) => Promise<Job>;
  updateJob: (id: number, input: Partial<ApiJobInput>) => Promise<Job>;
  deleteJob: (id: number) => Promise<void>;
}

const JobsContext = createContext<JobsContextType | undefined>(undefined);

export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const refreshJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<ApiJob[]>("/jobs");
      setJobs(data.map(toUIFrontJob));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs");
      // Keep previously-loaded jobs on failure rather than wiping the list.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshJobs();
  }, [refreshJobs]);

  const createJob = useCallback(
    async (input: ApiJobInput): Promise<Job> => {
      const created = await api.post<ApiJob>("/jobs", input);
      const uiJob = toUIFrontJob(created);
      setJobs((prev) => [uiJob, ...prev]);
      return uiJob;
    },
    []
  );

  const updateJob = useCallback(
    async (id: number, input: Partial<ApiJobInput>): Promise<Job> => {
      const updated = await api.put<ApiJob>(`/jobs/${id}`, input);
      const uiJob = toUIFrontJob(updated);
      setJobs((prev) => prev.map((j) => (j.id === id ? uiJob : j)));
      return uiJob;
    },
    []
  );

  const deleteJob = useCallback(async (id: number): Promise<void> => {
    await api.del(`/jobs/${id}`);
    setJobs((prev) => prev.filter((j) => j.id !== id));
  }, []);

  return (
    <JobsContext.Provider
      value={{
        jobs,
        setJobs,
        loading,
        error,
        refreshJobs,
        createJob,
        updateJob,
        deleteJob,
      }}
    >
      {children}
    </JobsContext.Provider>
  );
}

export function useJobs() {
  const context = useContext(JobsContext);
  if (!context) {
    throw new Error("useJobs must be used inside JobsProvider");
  }
  return context;
}
