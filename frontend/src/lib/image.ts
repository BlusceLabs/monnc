import { IMG_BASE } from './config';

// Inline SVG placeholder used whenever TMDB has no artwork for an item.
export function placeholder(label = 'No image'): string {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='500' height='750'>
    <rect width='100%' height='100%' fill='#20221f'/>
    <rect x='0' y='0' width='100%' height='6' fill='#e6b325'/>
    <text x='50%' y='50%' fill='#8f9a84' font-family='sans-serif' font-size='26'
      text-anchor='middle' dominant-baseline='middle'>${label}</text>
  </svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

type PosterSize = 'w92' | 'w154' | 'w185' | 'w342' | 'w500' | 'w780' | 'original';
type BackdropSize = 'w300' | 'w780' | 'w1280' | 'original';
type ProfileSize = 'w45' | 'w185' | 'h632' | 'original';

const absolute = (path?: string | null) =>
  typeof path === 'string' && (path.startsWith('http://') || path.startsWith('https://'));

// Highest quality everywhere.
export function poster(path?: string | null, size: PosterSize = 'original'): string {
  return path ? (absolute(path) ? path : `${IMG_BASE}/${size}${path}`) : placeholder('No poster');
}

export function backdrop(path?: string | null, size: BackdropSize = 'original'): string {
  return path ? (absolute(path) ? path : `${IMG_BASE}/${size}${path}`) : placeholder('No backdrop');
}

export function profile(path?: string | null, size: ProfileSize = 'original'): string {
  return path ? (absolute(path) ? path : `${IMG_BASE}/${size}${path}`) : placeholder('No photo');
}

export function logo(path?: string | null, size: 'w45' | 'w185' | 'w300' | 'original' = 'original'): string {
  return path ? (absolute(path) ? path : `${IMG_BASE}/${size}${path}`) : placeholder('Logo');
}
