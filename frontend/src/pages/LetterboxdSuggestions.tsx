import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ApiError,
  getLetterboxdImport,
  getLetterboxdRecommendations,
  startLetterboxdImport,
  verifyLetterboxd,
  type ImportStatus,
} from '../api'
import MovieCard, { MovieCardSkeleton } from '../components/MovieCard'
import { errorStatus, importErrorMessage, verifyMessage } from '../letterboxd'

const INITIAL_PICKS = 3
const MAX_PICKS = 10

function timeAgo(iso: string | null): string | null {
  if (!iso) return null
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000)
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ]
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit)
  }
  return 'just now'
}

/** POST /import, re-verifying once if the server forgot the verification (e.g. restart). */
async function startImport(username: string, refresh: boolean): Promise<ImportStatus> {
  try {
    return await startLetterboxdImport(username, refresh)
  } catch (err) {
    if (err instanceof ApiError && err.reason === 'not_verified') {
      await verifyLetterboxd(username)
      return startLetterboxdImport(username, refresh)
    }
    throw err
  }
}

function ImportProgress({ job }: { job: ImportStatus | undefined }) {
  const total = job?.films_total ?? 0
  const fetched = job?.films_fetched ?? 0
  let label = 'Starting…'
  let pct: number | null = null
  if (job?.phase === 'fetching') {
    label = total
      ? `Reading your films… ${fetched.toLocaleString()} of ${total.toLocaleString()}`
      : `Reading your films… ${fetched.toLocaleString()}`
    pct = total ? Math.min(100, (fetched / total) * 100) : null
  } else if (job?.phase === 'matching') {
    label = `Matching your ${fetched.toLocaleString()} films to our catalog…`
  } else if (job?.phase === 'saving') {
    label = 'Almost done…'
  }
  return (
    <div className="space-y-2" role="status">
      <p className="text-stone-700 dark:text-stone-300">{label}</p>
      <div
        className="h-2 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800"
        role="progressbar"
        aria-label="Import progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct === null ? undefined : Math.round(pct)}
      >
        {pct === null ? (
          <div className="h-full w-1/3 animate-pulse rounded-full bg-stone-500" />
        ) : (
          <div className="h-full rounded-full bg-stone-700 transition-all dark:bg-stone-300" style={{ width: `${pct}%` }} />
        )}
      </div>
      <p className="text-sm text-stone-500">Big profiles can take up to a minute.</p>
    </div>
  )
}

export default function LetterboxdSuggestions() {
  const { username: rawUsername = '' } = useParams()
  const username = rawUsername.toLowerCase()
  const navigate = useNavigate()
  const [refreshes, setRefreshes] = useState(0)
  const [showAll, setShowAll] = useState(false)

  const verify = useQuery({
    queryKey: ['lb-verify', username],
    queryFn: () => verifyLetterboxd(username),
    retry: false,
    staleTime: 5 * 60_000,
  })
  const profile = verify.data?.status === 'ok' ? verify.data.profile : null

  // Direct visits to a bad username go back to the form with the reason.
  useEffect(() => {
    if (verify.data && verify.data.status !== 'ok') {
      const q = new URLSearchParams({ user: rawUsername, error: verify.data.status })
      navigate(`/letterboxd?${q}`, { replace: true })
    }
  }, [verify.data, navigate, rawUsername])

  // Idempotent on the server (reuses running / recent imports), so it's safe as a query.
  const started = useQuery({
    queryKey: ['lb-import-start', username, refreshes],
    queryFn: () => startImport(username, refreshes > 0),
    enabled: profile !== null,
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  const jobId = started.data?.job_id

  const job = useQuery({
    queryKey: ['lb-import', jobId],
    queryFn: () => getLetterboxdImport(jobId!),
    enabled: jobId !== undefined,
    initialData: started.data,
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'done' || s === 'failed' ? false : 1000
    },
  })
  const status = job.data?.status

  const recs = useQuery({
    queryKey: ['lb-recs', username, job.data?.finished_at],
    queryFn: () => getLetterboxdRecommendations(username, MAX_PICKS),
    enabled: status === 'done',
    retry: false,
  })

  function refresh() {
    setShowAll(false)
    setRefreshes((n) => n + 1)
  }

  const results = recs.data?.results ?? []
  const shown = showAll ? results : results.slice(0, INITIAL_PICKS)

  return (
    <section className="space-y-8">
      <header className="flex items-center gap-4">
        {profile?.avatar_url && (
          <img src={profile.avatar_url} alt="" className="h-14 w-14 shrink-0 rounded-full object-cover" />
        )}
        <div className="min-w-0">
          <h1 className="text-3xl font-bold tracking-tight">
            Picks for {profile?.display_name ?? rawUsername}
          </h1>
          <p className="text-stone-600 dark:text-stone-400">
            Based on your Letterboxd ratings ·{' '}
            <Link to="/letterboxd" className="underline-offset-2 hover:underline">
              Not you?
            </Link>
          </p>
        </div>
      </header>

      <div aria-live="polite" className="space-y-6">
        {verify.isPending && <p className="text-stone-600 dark:text-stone-400">Checking your Letterboxd profile…</p>}

        {verify.isError && (
          <div role="alert" className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
            <p>{verifyMessage(errorStatus(verify.error), rawUsername)}</p>
            <button type="button" onClick={() => verify.refetch()} className="font-medium underline">
              Try again
            </button>
          </div>
        )}

        {started.isError && (
          <div role="alert" className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
            <p>{verifyMessage(errorStatus(started.error), rawUsername)}</p>
            <button type="button" onClick={() => started.refetch()} className="font-medium underline">
              Try again
            </button>
          </div>
        )}

        {profile && !started.isError && status !== 'done' && status !== 'failed' && (
          <ImportProgress job={job.data} />
        )}

        {status === 'failed' && (
          <div role="alert" className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
            <p>{importErrorMessage(job.data?.error ?? null)}</p>
            <button type="button" onClick={refresh} className="font-medium underline">
              Try again
            </button>
          </div>
        )}

        {status === 'done' && recs.isPending && (
          <>
            <MovieCardSkeleton />
            <MovieCardSkeleton />
            <MovieCardSkeleton />
          </>
        )}

        {recs.isError && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
            {recs.error instanceof ApiError && recs.error.status === 503
              ? "Recommendations aren't available right now. Try again in a bit."
              : 'Something went wrong loading your picks. Try again.'}
          </p>
        )}

        {recs.data && (
          <>
            <p className="text-sm text-stone-600 dark:text-stone-400">
              Based on the {recs.data.films_matched.toLocaleString()} of your{' '}
              {recs.data.films_logged.toLocaleString()} logged films that are in our catalog
              {recs.data.films_matched < recs.data.films_logged && ' (we cover films with 5,000+ IMDb ratings)'}.
              {recs.data.imported_at && <> Updated {timeAgo(recs.data.imported_at)}. </>}{' '}
              <button type="button" onClick={refresh} className="font-medium underline-offset-2 hover:underline">
                Refresh from Letterboxd
              </button>
            </p>

            {results.length === 0 ? (
              <p className="text-stone-600 dark:text-stone-400">
                We couldn't match enough of your films to make suggestions yet. Log and rate a few more on
                Letterboxd, or try the <Link to="/blend" className="underline">Movie Blender</Link>.
              </p>
            ) : (
              <div className="space-y-4">
                {shown.map((r, i) => (
                  <MovieCard key={r.movie.imdb_id} movie={r.movie} reasons={r.reasons} because={r.because} rank={i + 1} />
                ))}
                {!showAll && results.length > INITIAL_PICKS && (
                  <button
                    type="button"
                    onClick={() => setShowAll(true)}
                    className="w-full rounded-lg border border-stone-300 px-6 py-3 font-medium hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800"
                  >
                    Show {results.length - INITIAL_PICKS} more picks
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}
