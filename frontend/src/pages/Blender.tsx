import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ApiError,
  blendMovies,
  getMapSeats,
  getMovieMap,
  MAX_PICKS,
  type BlendResponse,
  type ExtraSeat,
  type MovieSummary,
} from '../api'
import MovieCard, { MovieCardSkeleton } from '../components/MovieCard'
import MovieTheater from '../components/MovieTheater'
import MovieSearch from '../components/MovieSearch'
import PickChips from '../components/PickChips'

const NO_RESULTS: BlendResponse['results'] = [] // stable, so the theater's memos hold

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
  const [focusId, setFocusId] = useState<string | null>(null)
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
  const results = blend.data && !blend.isPending ? blend.data.results : NO_RESULTS

  // --- Movie theater ----------------------------------------------------------
  // Optional: if the map isn't built or fails to load, the panel works on its own.
  const map = useQuery({ queryKey: ['map'], queryFn: getMovieMap, staleTime: Infinity, retry: 1 })
  const boardVisible = !map.isError

  const highlighted = useMemo(
    () => [...picks, ...results.map((r) => r.movie)],
    [picks, results],
  )
  const nodeIds = useMemo(() => new Set(map.data?.nodes.map((n) => n.imdb_id)), [map.data])
  const missing = map.data
    ? [...new Set(highlighted.map((m) => m.imdb_id).filter((id) => !nodeIds.has(id)))]
    : []
  // Picks and results without a seat get one made next to where they belong, so
  // every blend looks the same whether or not its movies were already in the house.
  const extraSeats = useQuery({
    queryKey: ['map-seats', missing.join(',')],
    queryFn: () => getMapSeats(missing),
    enabled: missing.length > 0,
    staleTime: Infinity,
    placeholderData: (previous) => previous, // keep seats steady while the next set loads
  })
  const extras = useMemo<ExtraSeat[]>(() => {
    const byId = new Map(highlighted.map((m) => [m.imdb_id, m]))
    return (extraSeats.data ?? []).flatMap((s) => {
      const m = byId.get(s.imdb_id)
      return m ? [{ ...s, title: m.title, year: m.year, poster_url: m.poster_url }] : []
    })
  }, [extraSeats.data, highlighted])

  function addPick(m: MovieSummary) {
    setPicks((p) => (p.length < MAX_PICKS && !p.some((x) => x.imdb_id === m.imdb_id) ? [...p, m] : p))
  }

  function removePick(imdbId: string) {
    setPicks((p) => p.filter((m) => m.imdb_id !== imdbId))
  }

  function runBlend() {
    const ids = picks.map((p) => p.imdb_id)
    setParams({ ids: ids.join(',') }, { replace: true })
    setBlendedKey(currentKey)
    blend.mutate(ids)
  }

  return (
    <section
      className={
        boardVisible
          ? 'flex flex-col gap-6 lg:grid lg:grid-cols-[minmax(0,1fr)_26rem] lg:items-start lg:gap-8'
          : 'mx-auto max-w-3xl'
      }
    >
      {boardVisible && (
        <div className="relative h-[38vh] min-h-64 overflow-hidden rounded-lg border border-stone-200 bg-[radial-gradient(ellipse_at_center,_white,_var(--color-stone-100))] lg:sticky lg:top-6 lg:h-[calc(100vh-10rem)] lg:min-h-[32rem] dark:border-stone-800 dark:bg-[radial-gradient(ellipse_at_center,_var(--color-stone-900),_var(--color-stone-950))]">
          {map.data ? (
            <MovieTheater
              grid={map.data.grid}
              nodes={map.data.nodes}
              edges={map.data.edges}
              sections={map.data.sections}
              extras={extras}
              pickIds={picks.map((p) => p.imdb_id)}
              resultIds={results.map((r) => r.movie.imdb_id)}
              stale={stale}
              blending={blend.isPending}
              focusId={focusId}
              canAdd={!full}
              onToggle={(m) => (pickedIds.has(m.imdb_id) ? removePick(m.imdb_id) : addPick(m))}
            />
          ) : (
            <p className="absolute inset-0 flex animate-pulse items-center justify-center text-sm text-stone-400">
              Mapping the catalog…
            </p>
          )}
          <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap gap-x-4 gap-y-1 rounded-md bg-white/85 px-2 py-1 text-xs text-stone-500 backdrop-blur dark:bg-stone-950/80">
            {picks.length > 0 && (
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-amber-500 dark:bg-amber-400" /> Your picks
              </span>
            )}
            {results.length > 0 && (
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-sky-600 dark:bg-sky-400" /> Your blend
              </span>
            )}
            {picks.length === 0 && (
              <span>
                <span className="hidden sm:inline">Hover a seat to explore, click to add it. Scroll or drag to move around.</span>
                <span className="sm:hidden">Tap a seat to explore. Pinch to zoom.</span>
              </span>
            )}
          </div>
        </div>
      )}

      <div className="space-y-8">
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
            onSelect={addPick}
          />
          <PickChips picks={picks} onRemove={removePick} />
          <button
            type="button"
            onClick={runBlend}
            disabled={picks.length === 0 || blend.isPending}
            className="w-full rounded-lg bg-stone-900 px-6 py-3 font-semibold text-white transition hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-stone-100 dark:text-stone-900 dark:hover:bg-stone-300"
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
              {results.length === 0 ? (
                <p className="text-stone-500">No matches found. Try different picks.</p>
              ) : (
                <div className={`space-y-4 transition ${stale ? 'opacity-50' : ''}`}>
                  {results.map((r, i) => (
                    <div
                      key={r.movie.imdb_id}
                      onMouseEnter={() => setFocusId(r.movie.imdb_id)}
                      onMouseLeave={() => setFocusId(null)}
                      onFocus={() => setFocusId(r.movie.imdb_id)}
                      onBlur={() => setFocusId(null)}
                    >
                      <MovieCard movie={r.movie} reasons={r.reasons} rank={i + 1} />
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  )
}
