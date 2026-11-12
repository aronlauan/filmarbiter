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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(path, {
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

export function searchMovies(q: string, signal?: AbortSignal): Promise<MovieSummary[]> {
  const params = new URLSearchParams({ q, limit: '8' })
  return request(`/api/movies/search?${params}`, { signal })
}

export function blendMovies(imdbIds: string[]): Promise<BlendResponse> {
  return request('/api/blend', { method: 'POST', body: JSON.stringify({ imdb_ids: imdbIds }) })
}

// --- Letterboxd -------------------------------------------------------------

export interface LetterboxdProfile {
  username: string
  display_name: string
  avatar_url: string | null
  films_count: number
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

/** Accepts "name", "@name" or a pasted profile URL ("letterboxd.com/name/films/"). */
export function parseLetterboxdUsername(input: string): string {
  const s = input.trim()
  const fromUrl = s.match(/letterboxd\.com\/([^/?#\s]+)/i)
  return (fromUrl ? fromUrl[1] : s.replace(/^@/, '')).trim()
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
