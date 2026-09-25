/**
 * The API serializes datetimes as naive UTC ("2026-03-10T09:30:00", no offset),
 * but `new Date("2026-03-10T09:30:00")` reads an offset-less date-time as *local*
 * time. That shifts every server value by the viewer's UTC offset: assessment
 * windows, the attempt countdown and `datetime-local` inputs all disagree with
 * the server by hours. These helpers read backend timestamps as the UTC instants
 * they are; formatting into the viewer's zone stays the caller's choice.
 */

const HAS_UTC_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/;

export type ApiDate = string | number | Date | null | undefined;

/** Parse a backend timestamp as UTC. Returns null for missing/invalid values. */
export function parseApiDate(value: ApiDate): Date | null {
  if (value === null || value === undefined || value === "") return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === "number") {
    const fromEpoch = new Date(value);
    return Number.isNaN(fromEpoch.getTime()) ? null : fromEpoch;
  }
  const raw = value.trim();
  const parsed = new Date(HAS_UTC_OFFSET.test(raw) ? raw : `${raw}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** Epoch milliseconds of a backend timestamp, or null when unusable. */
export function apiTime(value: ApiDate): number | null {
  return parseApiDate(value)?.getTime() ?? null;
}

/** Local `datetime-local` input value ("2026-03-10T15:30") for a backend timestamp. */
export function toDateTimeLocalInput(value: ApiDate): string {
  const date = parseApiDate(value);
  if (!date) return "";
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate()
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
