import { api } from "./api";

export type AssessmentQuestionType = "mcq" | "coding";

export const SUPPORTED_CODING_LANGUAGES: string[] = ["python", "java", "cpp"];
export const CODING_DIFFICULTIES: string[] = ["easy", "medium", "hard"];
export const DEFAULT_CODING_TIME_LIMIT_SECONDS = 5;

export interface QuestionTestCase {
  input: string;
  expected: string;
}

export interface AssessmentQuestion {
  id: number;
  section_id: number;
  question_type: AssessmentQuestionType;
  question_text: string;
  question_order: number;
  options: string[] | null;
  correct_index: number | null;
  marks: number | null;
  explanation: string | null;
  title: string | null;
  category: string | null;
  difficulty: string | null;
  input_format: string | null;
  output_format: string | null;
  constraints: string | null;
  sample_cases: QuestionTestCase[] | null;
  hidden_cases: QuestionTestCase[] | null;
  time_limit_seconds: number | null;
  supported_languages: string[] | null;
  created_at: string;
  updated_at: string;
}

export type McqQuestionPayload = {
  question_type: "mcq";
  question_text: string;
  options: string[];
  correct_index: number;
  marks: number | null;
  explanation: string | null;
};

export type CodingQuestionPayload = {
  question_type: "coding";
  question_text: string;
  title: string | null;
  category: string | null;
  difficulty: string | null;
  input_format: string | null;
  output_format: string | null;
  constraints: string | null;
  sample_cases: QuestionTestCase[] | null;
  hidden_cases: QuestionTestCase[];
  time_limit_seconds: number;
  supported_languages: string[];
  marks: number | null;
  explanation: string | null;
};

export type QuestionPayload = McqQuestionPayload | CodingQuestionPayload;

export interface McqQuestionFormState {
  question_text: string;
  options: string[];
  correctIndex: number | null;
  marks: string;
  explanation: string;
}

export interface CodingQuestionFormState {
  question_text: string;
  title: string;
  category: string;
  difficulty: string;
  input_format: string;
  output_format: string;
  constraints: string;
  sample_cases: QuestionTestCase[];
  hidden_cases: QuestionTestCase[];
  time_limit_seconds: string;
  supported_languages: string[];
  marks: string;
  explanation: string;
}

export function sectionQuestionType(
  sectionType: string
): AssessmentQuestionType | null {
  if (sectionType === "coding") return "coding";
  if (sectionType === "aptitude" || sectionType === "technical") return "mcq";
  return null;
}

export function emptyMcqQuestionForm(): McqQuestionFormState {
  return {
    question_text: "",
    options: ["", ""],
    correctIndex: null,
    marks: "",
    explanation: "",
  };
}

export function emptyCodingQuestionForm(): CodingQuestionFormState {
  return {
    question_text: "",
    title: "",
    category: "",
    difficulty: "easy",
    input_format: "",
    output_format: "",
    constraints: "",
    sample_cases: [],
    hidden_cases: [],
    time_limit_seconds: String(DEFAULT_CODING_TIME_LIMIT_SECONDS),
    supported_languages: [...SUPPORTED_CODING_LANGUAGES],
    marks: "",
    explanation: "",
  };
}

export function questionToMcqForm(
  question: AssessmentQuestion
): McqQuestionFormState {
  return {
    question_text: question.question_text,
    options: question.options ? [...question.options] : [],
    correctIndex: question.correct_index,
    marks: question.marks != null ? String(question.marks) : "",
    explanation: question.explanation ?? "",
  };
}

export function questionToCodingForm(
  question: AssessmentQuestion
): CodingQuestionFormState {
  return {
    question_text: question.question_text,
    title: question.title ?? "",
    category: question.category ?? "",
    difficulty: question.difficulty || "easy",
    input_format: question.input_format ?? "",
    output_format: question.output_format ?? "",
    constraints: question.constraints ?? "",
    sample_cases: question.sample_cases
      ? question.sample_cases.map((c) => ({ ...c }))
      : [],
    hidden_cases: question.hidden_cases
      ? question.hidden_cases.map((c) => ({ ...c }))
      : [],
    time_limit_seconds:
      question.time_limit_seconds != null
        ? String(question.time_limit_seconds)
        : String(DEFAULT_CODING_TIME_LIMIT_SECONDS),
    supported_languages:
      question.supported_languages && question.supported_languages.length > 0
        ? [...question.supported_languages]
        : [...SUPPORTED_CODING_LANGUAGES],
    marks: question.marks != null ? String(question.marks) : "",
    explanation: question.explanation ?? "",
  };
}

function validateOptionalMarks(raw: string): string | null {
  if (!raw.trim()) return null;
  const marks = Number(raw.trim());
  if (!Number.isInteger(marks) || marks < 0) {
    return "Marks must be a whole number of 0 or more.";
  }
  return null;
}

export function validateMcqForm(form: McqQuestionFormState): string | null {
  if (!form.question_text.trim()) {
    return "Question text is required.";
  }
  const options = form.options.map((option) => option.trim());
  if (options.length < 2) {
    return "At least two options are required.";
  }
  if (options.some((option) => option === "")) {
    return "Options cannot be empty.";
  }
  if (form.correctIndex === null) {
    return "Select the correct answer.";
  }
  if (form.correctIndex < 0 || form.correctIndex >= options.length) {
    return "The correct answer must point to one of the options.";
  }
  return validateOptionalMarks(form.marks);
}

export function validateCodingForm(
  form: CodingQuestionFormState
): string | null {
  if (!form.question_text.trim()) {
    return "Question text is required.";
  }

  const hiddenFilled = form.hidden_cases.filter(
    (c) => c.input.trim() || c.expected.trim()
  );
  if (hiddenFilled.length === 0) {
    return "At least one hidden test case is required.";
  }
  if (hiddenFilled.some((c) => !c.input.trim() || !c.expected.trim())) {
    return "Every hidden test case must have both an input and an expected output.";
  }

  const sampleIncomplete = form.sample_cases.some(
    (c) =>
      (c.input.trim() || c.expected.trim()) &&
      (!c.input.trim() || !c.expected.trim())
  );
  if (sampleIncomplete) {
    return "Every sample test case must have both an input and an expected output.";
  }

  if (form.time_limit_seconds.trim()) {
    const seconds = Number(form.time_limit_seconds.trim());
    if (!Number.isInteger(seconds) || seconds < 1) {
      return "Time limit must be a whole number of seconds (at least 1).";
    }
  }

  if (form.supported_languages.length === 0) {
    return "Select at least one supported language.";
  }

  return validateOptionalMarks(form.marks);
}

function parseOptionalMarks(raw: string): number | null {
  return raw.trim() ? Number(raw.trim()) : null;
}

export function mcqFormToPayload(
  form: McqQuestionFormState
): McqQuestionPayload {
  const correctIndex = form.correctIndex;
  if (correctIndex === null) {
    throw new Error("Correct answer is required");
  }
  return {
    question_type: "mcq",
    question_text: form.question_text.trim(),
    options: form.options.map((option) => option.trim()),
    correct_index: correctIndex,
    marks: parseOptionalMarks(form.marks),
    explanation: form.explanation.trim() || null,
  };
}

export function codingFormToPayload(
  form: CodingQuestionFormState
): CodingQuestionPayload {
  const sampleCases = form.sample_cases
    .filter((c) => c.input.trim() || c.expected.trim())
    .map((c) => ({ input: c.input.trim(), expected: c.expected.trim() }));

  return {
    question_type: "coding",
    question_text: form.question_text.trim(),
    title: form.title.trim() || null,
    category: form.category.trim() || null,
    difficulty: form.difficulty || null,
    input_format: form.input_format.trim() || null,
    output_format: form.output_format.trim() || null,
    constraints: form.constraints.trim() || null,
    sample_cases: sampleCases.length > 0 ? sampleCases : null,
    hidden_cases: form.hidden_cases
      .filter((c) => c.input.trim() || c.expected.trim())
      .map((c) => ({ input: c.input.trim(), expected: c.expected.trim() })),
    time_limit_seconds: form.time_limit_seconds.trim()
      ? Number(form.time_limit_seconds.trim())
      : DEFAULT_CODING_TIME_LIMIT_SECONDS,
    supported_languages: form.supported_languages,
    marks: parseOptionalMarks(form.marks),
    explanation: form.explanation.trim() || null,
  };
}

export function listQuestions(
  assessmentId: number,
  sectionId: number
): Promise<AssessmentQuestion[]> {
  return api.get<AssessmentQuestion[]>(
    `/assessments/${assessmentId}/sections/${sectionId}/questions`
  );
}

export function createQuestion(
  assessmentId: number,
  sectionId: number,
  payload: QuestionPayload
): Promise<AssessmentQuestion> {
  return api.post<AssessmentQuestion>(
    `/assessments/${assessmentId}/sections/${sectionId}/questions`,
    payload
  );
}

export function updateQuestion(
  assessmentId: number,
  sectionId: number,
  questionId: number,
  payload: QuestionPayload
): Promise<AssessmentQuestion> {
  return api.put<AssessmentQuestion>(
    `/assessments/${assessmentId}/sections/${sectionId}/questions/${questionId}`,
    payload
  );
}

export function deleteQuestion(
  assessmentId: number,
  sectionId: number,
  questionId: number
): Promise<void> {
  return api.del<void>(
    `/assessments/${assessmentId}/sections/${sectionId}/questions/${questionId}`
  );
}

export function reorderQuestions(
  assessmentId: number,
  sectionId: number,
  orderedQuestionIds: number[]
): Promise<AssessmentQuestion[]> {
  return api.put<AssessmentQuestion[]>(
    `/assessments/${assessmentId}/sections/${sectionId}/questions/reorder`,
    { ordered_question_ids: orderedQuestionIds }
  );
}