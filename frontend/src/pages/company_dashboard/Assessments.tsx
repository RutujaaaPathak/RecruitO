import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ClipboardList, Plus, X } from "lucide-react";
import CompanyLayout from "./CompanyLayout";
import AssessmentFormFields from "./AssessmentFormFields";
import {
  Assessment,
  AssessmentFormState,
  assessmentFormToPayload,
  assessmentStatusBadgeClass,
  createAssessment,
  emptyAssessmentForm,
  formatDateTime,
  listAssessments,
  validateAssessmentForm,
} from "../../lib/assessments";

export default function Assessments() {
  const navigate = useNavigate();

  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState<boolean>(false);
  const [form, setForm] = useState<AssessmentFormState>(
    emptyAssessmentForm()
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [creating, setCreating] = useState<boolean>(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const loadAssessments = useCallback(async (): Promise<void> => {
    try {
      const data = await listAssessments();
      setAssessments(data);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to load assessments"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAssessments();
  }, [loadAssessments]);

  const openCreate = (): void => {
    setForm(emptyAssessmentForm());
    setFormError(null);
    setShowCreate(true);
  };

  const handleCreate = async (): Promise<void> => {
    const validationError = validateAssessmentForm(form);
    if (validationError) {
      setFormError(validationError);
      return;
    }

    setCreating(true);
    setFormError(null);
    try {
      await createAssessment(assessmentFormToPayload(form));
      setShowCreate(false);
      setForm(emptyAssessmentForm());
      setSuccessMessage("Assessment created successfully.");
      loadAssessments();
    } catch (e) {
      setFormError(
        e instanceof Error ? e.message : "Failed to create assessment"
      );
    } finally {
      setCreating(false);
    }
  };

  return (
    <CompanyLayout>
      <div className="max-w-6xl mx-auto space-y-10">

        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-3xl font-bold text-gray-900 dark:text-white">
            Assessments
          </h2>

          <button
            onClick={openCreate}
            className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-3 rounded-xl font-medium transition shadow-md hover:shadow-lg"
          >
            <Plus size={18} />
            Create Assessment
          </button>
        </div>

        {successMessage && (
          <div className="flex items-center justify-between p-4 rounded-xl text-sm bg-green-500/10 border border-green-500/20 text-green-600 dark:text-green-400">
            <span>{successMessage}</span>
            <button
              onClick={() => setSuccessMessage(null)}
              aria-label="Dismiss message"
            >
              <X size={16} />
            </button>
          </div>
        )}

        {loading && (
          <p className="text-gray-500 dark:text-gray-400">
            Loading assessments...
          </p>
        )}

        {!loading && error && (
          <div className="p-4 rounded-xl text-sm bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {!loading && !error && assessments.length === 0 && (
          <p className="text-gray-500 dark:text-gray-400">
            No assessments yet. Create your first assessment.
          </p>
        )}

        {!loading && !error && assessments.length > 0 && (
          <div className="grid md:grid-cols-2 gap-6">
            {assessments.map((assessment) => (
              <div
                key={assessment.id}
                onClick={() =>
                  navigate(`/company/assessments/${assessment.id}`)
                }
                className="
                  bg-white dark:bg-gray-900
                  border border-gray-200 dark:border-gray-800
                  rounded-2xl p-6 cursor-pointer
                  hover:border-indigo-500 hover:shadow-lg
                  transition-all
                "
              >
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <ClipboardList className="text-indigo-500 dark:text-indigo-400" />
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                      {assessment.title}
                    </h3>
                  </div>

                  <span
                    className={`px-3 py-1 rounded-full text-xs font-medium capitalize ${assessmentStatusBadgeClass(
                      assessment.status
                    )}`}
                  >
                    {assessment.status}
                  </span>
                </div>

                <div className="space-y-1 text-sm text-gray-600 dark:text-gray-400">
                  <p>
                    Duration:
                    <span className="text-gray-900 dark:text-white font-medium ml-2">
                      {assessment.duration_minutes != null
                        ? `${assessment.duration_minutes} minutes`
                        : "Not set"}
                    </span>
                  </p>
                  <p>
                    Window:
                    <span className="text-gray-900 dark:text-white font-medium ml-2">
                      {formatDateTime(assessment.starts_at)} —{" "}
                      {formatDateTime(assessment.ends_at)}
                    </span>
                  </p>
                  <p>
                    Created:
                    <span className="text-gray-900 dark:text-white font-medium ml-2">
                      {formatDateTime(assessment.created_at)}
                    </span>
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Create Modal */}
        {showCreate && (
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="
              bg-white dark:bg-gray-900
              w-full max-w-xl max-h-[90vh] overflow-y-auto
              rounded-2xl p-6
              border border-gray-200 dark:border-gray-800
              shadow-xl space-y-4
            ">
              <div className="flex justify-between items-center">
                <h3 className="text-gray-900 dark:text-white text-lg font-semibold">
                  Create New Assessment
                </h3>
                <button
                  onClick={() => setShowCreate(false)}
                  aria-label="Close dialog"
                >
                  <X className="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white" />
                </button>
              </div>

              <AssessmentFormFields form={form} onChange={setForm} />

              <button
                onClick={handleCreate}
                disabled={creating}
                className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-3 rounded-xl font-medium transition disabled:opacity-60"
              >
                {creating ? "Creating..." : "Create Assessment"}
              </button>

              {formError && (
                <p className="text-sm text-red-600 dark:text-red-400 text-center">
                  {formError}
                </p>
              )}
            </div>
          </div>
        )}

      </div>
    </CompanyLayout>
  );
}
