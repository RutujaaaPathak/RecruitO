import {
  AssessmentFormState,
  AssessmentStatus,
  ASSESSMENT_STATUSES,
  ASSESSMENT_STATUS_LABELS,
} from "../../lib/assessments";

interface AssessmentFormFieldsProps {
  form: AssessmentFormState;
  onChange: (next: AssessmentFormState) => void;
}

const fieldClass = `
  w-full p-3 rounded-xl border
  bg-white text-gray-900
  dark:bg-gray-800 dark:text-white
  border-gray-300 dark:border-gray-700
  outline-none focus:ring-2 focus:ring-indigo-500
`;

const labelClass =
  "block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1";

export default function AssessmentFormFields({
  form,
  onChange,
}: AssessmentFormFieldsProps) {
  const update = <K extends keyof AssessmentFormState>(
    key: K,
    value: AssessmentFormState[K]
  ): void => {
    onChange({ ...form, [key]: value });
  };

  return (
    <>
      <div>
        <label className={labelClass}>Title *</label>
        <input
          type="text"
          value={form.title}
          onChange={(e) => update("title", e.target.value)}
          placeholder="Assessment title"
          className={fieldClass}
        />
      </div>

      <div>
        <label className={labelClass}>Description</label>
        <textarea
          rows={3}
          value={form.description}
          onChange={(e) => update("description", e.target.value)}
          placeholder="What this assessment covers"
          className={fieldClass}
        />
      </div>

      <div>
        <label className={labelClass}>Instructions</label>
        <textarea
          rows={3}
          value={form.instructions}
          onChange={(e) => update("instructions", e.target.value)}
          placeholder="Instructions shown to candidates taking this assessment"
          className={fieldClass}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>Status</label>
          <select
            value={form.status}
            onChange={(e) =>
              update("status", e.target.value as AssessmentStatus)
            }
            className={fieldClass}
          >
            {ASSESSMENT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {ASSESSMENT_STATUS_LABELS[status]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelClass}>Duration (minutes)</label>
          <input
            type="number"
            min={1}
            step={1}
            value={form.duration}
            onChange={(e) => update("duration", e.target.value)}
            placeholder="e.g. 60"
            className={fieldClass}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>Start date &amp; time</label>
          <input
            type="datetime-local"
            value={form.startsAt}
            onChange={(e) => update("startsAt", e.target.value)}
            className={fieldClass}
          />
        </div>

        <div>
          <label className={labelClass}>End date &amp; time</label>
          <input
            type="datetime-local"
            value={form.endsAt}
            onChange={(e) => update("endsAt", e.target.value)}
            className={fieldClass}
          />
        </div>
      </div>
    </>
  );
}
