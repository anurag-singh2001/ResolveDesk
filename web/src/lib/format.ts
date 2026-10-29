// Display helpers only: labels and dates. No business rules here.

export function humanize(slug: string | null | undefined): string {
  if (!slug) return "n/a";
  const s = slug.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function categoryLabel(slug: string | null | undefined): string {
  return slug ? humanize(slug) : "Not categorised yet";
}

const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "n/a" : dateTimeFmt.format(d);
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "n/a" : timeFmt.format(d);
}

/** "5 min", "3 h", "2 d" since `iso`. */
export function age(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "n/a";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "n/a";
  const mins = Math.max(0, Math.floor((now - t) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h`;
  return `${Math.floor(hours / 24)} d`;
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "n/a";
}
