import { useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import {
  AssessmentQuestion,
  CodingQuestionFormState,
  McqQuestionFormState,
  QuestionPayload,
  QuestionTestCase,
  SUPPORTED_CODING_LANGUAGES,
  CODING_DIFFICULTIES,
  codingFormToPayload,
  createQuestion,
  deleteQuestion,
  emptyCodingQuestionForm,
  emptyMcqQuestionForm,
  listQuestions,
  mcqFormToPayload,
  questionToCodingForm,
  questionToMcqForm,
  reorderQuestions,
  sectionQuestionType,
  updateQuestion,
  validateCodingForm,
  validateMcqForm,
} from "../../lib/questions";
import { AssessmentSection, SECTION_TYPE_LABELS } from "../../lib/assessments";

interface SectionQuestionsProps {
  assessmentId: number;
  section: AssessmentSection;
}

const boxClass = `
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

interface TestCaseEditorProps {
  label: string;
  hint?: string;
  cases: QuestionTestCase[];
  onChange: (next: QuestionTestCase[]) => void;
}

function TestCaseEditor({ label, hint, cases, onChange }: TestCaseEditorProps) {
  const updateCase = (
    index: number,
    patch: Partial<QuestionTestCase>
  ): void => {
    const next = cases.map((c, i) => (i === index ? { ...c, ...patch } : c));
    onChange(next);
  };

  const removeCase = (index: number): void => {
    onChange(cases.filter((_, i) => i !== index));
  };

  const addCase = (): void => {
    onChange([...cases, { input: "", expected: "" }]);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {label}
        </label>
        <button
          onClick={addCase}
          className="text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          + Add case
        </button>
      </div>

      {hint && (
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">{hint}</p>
      )}

      <div className="space-y-2">
        {cases.length === 0 ? (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            No test cases yet.
          </p>
        ) : (
          cases.map((c, i) => (
            <div
              key={i}
              className="space-y-2 rounded-xl border border-gray-200 dark:border-gray-700 p-3 bg-white dark:bg-gray-800"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  Case {i + 1}
                </span>
                <button
                  onClick={() => removeCase(i)}
                  aria-label={`Remove ${label} case ${i + 1}`}
                  className="text-gray-400 hover:text-red-500 transition"
                >
                  <X size={14} />
                </button>
              </div>

              <textarea
                rows={2}
                placeholder="Input"
                value={c.input}
                onChange={(e) => updateCase(i, { input: e.target.value })}
                className={boxClass}
              />

              <textarea
                rows={2}
                placeholder="Expected output"
                value={c.expected}
                onChange={(e) => updateCase(i, { expected: e.target.value })}
                className={boxClass}
              />
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function SectionQuestions({
  assessmentId,
  section,
}: SectionQuestionsProps) {
  const qType = sectionQuestionType(section.section_type);

  const [questions, setQuestions] = useState<AssessmentQuestion[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<boolean>(false);

  const [modal, setModal] = useState<{
    mode: "add" | "edit";
    question: AssessmentQuestion | null;
  } | null>(null);
  const [mcqForm, setMcqForm] = useState<McqQuestionFormState>(
    emptyMcqQuestionForm()
  );
  const [codingForm, setCodingForm] = useState<CodingQuestionFormState>(
    emptyCodingQuestionForm()
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);

  const [questionToDelete, setQuestionToDelete] =
    useState<AssessmentQuestion | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const loadQuestions = useCallback(async (): Promise<void> => {
    try {
      const data = await listQuestions(assessmentId, section.id);
      setQuestions(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load questions");
    } finally {
      setLoading(false);
    }
  }, [assessmentId, section.id]);

  useEffect(() => {
    if (qType) {
      loadQuestions();
    }
  }, [qType, loadQuestions]);

  const openAdd = (): void => {
    setMcqForm(emptyMcqQuestionForm());
    setCodingForm(emptyCodingQuestionForm());
    setFormError(null);
    setModal({ mode: "add", question: null });
  };

  const openEdit = (question: AssessmentQuestion): void => {
    setMcqForm(qType === "mcq" ? questionToMcqForm(question) : emptyMcqQuestionForm());
    setCodingForm(
      qType === "coding" ? questionToCodingForm(question) : emptyCodingQuestionForm()
    );
    setFormError(null);
    setModal({ mode: "edit", question });
  };

  const updateOption = (index: number, value: string): void => {
    const options = mcqForm.options.map((option, i) =>
      i === index ? value : option
    );
    setMcqForm({ ...mcqForm, options });
  };

  const addOption = (): void => {
    setMcqForm({ ...mcqForm, options: [...mcqForm.options, ""] });
  };

  const removeOption = (index: number): void => {
    const options = mcqForm.options.filter((_, i) => i !== index);
    let correctIndex = mcqForm.correctIndex;
    if (correctIndex === index) {
      correctIndex = null;
    } else if (correctIndex !== null && correctIndex > index) {
      correctIndex -= 1;
    }
    if (correctIndex !== null && correctIndex >= options.length) {
      correctIndex = null;
    }
    setMcqForm({ ...mcqForm, options, correctIndex });
  };

  const toggleLanguage = (lang: string): void => {
    const supported = codingForm.supported_languages.includes(lang)
      ? codingForm.supported_languages.filter((l) => l !== lang)
      : [...codingForm.supported_languages, lang];
    setCodingForm({ ...codingForm, supported_languages: supported });
  };

  const handleSubmit = async (): Promise<void> => {
    if (!modal) return;

    let validationError: string | null;
    let payload: QuestionPayload;

    if (qType === "mcq") {
      validationError = validateMcqForm(mcqForm);
      payload = mcqFormToPayload(mcqForm);
    } else {
      validationError = validateCodingForm(codingForm);
      payload = codingFormToPayload(codingForm);
    }

    if (validationError) {
      setFormError(validationError);
      return;
    }

    setSubmitting(true);
    setFormError(null);
    setSuccessMessage(null);
    try {
      if (modal.mode === "add") {
        await createQuestion(assessmentId, section.id, payload);
      } else if (modal.question) {
        await updateQuestion(
          assessmentId,
          section.id,
          modal.question.id,
          payload
        );
      }
      setModal(null);
      setSuccessMessage(
        modal.mode === "add"
          ? "Question added successfully."
          : "Question updated successfully."
      );
      await loadQuestions();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Failed to save question");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (): Promise<void> => {
    if (!questionToDelete) return;
    setBusy(true);
    setSuccessMessage(null);
    try {
      await deleteQuestion(assessmentId, section.id, questionToDelete.id);
      setQuestionToDelete(null);
      setSuccessMessage("Question deleted successfully.");
      await loadQuestions();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete question");
      setQuestionToDelete(null);
    } finally {
      setBusy(false);
    }
  };

  const handleMove = async (
    index: number,
    direction: -1 | 1
  ): Promise<void> => {
    const target = index + direction;
    if (target < 0 || target >= questions.length) return;

    const ids = questions.map((q) => q.id);
    const moved = ids[index];
    ids[index] = ids[target];
    ids[target] = moved;

    setBusy(true);
    setSuccessMessage(null);
    try {
      await reorderQuestions(assessmentId, section.id, ids);
      setSuccessMessage("Questions reordered successfully.");
      await loadQuestions();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reorder questions");
    } finally {
      setBusy(false);
    }
  };

  if (!qType) {
    return (
      <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-4 text-sm text-gray-500 dark:text-gray-400">
        Question bank entries are not supported for{" "}
        {SECTION_TYPE_LABELS[section.section_type]} sections yet. This section
        type is handled separately and will be configured later.
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm font-semibold text-gray-900 dark:text-white">
          Question Bank
          {!loading && !error && questions.length > 0 && (
            <span className="ml-2 text-xs font-normal text-gray-500 dark:text-gray-400">
              {questions.length} {questions.length === 1 ? "question" : "questions"}
            </span>
          )}
        </p>

        <button
          onClick={openAdd}
          disabled={busy}
          className="flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-2 rounded-lg text-sm font-medium transition disabled:opacity-60"
        >
          <Plus size={14} />
          Add Question
        </button>
      </div>

      {successMessage && (
        <div className="mb-4 flex items-center justify-between p-3 rounded-xl text-xs bg-green-500/10 border border-green-500/20 text-green-600 dark:text-green-400">
          <span>{successMessage}</span>
          <button
            onClick={() => setSuccessMessage(null)}
            aria-label="Dismiss message"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 rounded-xl text-xs bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {loading && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Loading questions...
        </p>
      )}

      {!loading && !error && questions.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          No questions in this section yet. Add your first question.
        </p>
      )}

      {!loading && !error && questions.length > 0 && (
        <div className="space-y-2">
          {questions.map((question, index) => (
            <div
              key={question.id}
              className="flex items-center gap-3 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-4 py-3"
            >
              <span className="
                w-7 h-7 shrink-0 rounded-full
                bg-indigo-600/10 text-indigo-600 dark:text-indigo-400
                flex items-center justify-center text-xs font-semibold
              ">
                {question.question_order}
              </span>

              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white line-clamp-1">
                  {question.question_text}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {question.question_type === "mcq"
                    ? `${question.options?.length ?? 0} options`
                    : "Coding"}
                  {question.marks != null && ` • ${question.marks} marks`}
                </p>
              </div>

              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleMove(index, -1)}
                  disabled={busy || index === 0}
                  aria-label="Move question up"
                  className={iconButtonClass}
                >
                  <ChevronUp size={16} />
                </button>

                <button
                  onClick={() => handleMove(index, 1)}
                  disabled={busy || index === questions.length - 1}
                  aria-label="Move question down"
                  className={iconButtonClass}
                >
                  <ChevronDown size={16} />
                </button>

                <button
                  onClick={() => openEdit(question)}
                  disabled={busy}
                  aria-label="Edit question"
                  className={iconButtonClass}
                >
                  <Pencil size={16} />
                </button>

                <button
                  onClick={() => setQuestionToDelete(question)}
                  disabled={busy}
                  aria-label="Delete question"
                  className={iconButtonClass}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add / Edit Question Modal */}
      {modal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="
            bg-white dark:bg-gray-900
            w-full max-h-[90vh] overflow-y-auto
            rounded-2xl p-6
            border border-gray-200 dark:border-gray-800
            shadow-xl space-y-4
          "
            style={{ maxWidth: qType === "coding" ? "48rem" : "40rem" }}
          >
            <div className="flex justify-between items-center">
              <h3 className="text-gray-900 dark:text-white text-lg font-semibold">
                {modal.mode === "add" ? "Add Question" : "Edit Question"}
              </h3>
              <button onClick={() => setModal(null)} aria-label="Close dialog">
                <X className="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white" />
              </button>
            </div>

            {qType === "mcq" ? (
              <>
                <div>
                  <label className={labelClass}>Question Text *</label>
                  <textarea
                    rows={3}
                    value={mcqForm.question_text}
                    onChange={(e) =>
                      setMcqForm({ ...mcqForm, question_text: e.target.value })
                    }
                    placeholder="Question text"
                    className={boxClass}
                  />
                </div>

                <div>
                  <label className={labelClass}>Options *</label>
                  <div className="space-y-2">
                    {mcqForm.options.map((option, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <input
                          type="radio"
                          name="correct-option"
                          checked={mcqForm.correctIndex === i}
                          onChange={() =>
                            setMcqForm({ ...mcqForm, correctIndex: i })
                          }
                          aria-label={`Select option ${i + 1} as the correct answer`}
                          className="accent-indigo-600 h-4 w-4 shrink-0"
                        />
                        <input
                          type="text"
                          value={option}
                          onChange={(e) => updateOption(i, e.target.value)}
                          placeholder={`Option ${i + 1}`}
                          className={boxClass}
                        />
                        {mcqForm.correctIndex === i && (
                          <span className="shrink-0 text-xs font-medium text-green-600 dark:text-green-400">
                            Correct
                          </span>
                        )}
                        <button
                          onClick={() => removeOption(i)}
                          disabled={mcqForm.options.length <= 2}
                          aria-label={`Remove option ${i + 1}`}
                          className="shrink-0 text-gray-400 hover:text-red-500 transition disabled:opacity-40"
                        >
                          <X size={16} />
                        </button>
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={addOption}
                    className="mt-2 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
                  >
                    + Add option
                  </button>
                </div>
              </>
            ) : (
              <>
                <div>
                  <label className={labelClass}>Question Text *</label>
                  <textarea
                    rows={3}
                    value={codingForm.question_text}
                    onChange={(e) =>
                      setCodingForm({
                        ...codingForm,
                        question_text: e.target.value,
                      })
                    }
                    placeholder="Problem statement for the candidate"
                    className={boxClass}
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div>
                    <label className={labelClass}>Title</label>
                    <input
                      type="text"
                      value={codingForm.title}
                      onChange={(e) =>
                        setCodingForm({
                          ...codingForm,
                          title: e.target.value,
                        })
                      }
                      placeholder="e.g. Two Sum"
                      className={boxClass}
                    />
                  </div>

                  <div>
                    <label className={labelClass}>Category</label>
                    <input
                      type="text"
                      value={codingForm.category}
                      onChange={(e) =>
                        setCodingForm({
                          ...codingForm,
                          category: e.target.value,
                        })
                      }
                      placeholder="e.g. arrays"
                      className={boxClass}
                    />
                  </div>

                  <div>
                    <label className={labelClass}>Difficulty</label>
                    <select
                      value={codingForm.difficulty}
                      onChange={(e) =>
                        setCodingForm({
                          ...codingForm,
                          difficulty: e.target.value,
                        })
                      }
                      className={boxClass}
                    >
                      {CODING_DIFFICULTIES.map((difficulty) => (
                        <option key={difficulty} value={difficulty}>
                          {difficulty}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <label className={labelClass}>Input Format</label>
                  <textarea
                    rows={2}
                    value={codingForm.input_format}
                    onChange={(e) =>
                      setCodingForm({
                        ...codingForm,
                        input_format: e.target.value,
                      })
                    }
                    placeholder="Describe the input format"
                    className={boxClass}
                  />
                </div>

                <div>
                  <label className={labelClass}>Output Format</label>
                  <textarea
                    rows={2}
                    value={codingForm.output_format}
                    onChange={(e) =>
                      setCodingForm({
                        ...codingForm,
                        output_format: e.target.value,
                      })
                    }
                    placeholder="Describe the expected output format"
                    className={boxClass}
                  />
                </div>

                <div>
                  <label className={labelClass}>Constraints</label>
                  <textarea
                    rows={2}
                    value={codingForm.constraints}
                    onChange={(e) =>
                      setCodingForm({
                        ...codingForm,
                        constraints: e.target.value,
                      })
                    }
                    placeholder="Constraints (e.g. 1 ≤ N ≤ 100000)"
                    className={boxClass}
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className={labelClass}>
                      Time Limit (seconds per case) *
                    </label>
                    <input
                      type="number"
                      min={1}
                      step={1}
                      value={codingForm.time_limit_seconds}
                      onChange={(e) =>
                        setCodingForm({
                          ...codingForm,
                          time_limit_seconds: e.target.value,
                        })
                      }
                      className={boxClass}
                    />
                  </div>

                  <div>
                    <label className={labelClass}>Supported Languages *</label>
                    <div className="flex flex-wrap gap-2">
                      {SUPPORTED_CODING_LANGUAGES.map((lang) => (
                        <label
                          key={lang}
                          className="
                            flex items-center gap-2 px-3 py-2 rounded-lg text-sm
                            border border-gray-300 dark:border-gray-700
                            bg-white text-gray-700
                            dark:bg-gray-800 dark:text-gray-300
                            cursor-pointer select-none
                          "
                        >
                          <input
                            type="checkbox"
                            checked={codingForm.supported_languages.includes(lang)}
                            onChange={() => toggleLanguage(lang)}
                            className="accent-indigo-600"
                          />
                          {lang}
                        </label>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <TestCaseEditor
                    label="Sample Test Cases"
                    hint="Shown to candidates."
                    cases={codingForm.sample_cases}
                    onChange={(next) =>
                      setCodingForm({ ...codingForm, sample_cases: next })
                    }
                  />

                  <TestCaseEditor
                    label="Hidden Test Cases"
                    hint="Used for scoring; never shown to candidates."
                    cases={codingForm.hidden_cases}
                    onChange={(next) =>
                      setCodingForm({ ...codingForm, hidden_cases: next })
                    }
                  />
                </div>
              </>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Marks</label>
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={qType === "mcq" ? mcqForm.marks : codingForm.marks}
                  onChange={(e) =>
                    qType === "mcq"
                      ? setMcqForm({ ...mcqForm, marks: e.target.value })
                      : setCodingForm({ ...codingForm, marks: e.target.value })
                  }
                  placeholder="e.g. 5"
                  className={boxClass}
                />
              </div>

              <div>
                <label className={labelClass}>Explanation</label>
                <input
                  type="text"
                  value={
                    qType === "mcq"
                      ? mcqForm.explanation
                      : codingForm.explanation
                  }
                  onChange={(e) =>
                    qType === "mcq"
                      ? setMcqForm({
                          ...mcqForm,
                          explanation: e.target.value,
                        })
                      : setCodingForm({
                          ...codingForm,
                          explanation: e.target.value,
                        })
                  }
                  placeholder="Shown after the answer"
                  className={boxClass}
                />
              </div>
            </div>

            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-3 rounded-xl font-medium transition disabled:opacity-60"
            >
              {submitting
                ? "Saving..."
                : modal.mode === "add"
                  ? "Add Question"
                  : "Save Question"}
            </button>

            {formError && (
              <p className="text-sm text-red-600 dark:text-red-400 text-center">
                {formError}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Delete Question Modal */}
      {questionToDelete && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="
            bg-white dark:bg-gray-900
            border border-gray-200 dark:border-gray-800
            p-6 rounded-2xl w-full max-w-sm shadow-xl
          ">
            <h3 className="text-gray-900 dark:text-white text-lg font-semibold">
              Delete Question?
            </h3>

            <p className="text-gray-600 dark:text-gray-400 text-sm mt-2">
              This will permanently delete this question from the section.
              This action cannot be undone.
            </p>

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setQuestionToDelete(null)}
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
                disabled={busy}
                className="px-4 py-2 rounded-lg bg-red-600 text-white hover:bg-red-700 disabled:opacity-60"
              >
                {busy ? "Deleting..." : "Confirm Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}