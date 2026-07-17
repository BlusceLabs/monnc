// Small display helpers shared across pages & components.

export function year(date?: string | null): string {
  if (!date) return '';
  return date.slice(0, 4);
}

export function prettyDate(date?: string | null): string {
  if (!date) return 'TBA';
  const d = new Date(date);
  if (Number.isNaN(d.getTime())) return date;
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
}

export function runtime(minutes?: number | null): string {
  if (!minutes) return '';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

export function money(value?: number | null): string {
  if (!value) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value);
}

export function percent(vote?: number | null): number {
  return Math.round((vote ?? 0) * 10);
}

export function compact(n?: number | null): string {
  if (!n) return '0';
  return new Intl.NumberFormat('en-US', { notation: 'compact' }).format(n);
}

// Normalise any TMDB list item to the shape our card component expects.
export function mediaTitle(item: any): string {
  return item?.title ?? item?.name ?? 'Untitled';
}

export function mediaDate(item: any): string {
  return item?.release_date ?? item?.first_air_date ?? '';
}

export function mediaType(item: any): 'movie' | 'tv' | 'person' {
  if (item?.media_type) return item.media_type;
  if (item?.first_air_date || item?.name) return 'tv';
  return 'movie';
}
