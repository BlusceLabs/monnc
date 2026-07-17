import {
  TMDB_BASE,
  TMDB_ACCESS_TOKEN,
  TMDB_API_KEY,
  LANGUAGE,
  REGION,
  hasCredentials,
} from './config';
import type { Paged, MediaItem, Genre } from './types';

type Params = Record<string, string | number | boolean | undefined | null>;

/**
 * Generic TMDB request. Uses a v4 bearer token when available, otherwise
 * appends the v3 api_key. Language & region defaults are injected automatically.
 */
async function request<T = any>(path: string, params: Params = {}): Promise<T> {
  if (!hasCredentials) {
    throw new Error(
      'Missing TMDB credentials. Copy .env.example to .env and set TMDB_ACCESS_TOKEN or TMDB_API_KEY.'
    );
  }

  const url = new URL(`${TMDB_BASE}${path}`);
  const merged: Params = { language: LANGUAGE, ...params };
  for (const [key, value] of Object.entries(merged)) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }

  // The backend (/api/tmdb) holds the real TMDB key, so the browser only
  // ever talks to our own origin — no credentials are attached here.
  const headers: Record<string, string> = { accept: 'application/json' };

  const res = await fetch(url, { headers });
  if (!res.ok) {
    throw new Error(`TMDB ${res.status} on ${path}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

// A tiny helper for appending append_to_response segments.
const append = (...parts: string[]) => parts.join(',');

export const tmdb = {
  raw: request,

  /* ------------------------------------------------------------------ *
   * 1. Configuration & reference                                        *
   * ------------------------------------------------------------------ */
  configuration: () => request('/configuration'), // 1
  countries: () => request('/configuration/countries'), // 2
  languages: () => request('/configuration/languages'), // 3
  jobs: () => request('/configuration/jobs'), // 4
  movieCertifications: () => request('/certification/movie/list'), // 5
  tvCertifications: () => request('/certification/tv/list'), // 6

  /* ------------------------------------------------------------------ *
   * 2. Trending                                                         *
   * ------------------------------------------------------------------ */
  trendingAll: (window: 'day' | 'week' = 'week', page = 1) =>
    request<Paged<MediaItem>>(`/trending/all/${window}`, { page }), // 7
  trendingMovies: (window: 'day' | 'week' = 'week', page = 1) =>
    request<Paged<MediaItem>>(`/trending/movie/${window}`, { page }), // 8
  trendingTv: (window: 'day' | 'week' = 'week', page = 1) =>
    request<Paged<MediaItem>>(`/trending/tv/${window}`, { page }), // 9
  trendingPeople: (window: 'day' | 'week' = 'week', page = 1) =>
    request<Paged<MediaItem>>(`/trending/person/${window}`, { page }), // 10

  /* ------------------------------------------------------------------ *
   * 3. Movie lists                                                      *
   * ------------------------------------------------------------------ */
  moviesPopular: (page = 1) =>
    request<Paged<MediaItem>>('/movie/popular', { page, region: REGION }), // 11
  moviesTopRated: (page = 1) =>
    request<Paged<MediaItem>>('/movie/top_rated', { page, region: REGION }), // 12
  moviesUpcoming: (page = 1) =>
    request<Paged<MediaItem>>('/movie/upcoming', { page, region: REGION }), // 13
  moviesNowPlaying: (page = 1) =>
    request<Paged<MediaItem>>('/movie/now_playing', { page, region: REGION }), // 14
  movieLatest: () => request<MediaItem>('/movie/latest'), // 15

  /* ------------------------------------------------------------------ *
   * 4. Movie detail (single call w/ append_to_response)                 *
   * ------------------------------------------------------------------ */
  movie: (id: number | string) =>
    request(`/movie/${id}`, {
      append_to_response: append(
        'credits',
        'images',
        'videos',
        'recommendations',
        'similar',
        'reviews',
        'keywords',
        'release_dates',
        'external_ids',
        'watch/providers'
      ),
      include_image_language: 'en,null',
    }), // 16 (details) + 17-25 appended
  movieCredits: (id: number | string) => request(`/movie/${id}/credits`), // 26
  movieImages: (id: number | string) => request(`/movie/${id}/images`), // 27
  movieVideos: (id: number | string) => request(`/movie/${id}/videos`), // 28
  movieRecommendations: (id: number | string, page = 1) =>
    request<Paged<MediaItem>>(`/movie/${id}/recommendations`, { page }), // 29
  movieSimilar: (id: number | string, page = 1) =>
    request<Paged<MediaItem>>(`/movie/${id}/similar`, { page }), // 30
  movieReviews: (id: number | string, page = 1) =>
    request(`/movie/${id}/reviews`, { page }), // 31
  movieKeywords: (id: number | string) => request(`/movie/${id}/keywords`), // 32
  movieWatchProviders: (id: number | string) =>
    request(`/movie/${id}/watch/providers`), // 33
  movieReleaseDates: (id: number | string) =>
    request(`/movie/${id}/release_dates`), // 34
  movieExternalIds: (id: number | string) =>
    request(`/movie/${id}/external_ids`), // 35

  /* ------------------------------------------------------------------ *
   * 5. TV lists                                                         *
   * ------------------------------------------------------------------ */
  tvPopular: (page = 1) => request<Paged<MediaItem>>('/tv/popular', { page }), // 36
  tvTopRated: (page = 1) => request<Paged<MediaItem>>('/tv/top_rated', { page }), // 37
  tvOnTheAir: (page = 1) => request<Paged<MediaItem>>('/tv/on_the_air', { page }), // 38
  tvAiringToday: (page = 1) =>
    request<Paged<MediaItem>>('/tv/airing_today', { page }), // 39
  tvLatest: () => request<MediaItem>('/tv/latest'), // 40

  /* ------------------------------------------------------------------ *
   * 6. TV detail, seasons & episodes                                    *
   * ------------------------------------------------------------------ */
  tv: (id: number | string) =>
    request(`/tv/${id}`, {
      append_to_response: append(
        'aggregate_credits',
        'images',
        'videos',
        'recommendations',
        'similar',
        'reviews',
        'keywords',
        'external_ids',
        'content_ratings',
        'watch/providers'
      ),
      include_image_language: 'en,null',
    }), // 41 (details) + 42-51 appended
  tvCredits: (id: number | string) => request(`/tv/${id}/credits`), // 52
  tvAggregateCredits: (id: number | string) =>
    request(`/tv/${id}/aggregate_credits`), // 53
  tvContentRatings: (id: number | string) =>
    request(`/tv/${id}/content_ratings`), // 54
  tvSeason: (id: number | string, season: number | string) =>
    request(`/tv/${id}/season/${season}`, {
      append_to_response: 'credits,images,videos',
    }), // 55
  tvEpisode: (id: number | string, season: number | string, ep: number | string) =>
    request(`/tv/${id}/season/${season}/episode/${ep}`), // 56
  tvWatchProviders: (id: number | string) => request(`/tv/${id}/watch/providers`), // 57
  tvExternalIds: (id: number | string) => request(`/tv/${id}/external_ids`), // 58
  tvSeasons: (id: number | string) => request(`/tv/${id}/seasons`), // 59

  /* ------------------------------------------------------------------ *
   * 7. People                                                           *
   * ------------------------------------------------------------------ */
  peoplePopular: (page = 1) =>
    request<Paged<MediaItem>>('/person/popular', { page }), // 59
  person: (id: number | string) =>
    request(`/person/${id}`, {
      append_to_response: append(
        'combined_credits',
        'movie_credits',
        'tv_credits',
        'images',
        'external_ids'
      ),
    }), // 60 (details) + 61-65 appended
  personCombinedCredits: (id: number | string) =>
    request(`/person/${id}/combined_credits`), // 66
  personImages: (id: number | string) => request(`/person/${id}/images`), // 67

  /* ------------------------------------------------------------------ *
   * 8. Search                                                           *
   * ------------------------------------------------------------------ */
  searchMulti: (query: string, page = 1) =>
    request<Paged<MediaItem>>('/search/multi', { query, page, include_adult: false }), // 68
  searchMovie: (query: string, page = 1) =>
    request<Paged<MediaItem>>('/search/movie', { query, page, include_adult: false }), // 69
  searchTv: (query: string, page = 1) =>
    request<Paged<MediaItem>>('/search/tv', { query, page, include_adult: false }), // 70
  searchPerson: (query: string, page = 1) =>
    request<Paged<MediaItem>>('/search/person', { query, page, include_adult: false }), // 71
  searchCollection: (query: string, page = 1) =>
    request('/search/collection', { query, page }), // 72
  searchCompany: (query: string, page = 1) =>
    request('/search/company', { query, page }), // 73
  searchKeyword: (query: string, page = 1) =>
    request('/search/keyword', { query, page }), // 74

  /* ------------------------------------------------------------------ *
   * 9. Discover                                                         *
   * ------------------------------------------------------------------ */
  discoverMovie: (params: Params = {}) =>
    request<Paged<MediaItem>>('/discover/movie', {
      sort_by: 'popularity.desc',
      include_adult: false,
      ...params,
    }), // 75
  discoverTv: (params: Params = {}) =>
    request<Paged<MediaItem>>('/discover/tv', {
      sort_by: 'popularity.desc',
      ...params,
    }), // 76

  /* ------------------------------------------------------------------ *
   * 10. Genres                                                          *
   * ------------------------------------------------------------------ */
  movieGenres: () => request<{ genres: Genre[] }>('/genre/movie/list'), // 77
  tvGenres: () => request<{ genres: Genre[] }>('/genre/tv/list'), // 78

  /* ------------------------------------------------------------------ *
   * 11. Collections, companies, keywords, networks, reviews             *
   * ------------------------------------------------------------------ */
  collection: (id: number | string) => request(`/collection/${id}`), // 79
  company: (id: number | string) => request(`/company/${id}`), // 80
  companyImages: (id: number | string) => request(`/company/${id}/images`), // 81
  keyword: (id: number | string) => request(`/keyword/${id}`), // 82
  keywordMovies: (id: number | string, page = 1) =>
    request<Paged<MediaItem>>(`/keyword/${id}/movies`, { page }), // 83
  network: (id: number | string) => request(`/network/${id}`), // 84
  review: (id: string) => request(`/review/${id}`), // 85

  /* ------------------------------------------------------------------ *
   * 12. Watch providers directory                                       *
   * ------------------------------------------------------------------ */
  providerRegions: () => request('/watch/providers/regions'), // 86
  movieProviders: () =>
    request('/watch/providers/movie', { watch_region: REGION }), // 87
  tvProviders: () => request('/watch/providers/tv', { watch_region: REGION }), // 88
};

export type Tmdb = typeof tmdb;
