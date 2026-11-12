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

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `Request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError(0, "Can't reach the filmarbiter server.")
  }
  if (!resp.ok) {
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
