import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, blendMovies, MAX_PICKS, type BlendResponse, type MovieSummary } from '../api'
import MovieCard, { MovieCardSkeleton } from '../components/MovieCard'
import MovieSearch from '../components/MovieSearch'
import PickChips from '../components/PickChips'

const IMDB_ID = /^tt\d{7,10}$/

function idsFromParams(params: URLSearchParams): string[] {
  const raw = params.get('ids')?.split(',') ?? []
  return [...new Set(raw.filter((id) => IMDB_ID.test(id)))].slice(0, MAX_PICKS)
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "One of those movies isn't in our catalog. Remove it and try again."
    if (err.status === 503) return "Recommendations aren't available right now. Try again in a bit."
    return err.message
  }
  return 'Something went wrong. Try again.'
}

export default function Blender() {
  const [params, setParams] = useSearchParams()
  const [picks, setPicks] = useState<MovieSummary[]>([])
  const [blendedKey, setBlendedKey] = useState<string | null>(null)
  const hydrated = useRef(false)

  const blend = useMutation<BlendResponse, unknown, string[]>({ mutationFn: blendMovies })

  // Shared links (/blend?ids=tt..,tt..): run the blend and take the picks from the response.
  useEffect(() => {
    if (hydrated.current) return
    hydrated.current = true
    const ids = idsFromParams(params)
    if (ids.length === 0) return
    blend.mutate(ids, {
      onSuccess: (data) => {
        setPicks(data.picks)
        setBlendedKey(data.picks.map((p) => p.imdb_id).join(','))
      },
    })
  }, [params, blend])

  const pickedIds = new Set(picks.map((p) => p.imdb_id))
  const currentKey = picks.map((p) => p.imdb_id).join(',')
  const stale = blend.data !== undefined && blendedKey !== currentKey
  const full = picks.length >= MAX_PICKS

  function runBlend() {
    const ids = picks.map((p) => p.imdb_id)
    setParams({ ids: ids.join(',') }, { replace: true })
    setBlendedKey(currentKey)
    blend.mutate(ids)
  }

  return (
    <section className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">Movie Blender</h1>
        <p className="text-stone-600 dark:text-stone-400">
          Pick up to {MAX_PICKS} movies with the vibe you're after. We'll find the 3 that best match all
          of them.
        </p>
      </header>

      <div className="space-y-4">
        <MovieSearch
          pickedIds={pickedIds}
          disabled={full}
          placeholder={full ? `That's ${MAX_PICKS}. Remove one to swap it out.` : undefined}
          onSelect={(m) => setPicks((p) => (p.length < MAX_PICKS ? [...p, m] : p))}
        />
        <PickChips picks={picks} onRemove={(id) => setPicks((p) => p.filter((m) => m.imdb_id !== id))} />
        <button
          type="button"
          onClick={runBlend}
          disabled={picks.length === 0 || blend.isPending}
          className="w-full rounded-lg bg-stone-900 px-6 py-3 font-semibold text-white transition hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto dark:bg-stone-100 dark:text-stone-900 dark:hover:bg-stone-300"
        >
          {blend.isPending ? 'Blending…' : picks.length > 0 && stale ? 'Blend again' : 'Blend'}
        </button>
      </div>

      <div aria-live="polite" className="space-y-4">
        {blend.isPending && (
          <>
            <MovieCardSkeleton />
            <MovieCardSkeleton />
            <MovieCardSkeleton />
          </>
        )}

        {blend.isError && !blend.isPending && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
            {errorMessage(blend.error)}
          </p>
        )}

        {blend.data && !blend.isPending && (
          <>
            <h2 className="text-xl font-semibold">
              Your blend
              {stale && (
                <span className="ml-2 text-sm font-normal text-stone-500">
                  (for your previous picks; blend again to update)
                </span>
              )}
            </h2>
            {blend.data.results.length === 0 ? (
              <p className="text-stone-500">No matches found. Try different picks.</p>
            ) : (
              <div className={`space-y-4 transition ${stale ? 'opacity-50' : ''}`}>
                {blend.data.results.map((r, i) => (
                  <MovieCard key={r.movie.imdb_id} movie={r.movie} reasons={r.reasons} rank={i + 1} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}
