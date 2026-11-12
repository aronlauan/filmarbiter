import { useMutation, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import BlendButton from '../components/BlendButton'
import { ResultsAside, ResultsTray } from '../components/BlendResults'
import MovieTheater from '../components/MovieTheater'
import { PicksDock, PicksRail } from '../components/PicksDrawer'
import { useMediaQuery } from '../hooks'

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
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [resultsOpen, setResultsOpen] = useState(true)
  const desktop = useMediaQuery('(min-width: 1024px)')
  const focusResult = useCallback((id: string | null) => setFocusId(id), [])
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
    setDrawerOpen(false)
    setResultsOpen(true)
    blend.mutate(ids)
  }

  const hasOutcome = blend.isPending || blend.isError || blend.data !== undefined
  const outcome = {
    pending: blend.isPending,
    error: blend.isError && !blend.isPending ? errorMessage(blend.error) : null,
    results: blend.data && !blend.isPending ? blend.data.results : null,
    stale,
    onFocusResult: focusResult,
  }
  const picksProps = { picks, onAdd: addPick, onRemove: removePick, open: drawerOpen, onOpenChange: setDrawerOpen }
  const blendButton = (className: string, showCount: boolean) => (
    <BlendButton
      count={picks.length}
      pending={blend.isPending}
      stale={picks.length > 0 && stale}
      showCount={showCount}
      onClick={runBlend}
      className={className}
    />
  )

  const theater = (
    <div className="relative min-h-0 min-w-0 flex-1 bg-[radial-gradient(ellipse_at_center,_white,_var(--color-stone-100))] dark:bg-[radial-gradient(ellipse_at_center,_var(--color-stone-900),_var(--color-stone-950))]">
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
        <p
          className={`absolute inset-0 flex items-center justify-center px-8 text-center text-sm text-stone-500 lg:pl-28 ${
            map.isError ? '' : 'animate-pulse'
          }`}
        >
          {map.isError
            ? `The seat map isn't available right now. ${desktop ? 'Search on the left' : 'Tap search below'} to pick movies and blend.`
            : 'Mapping the catalog…'}
        </p>
      )}

      <div className="pointer-events-none absolute top-3 left-3 flex flex-wrap gap-x-4 gap-y-1 rounded-md bg-white/80 px-2 py-1 text-xs text-stone-500 backdrop-blur lg:left-[5.5rem] dark:bg-stone-950/75">
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
        {picks.length === 0 && map.data && (
          <span>
            {desktop
              ? 'Hover the left edge to search. Click a seat to add it; scroll or drag to move around.'
              : 'Tap a seat to explore. Pinch to zoom.'}
          </span>
        )}
      </div>

      {desktop && <PicksRail {...picksProps} forceOpen={map.isError} />}
      {desktop && blendButton('absolute bottom-6 left-1/2 z-10 -translate-x-1/2 px-8 py-3.5 text-lg', true)}
      {desktop && hasOutcome && !resultsOpen && (
        <button
          type="button"
          onClick={() => setResultsOpen(true)}
          className="absolute right-6 bottom-6 z-10 flex items-center gap-2 rounded-full border border-stone-200 bg-white/90 px-4 py-2.5 text-sm font-semibold shadow-lg backdrop-blur hover:bg-white dark:border-stone-700 dark:bg-stone-900/90 dark:hover:bg-stone-900"
        >
          <span className="h-2 w-2 rounded-full bg-sky-600 dark:bg-sky-400" /> Show your blend <span aria-hidden="true">←</span>
        </button>
      )}
    </div>
  )

  return (
    <section className={`relative flex h-[calc(100dvh-3.5rem)] overflow-hidden ${desktop ? 'flex-row' : 'flex-col'}`}>
      <h1 className="sr-only">Movie Blender</h1>
      {theater}
      {desktop ? (
        <ResultsAside {...outcome} open={hasOutcome && resultsOpen} onOpenChange={setResultsOpen} />
      ) : (
        <>
          {hasOutcome && <ResultsTray {...outcome} open={resultsOpen} onOpenChange={setResultsOpen} />}
          <PicksDock {...picksProps} action={blendButton('relative shrink-0 px-5', false)} />
        </>
      )}
    </section>
  )
}
