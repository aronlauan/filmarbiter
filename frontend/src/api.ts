// Typed client for the FastAPI backend. Types mirror backend/app/schemas.py.

export const MAX_PICKS = 5

export interface MovieSummary {
  imdb_id: string
  title: string
  year: number | null
  poster_url: string | null
}

export interface PersonCredit {
  nconst: string
  name: string
}

export interface MovieDetail extends MovieSummary {
  original_title: string | null
  runtime_minutes: number | null
  genres: string[]
  imdb_rating: number | null
  imdb_votes: number
  overview: string | null
  keywords: string[]
  directors: PersonCredit[]
  writers: PersonCredit[]
  cast: PersonCredit[]
  imdb_url: string
  letterboxd_url: string
}

export interface MatchReasons {
  keywords: string[]
  genres: string[]
  people: string[]
}

export interface BlendResult {
  movie: MovieDetail
  score: number
  /** 0-100: how well the movie fits all the picks (the engine's score, rescaled). */
  match: number
  reasons: MatchReasons
}

export interface BlendResponse {
  picks: MovieSummary[]
  results: BlendResult[]
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown
  /** Machine-readable reason from `{detail: {reason, message}}` errors, if any. */
  readonly reason: string | null

  constructor(status: number, detail: unknown) {
    const obj = typeof detail === 'object' && detail !== null ? (detail as Record<string, unknown>) : null
    const message =
      typeof detail === 'string'
        ? detail
        : typeof obj?.message === 'string'
          ? obj.message
          : `Request failed (${status})`
    super(message)
    this.status = status
    this.detail = detail
    this.reason = typeof obj?.reason === 'string' ? obj.reason : null
  }
}

export const SERVER_UNREACHABLE = "Can't reach filmarbiter right now. Check your connection and try again."

/** True when the request never got an answer from our API (network down, server stopped). */
export function isServerUnreachable(err: unknown): boolean {
  return err instanceof ApiError && err.status === 0
}

/** API origin. Empty in development (Vite proxies /api); set VITE_API_URL at build time
 * when the API lives elsewhere, e.g. https://filmarbiter-api.onrender.com. */
const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(API_BASE + path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err // cancelled, not an outage
    throw new ApiError(0, SERVER_UNREACHABLE)
  }
  if (!resp.ok) {
    const isJson = resp.headers.get('content-type')?.includes('application/json')
    // Our API always answers with JSON; a non-JSON 5xx comes from a proxy in front of
    // it (e.g. Vite's dev proxy returns 502 when the backend isn't running).
    if (!isJson && resp.status >= 500) throw new ApiError(0, SERVER_UNREACHABLE)
    let detail: unknown = resp.statusText
    try {
      detail = (await resp.json()).detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail)
  }
  return resp.json() as Promise<T>
}

/** Resolves once the API answers. On Render's free tier the first request after a
 *  nap waits while the server boots (up to about a minute). */
export async function checkHealth(signal?: AbortSignal): Promise<void> {
  await request('/api/health', { signal })
}

export function searchMovies(q: string, signal?: AbortSignal): Promise<MovieSummary[]> {
  const params = new URLSearchParams({ q, limit: '8' })
  return request(`/api/movies/search?${params}`, { signal })
}

export function blendMovies(imdbIds: string[]): Promise<BlendResponse> {
  return request('/api/blend', { method: 'POST', body: JSON.stringify({ imdb_ids: imdbIds }) })
}

/** TMDB poster at another width (the API hands out w342 URLs). */
export function posterSrc(url: string | null, size: 'w92' | 'w185' | 'w342'): string | null {
  return url ? url.replace('/w342/', `/${size}/`) : null
}

export interface RolledMovie {
  /** The genre this movie was drawn for. */
  genre: string
  movie: MovieDetail
}

/** `perGenre` random well-rated movies for each genre, in the order given, skipping
 *  `exclude`. Genres with nothing to offer are left out. */
export function rollMovies(genres: string[], perGenre: number, exclude: string[]): Promise<RolledMovie[]> {
  const params = new URLSearchParams({ genres: genres.join(','), per_genre: String(perGenre) })
  if (exclude.length) params.set('exclude', exclude.join(','))
  return request(`/api/movies/roll?${params}`)
}

// --- Movie map --------------------------------------------------------------

/** A movie in the Blender's theater; x and y are in [-1, 1]. */
export interface MapNode extends MovieSummary {
  x: number
  y: number
  /** Index into MapResponse.sections. */
  section: number
  /** The film's own IMDb genres (a section only names an area of the house). */
  genres: string[]
}

/** An area of the house, named after its most distinctive genre. */
export interface MapSection {
  name: string
  size: number
}

export interface MapResponse {
  /** Board grid spacing; every node's x and y is a multiple of it. */
  grid: number
  nodes: MapNode[]
  sections: MapSection[]
  /** Links between similar movies, as index pairs into nodes. */
  edges: [number, number][]
}

/** A seat made for a movie outside the house's seating (a pick or a result). */
export interface MapSeat {
  imdb_id: string
  x: number
  y: number
  section: number
  /** Its most similar seats, as indexes into MapResponse.nodes. */
  links: number[]
  genres: string[]
}

/** A pick or result shown with a made-for-it seat. */
export interface ExtraSeat extends MapNode {
  links: number[]
}

export function getMovieMap(): Promise<MapResponse> {
  return request('/api/map')
}

/** Seats for movies without one, next to where they belong. Order matters: earlier
 *  ids keep their seat as more are added (send picks before results). Movies not on
 *  the map are left out. */
export function getMapSeats(imdbIds: string[]): Promise<MapSeat[]> {
  return request(`/api/map/seats?ids=${imdbIds.map(encodeURIComponent).join(',')}`)
}

// --- Letterboxd -------------------------------------------------------------

export interface LetterboxdProfile {
  username: string
  display_name: string
  avatar_url: string | null
  films_count: number
}

/** A search hit: enough to recognise the account, not yet verified (no film count). */
export interface LetterboxdMember {
  username: string
  display_name: string
  avatar_url: string | null
  badge: string | null
}

export interface MemberSearchResponse {
  query: string
  /** exact: username or display name equals the query; partial: closest matches only. */
  match: 'exact' | 'partial' | 'none'
  results: LetterboxdMember[]
}

export type VerifyStatus = 'ok' | 'not_found' | 'private' | 'invalid'

export interface VerifyResponse {
  status: VerifyStatus
  profile: LetterboxdProfile | null
}

export type ImportPhase = 'fetching' | 'matching' | 'saving'

export interface ImportStatus {
  job_id: string
  username: string
  status: 'pending' | 'running' | 'done' | 'failed'
  phase: ImportPhase | null
  films_total: number | null
  films_fetched: number
  films_matched: number
  films_rated: number
  error: string | null
  created_at: string
  finished_at: string | null
}

export interface BecauseFilm {
  imdb_id: string
  title: string
  year: number | null
  rating: number | null
  liked: boolean
}

export interface ProfileRecommendation {
  movie: MovieDetail
  score: number
  reasons: MatchReasons
  because: BecauseFilm[]
}

export interface RecommendationsResponse {
  username: string
  imported_at: string | null
  films_logged: number
  films_matched: number
  results: ProfileRecommendation[]
}

/** Accepts "name", "@name", a display name or a pasted profile URL
 * ("letterboxd.com/name/films/" -> "name"). */
export function parseLetterboxdUsername(input: string): string {
  const s = input.trim()
  const fromUrl = s.match(/letterboxd\.com\/([^/?#\s]+)/i)
  return (fromUrl ? fromUrl[1] : s.replace(/^@/, '')).trim()
}

export function searchLetterboxd(query: string): Promise<MemberSearchResponse> {
  return request(`/api/letterboxd/search?q=${encodeURIComponent(query)}`)
}

export function verifyLetterboxd(username: string): Promise<VerifyResponse> {
  return request(`/api/letterboxd/verify/${encodeURIComponent(username)}`)
}

export function startLetterboxdImport(username: string, refresh = false): Promise<ImportStatus> {
  return request('/api/letterboxd/import', {
    method: 'POST',
    body: JSON.stringify({ username, refresh }),
  })
}

export function getLetterboxdImport(jobId: string): Promise<ImportStatus> {
  return request(`/api/letterboxd/import/${encodeURIComponent(jobId)}`)
}

export function getLetterboxdRecommendations(
  username: string,
  limit = 10,
): Promise<RecommendationsResponse> {
  return request(
    `/api/letterboxd/${encodeURIComponent(username)}/recommendations?limit=${limit}`,
  )
}
