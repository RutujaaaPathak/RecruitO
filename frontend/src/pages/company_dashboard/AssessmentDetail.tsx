import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import CompanyLayout from "./CompanyLayout";
import AssessmentFormFields from "./AssessmentFormFields";
import {
  AssessmentDetail as AssessmentDetailData,
  AssessmentFormState,
  AssessmentSection,
  ASSESSMENT_STATUS_LABELS,
  SECTION_TYPES,
  SECTION_TYPE_LABELS,
  SectionFormState,
  addSection,
  assessmentFormToPayload,
  assessmentStatusBadgeClass,
  assessmentToFormState,
  deleteAssessment,
  deleteSection,
  emptyAssessmentForm,
  emptySectionForm,
  formatDateTime,
  getAssessment,
  reorderSections,
  sectionFormToPayload,
  sectionToFormState,
  updateAssessment,
  updateSection,
  validateAssessmentForm,
  validateSectionForm,
} from "../../lib/assessments";

const inputClass = `
  w-full p-3 rounded-xl border
  bg-white text-gray-900
  dark:bg-gray-800 dark:text-white
  border-gray-300 dark:border-gray-700
  outline-none focus:ring-2 focus:ring-indigo-500
`;

const labelClass =
  "block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1";

const iconButtonClass = `
  p-2 rounded-lg transition
  text-gray-500 hover:text-gray-900 hover:bg-gray-100
  dark:text-gray-400 dark:hover:text-white dark:hover:bg-gray-800
  disabled:opacity-40 disabled:cursor-not-allowed
`;

export default function AssessmentDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const assessmentId = Number(id);

  const [assessment, setAssessment] = useState<AssessmentDetailData | null>(
    null
  );
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [form, setForm] = useState<AssessmentFormState>(
    emptyAssessmentForm()
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState<boolean>(false);

  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [deleting, setDeleting] = useState<boolean>(false);

  const [sectionModal, setSectionModal] = useState<{
    mode: "add" | "edit";
    sectionId: number | null;
  } | null>(null);
  const [sectionForm, setSectionForm] = useState<SectionFormState>(
    emptySectionForm()
  );
  const [sectionError, setSectionError] = useState<string | null>(null);
  const [sectionBusy, setSectionBusy] = useState<boolean>(false);
  const [sectionToDelete, setSectionToDelete] =
    useState<AssessmentSection | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const loadAssessment = useCallback(
    async (initial: boolean): Promise<void> => {
      if (initial) {
        setLoading(true);
      }
      try {
        const data = await getAssessment(assessmentId);
        setAssessment(data);
        setError(null);
      } catch (e) {
        const message =
          e instanceof Error ? e.message : "Failed to load assessment";
        if (initial) {
          setError(message);
        } else {
          setActionError(message);
        }
      } finally {
        if (initial) {
          setLoading(false);
        }
      }
    },
    [assessmentId]
  );

  useEffect(() => {
    if (Number.isNaN(assessmentId)) {
      setError("Assessment not found.");
      setLoading(false);
      return;
    }
    loadAssessment(true);
  }, [assessmentId, loadAssessment]);

  const startEdit = (): void => {
    if (!assessment) return;
    setForm(assessmentToFormState(assessment));
    setFormError(null);
    setIsEditing(true);
  };

  const cancelEdit = (): void => {
    setIsEditing(false);
    setFormError(null);
  };

  const handleSave = async (): Promise<void> => {
    if (!assessment) return;

    const validationError = validateAssessmentForm(form);
    if (validationError) {
      setFormError(validationError);
      return;
    }

    setSaving(true);
    setFormError(null);
    setActionError(null);
    setSuccessMessage(null);
    try {
      const updated = await updateAssessment(
        assessment.id,
        assessmentFormToPayload(form)
      );
      setAssessment({ ...assessment, ...updated });
      setIsEditing(false);
      setSuccessMessage("Assessment updated successfully.");
    } catch (e) {
      setFormError(
        e instanceof Error ? e.message : "Failed to update assessment"
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (): Promise<void> => {
    if (!assessment) return;
    setDeleting(true);
    setActionError(null);
    try {
      await deleteAssessment(assessment.id);
      navigate("/company/assessments");
    } catch (e) {
      setActionError(
        e instanceof Error ? e.message : "Failed to delete assessment"
      );
      setDeleting(false);
      setShowDeleteModal(false);
    }
  };

  const openAddSection = (): void => {
    setSectionForm(emptySectionForm());
    setSectionError(null);
    setSectionModal({ mode: "add", sectionId: null });
  };

  const openEditSection = (section: AssessmentSection): void => {
    setSectionForm(sectionToFormState(section));
    setSectionError(null);
    setSectionModal({ mode: "edit", sectionId: section.id });
  };

  const handleSectionSubmit = async (): Promise<void> => {
    if (!assessment || !sectionModal) return;

    const validationError = validateSectionForm(sectionForm);
    if (validationError) {
      setSectionError(validationError);
      return;
    }

    setSectionBusy(true);
    setSectionError(null);
    setActionError(null);
    setSuccessMessage(null);
    try {
      const payload = sectionFormToPayload(sectionForm);
      if (sectionModal.mode === "add") {
        await addSection(assessment.id, payload);
      } else if (sectionModal.sectionId != null) {
        await updateSection(assessment.id, sectionModal.sectionId, payload);
      }
      await loadAssessment(false);
      setSectionModal(null);
      setSuccessMessage(
        sectionModal.mode === "add"
          ? "Section added successfully."
          : "Section updated successfully."
      );
    } catch (e) {
      setSectionError(
        e instanceof Error ? e.message : "Failed to save section"
      );
    } finally {
      setSectionBusy(false);
    }
  };

  const handleSectionDelete = async (): Promise<void> => {
    if (!assessment || !sectionToDelete) return;
    setSectionBusy(true);
    setActionError(null);
    setSuccessMessage(null);
    try {
      await deleteSection(assessment.id, sectionToDelete.id);
      await loadAssessment(false);
      setSectionToDelete(null);
      setSuccessMessage("Section deleted successfully.");
    } catch (e) {
      setActionError(
        e instanceof Error ? e.message : "Failed to delete section"
      );
      setSectionToDelete(null);
    } finally {
      setSectionBusy(false);
    }
  };

  const handleMove = async (
    index: number,
    direction: -1 | 1
  ): Promise<void> => {
    if (!assessment) return;
    const sections = assessment.sections;
    const target = index + direction;
    if (target < 0 || target >= sections.length) return;

    const ids = sections.map((section) => section.id);
    const moved = ids[index];
    ids[index] = ids[target];
    ids[target] = moved;

    setSectionBusy(true);
    setActionError(null);
    setSuccessMessage(null);
    try {
      await reorderSections(assessment.id, ids);
      await loadAssessment(false);
      setSuccessMessage("Sections reordered successfully.");
    } catch (e) {
      setActionError(
        e instanceof Error ? e.message : "Failed to reorder sections"
      );
    } finally {
      setSectionBusy(false);
    }
  };

  if (loading) {
    return (
      <CompanyLayout>
        <div className="max-w-6xl mx-auto space-y-10">
          <button
            onClick={() => navigate("/company/assessments")}
            className="flex items-center gap-2 text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white transition"
          >
            <ArrowLeft size={18} />
            Back to Assessments
          </button>
          <p className="text-gray-500 dark:text-gray-400">
            Loading assessment...
          </p>
        </div>
      </CompanyLayout>
    );
  }

  if (error || !assessment) {
    return (
      <CompanyLayout>
        <div className="max-w-6xl mx-auto space-y-10">
          <button
            onClick={() => navigate("/company/assessments")}
            className="flex items-center gap-2 text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white transition"
          >
            <ArrowLeft size={18} />
            Back to Assessments
          </button>
          <div className="p-4 rounded-xl text-sm bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400">
            {error || "Assessment not found."}
          </div>
        </div>
      </CompanyLayout>
    );
  }

  return (
    <CompanyLayout>
      <div className="max-w-6xl mx-auto space-y-10">

        {/* Back */}
        <button
          onClick={() => navigate("/company/assessments")}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white transition"
        >
          <ArrowLeft size={18} />
          Back to Assessments
        </button>

        {actionError && (
          <div className="flex items-center justify-between p-4 rounded-xl text-sm bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400">
            <span>{actionError}</span>
            <button
              onClick={() => setActionError(null)}
              aria-label="Dismiss error"
            >
              <X size={16} />
            </button>
          </div>
        )}

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

        {/* Header */}
        <div className="flex justify-between items-start">
          <div>
            <h2 className="text-3xl font-bold text-gray-900 dark:text-white">
              {assessment.title}
            </h2>
            <span
              className={`mt-3 inline-block px-4 py-2 rounded-full text-sm font-medium ${assessmentStatusBadgeClass(
                assessment.status
              )}`}
            >
              {ASSESSMENT_STATUS_LABELS[assessment.status]}
            </span>
          </div>

          {!isEditing && (
            <div className="flex gap-3">
              <button
                onClick={startEdit}
                className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm flex items-center gap-2 transition"
              >
                <Pencil size={16} />
                Edit
              </button>

              <button
                onClick={() => setShowDeleteModal(true)}
                className="
                  bg-red-100 text-red-700 hover:bg-red-200
                  dark:bg-red-600/20 dark:text-red-400
                  dark:hover:bg-red-600/30
                  px-4 py-2 rounded-lg text-sm flex items-center gap-2 transition
                "
              >
                <Trash2 size={16} />
                Delete
              </button>
            </div>
          )}
        </div>

        {/* Details / Edit Form */}
        {isEditing ? (
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl p-8 shadow-sm space-y-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Edit Assessment
            </h3>

            <AssessmentFormFields form={form} onChange={setForm} />

            {formError && (
              <p className="text-sm text-red-600 dark:text-red-400">
                {formError}
              </p>
            )}

            <div className="flex gap-3 pt-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="bg-indigo-600 hover:bg-indigo-700 text-white px-6 py-3 rounded-xl font-medium transition disabled:opacity-60"
              >
                {saving ? "Saving..." : "Save Changes"}
              </button>
              <button
                onClick={cancelEdit}
                disabled={saving}
                className="
                  px-6 py-3 rounded-xl border
                  border-gray-300 dark:border-gray-700
                  text-gray-600 dark:text-gray-400
                  hover:bg-gray-50 dark:hover:bg-gray-800
                  transition disabled:opacity-60
                "
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div
            className="
              bg-white dark:bg-gray-900
              border border-gray-200 dark:border-gray-800
              rounded-2xl p-8 shadow-sm
            "
          >
            <div className="grid md:grid-cols-2 gap-6 text-sm">
              <Info
                label="Duration"
                value={
                  assessment.duration_minutes != null
                    ? `${assessment.duration_minutes} minutes`
                    : "Not set"
                }
              />
              <Info
                label="Starts At"
                value={formatDateTime(assessment.starts_at)}
              />
              <Info
                label="Ends At"
                value={formatDateTime(assessment.ends_at)}
              />
              <Info
                label="Candidates Assigned"
                value={String(assessment.assignments.length)}
              />
              <Info
                label="Created On"
                value={formatDateTime(assessment.created_at)}
              />
              <Info
                label="Last Updated"
                value={formatDateTime(assessment.updated_at)}
              />
            </div>

            <div className="mt-6">
              <p className="text-gray-500 dark:text-gray-400 text-sm mb-1">
                Description
              </p>
              <p className="text-gray-900 dark:text-white text-sm">
                {assessment.description || "No description provided."}
              </p>
            </div>

            <div className="mt-4">
              <p className="text-gray-500 dark:text-gray-400 text-sm mb-1">
                Instructions
              </p>
              <p className="text-gray-900 dark:text-white text-sm whitespace-pre-wrap">
                {assessment.instructions || "No instructions provided."}
              </p>
            </div>
          </div>
        )}

        {/* Sections */}
        <div
          className="
            bg-white dark:bg-gray-900
            border border-gray-200 dark:border-gray-800
            rounded-2xl overflow-hidden shadow-sm
          "
        >
          <div className="flex items-center justify-between p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Sections
            </h3>

            <button
              onClick={openAddSection}
              disabled={sectionBusy}
              className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-60"
            >
              <Plus size={16} />
              Add Section
            </button>
          </div>

          {assessment.sections.length === 0 ? (
            <p className="px-6 pb-6 text-gray-500 dark:text-gray-400 text-sm">
              No sections yet. Add your first section.
            </p>
          ) : (
            <ul>
              {assessment.sections.map((section, index) => (
                <li
                  key={section.id}
                  className="
                    flex items-center gap-4 px-6 py-4
                    border-t border-gray-200 dark:border-gray-800
                    hover:bg-gray-50 dark:hover:bg-gray-800/50 transition
                  "
                >
                  <span className="
                    w-8 h-8 shrink-0 rounded-full
                    bg-indigo-600/10 text-indigo-600 dark:text-indigo-400
                    flex items-center justify-center text-sm font-semibold
                  ">
                    {section.section_order}
                  </span>

                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-gray-900 dark:text-white">
                      {section.title}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {SECTION_TYPE_LABELS[section.section_type]}
                      {section.marks != null && ` • ${section.marks} marks`}
                    </p>
                  </div>

                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleMove(index, -1)}
                      disabled={sectionBusy || index === 0}
                      aria-label="Move section up"
                      className={iconButtonClass}
                    >
                      <ChevronUp size={16} />
                    </button>

                    <button
                      onClick={() => handleMove(index, 1)}
                      disabled={
                        sectionBusy ||
                        index === assessment.sections.length - 1
                      }
                      aria-label="Move section down"
                      className={iconButtonClass}
                    >
                      <ChevronDown size={16} />
                    </button>

                    <button
                      onClick={() => openEditSection(section)}
                      disabled={sectionBusy}
                      aria-label="Edit section"
                      className={iconButtonClass}
                    >
                      <Pencil size={16} />
                    </button>

                    <button
                      onClick={() => setSectionToDelete(section)}
                      disabled={sectionBusy}
                      aria-label="Delete section"
                      className={iconButtonClass}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Add / Edit Section Modal */}
        {sectionModal && (
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="
              bg-white dark:bg-gray-900
              w-full max-w-md
              rounded-2xl p-6
              border border-gray-200 dark:border-gray-800
              shadow-xl space-y-4
            ">
              <div className="flex justify-between items-center">
                <h3 className="text-gray-900 dark:text-white text-lg font-semibold">
                  {sectionModal.mode === "add"
                    ? "Add Section"
                    : "Edit Section"}
                </h3>
                <button
                  onClick={() => setSectionModal(null)}
                  aria-label="Close dialog"
                >
                  <X className="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white" />
                </button>
              </div>

              <div>
                <label className={labelClass}>Section Type</label>
                <select
                  value={sectionForm.section_type}
                  onChange={(e) =>
                    setSectionForm({
                      ...sectionForm,
                      section_type: e.target
                        .value as SectionFormState["section_type"],
                    })
                  }
                  className={inputClass}
                >
                  {SECTION_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {SECTION_TYPE_LABELS[type]}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className={labelClass}>Title *</label>
                <input
                  type="text"
                  value={sectionForm.title}
                  onChange={(e) =>
                    setSectionForm({ ...sectionForm, title: e.target.value })
                  }
                  placeholder="Section title"
                  className={inputClass}
                />
              </div>

              <div>
                <label className={labelClass}>Marks</label>
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={sectionForm.marks}
                  onChange={(e) =>
                    setSectionForm({ ...sectionForm, marks: e.target.value })
                  }
                  placeholder="e.g. 20"
                  className={inputClass}
                />
              </div>

              <button
                onClick={handleSectionSubmit}
                disabled={sectionBusy}
                className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-3 rounded-xl font-medium transition disabled:opacity-60"
              >
                {sectionBusy
                  ? "Saving..."
                  : sectionModal.mode === "add"
                    ? "Add Section"
                    : "Save Section"}
              </button>

              {sectionError && (
                <p className="text-sm text-red-600 dark:text-red-400 text-center">
                  {sectionError}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Delete Assessment Modal */}
        {showDeleteModal && (
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="
              bg-white dark:bg-gray-900
              border border-gray-200 dark:border-gray-800
              p-6 rounded-2xl w-full max-w-sm shadow-xl
            ">
              <h3 className="text-gray-900 dark:text-white text-lg font-semibold">
                Delete Assessment?
              </h3>

              <p className="text-gray-600 dark:text-gray-400 text-sm mt-2">
                This will permanently delete “{assessment.title}” along with
                its sections and assignments. This action cannot be undone.
              </p>

              <div className="flex justify-end gap-3 mt-6">
                <button
                  onClick={() => setShowDeleteModal(false)}
                  className="
                    px-4 py-2 rounded-lg
                    bg-gray-100 text-gray-700
                    hover:bg-gray-200
                    dark:bg-gray-800 dark:text-gray-300
                  "
                >
                  Cancel
                </button>

                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="px-4 py-2 rounded-lg bg-red-600 text-white hover:bg-red-700 disabled:opacity-60"
                >
                  {deleting ? "Deleting..." : "Confirm Delete"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Delete Section Modal */}
        {sectionToDelete && (
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="
              bg-white dark:bg-gray-900
              border border-gray-200 dark:border-gray-800
              p-6 rounded-2xl w-full max-w-sm shadow-xl
            ">
              <h3 className="text-gray-900 dark:text-white text-lg font-semibold">
                Delete Section?
              </h3>

              <p className="text-gray-600 dark:text-gray-400 text-sm mt-2">
                This will permanently delete “{sectionToDelete.title}”. This
                action cannot be undone.
              </p>

              <div className="flex justify-end gap-3 mt-6">
                <button
                  onClick={() => setSectionToDelete(null)}
                  className="
                    px-4 py-2 rounded-lg
                    bg-gray-100 text-gray-700
                    hover:bg-gray-200
                    dark:bg-gray-800 dark:text-gray-300
                  "
                >
                  Cancel
                </button>

                <button
                  onClick={handleSectionDelete}
                  disabled={sectionBusy}
                  className="px-4 py-2 rounded-lg bg-red-600 text-white hover:bg-red-700 disabled:opacity-60"
                >
                  {sectionBusy ? "Deleting..." : "Confirm Delete"}
                </button>
              </div>
            </div>
          </div>
        )}

      </div>
    </CompanyLayout>
  );
}

function Info({
  label,
  value,
}: {
  label: string;
  value: string;
}): JSX.Element {
  return (
    <div>
      <p className="text-gray-500 dark:text-gray-400">{label}</p>
      <p className="text-gray-900 dark:text-white font-medium mt-1">
        {value}
      </p>
    </div>
  );
}
