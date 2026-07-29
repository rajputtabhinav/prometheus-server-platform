import { formatDistanceToNowStrict, parseISO } from "date-fns";

function toDate(value: string) {
  const parsed = parseISO(value);
  return Number.isNaN(parsed.getTime()) ? new Date(value) : parsed;
}

export const PLATFORM_TIMEZONE = import.meta.env.VITE_APP_TIMEZONE ?? "Asia/Kolkata";
const PLATFORM_LOCALE = "en-IN";

function formatInTimezone(value: Date, options: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat(PLATFORM_LOCALE, {
    timeZone: PLATFORM_TIMEZONE,
    ...options,
  }).format(value);
}

export function formatCalendarDate(value: string) {
  return formatInTimezone(toDate(value), {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function formatClockTime(value: string) {
  return formatInTimezone(toDate(value), {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

export function formatDateTime(value: string) {
  return formatInTimezone(toDate(value), {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

export function formatEventTime(value: string) {
  return `${formatClockTime(value)} | ${formatDistanceToNowStrict(toDate(value), { addSuffix: true })}`;
}

export function formatNow(value: Date) {
  return formatInTimezone(value, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}
