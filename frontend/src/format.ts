import type { Priority } from './types';

export const PRIORITY_LABEL: Record<Priority, string> = {
  P0: 'Critical', P1: 'High', P2: 'Medium', P3: 'Low', P4: 'Info',
};

export const shortDateTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '';

export const shortDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '';

export const timeOfDay = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) : '';

export function minutes(total: number) {
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

// Date-only strings ("2026-10-13") are parsed at noon so they never shift a day across timezones.
export const dayLabel = (isoDate: string) => {
  const d = new Date(`${isoDate}T12:00:00`);
  return {
    weekday: d.toLocaleDateString(undefined, { weekday: 'short' }),
    date: d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    isToday: d.toDateString() === new Date().toDateString(),
  };
};
