import { useEffect, useRef, useState } from 'react'
import type { BlendResult } from '../api'
import MovieCard, { MovieCardSkeleton } from './MovieCard'

export interface BlendOutcome {
  pending: boolean
  /** Shown instead of results when the blend failed. */
  error: string | null
  results: BlendResult[] | null
  /** Results belong to an older set of picks. */
  stale: boolean
}

interface Props extends BlendOutcome {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** The result being looked at, so the theater can point at its seat. */
  onFocusResult: (imdbId: string | null) => void
}

function StaleNote({ className = '' }: { className?: string }) {
  return <span className={`text-xs font-normal text-stone-500 ${className}`}>For your previous picks; blend again to update</span>
}

function ErrorNote({ message }: { message: string }) {
  return (
    <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
      {message}
    </p>
  )
}

/** Desktop: a column beside the theater. The theater narrows to make room, so its
 *  framing of the results stays in view next to the list. */
export function ResultsAside({ pending, error, results, stale, open, onOpenChange, onFocusResult }: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (pending) scroller.current?.scrollTo({ top: 0 })
  }, [pending])

  return (
    <aside
      aria-label="Your blend"
      inert={!open}
      className={`relative shrink-0 overflow-hidden transition-[width] duration-500 ease-out motion-reduce:transition-none ${open ? 'w-[28rem]' : 'w-0'}`}
    >
      <div className="absolute inset-y-0 left-0 flex w-[28rem] flex-col border-l border-stone-200 bg-stone-50/95 dark:border-stone-800 dark:bg-stone-950/95">
        <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-3">
          <div>
            <h2 className="text-xl font-semibold">Your blend</h2>
            {stale && !pending && <StaleNote />}
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            aria-label="Hide your blend"
            title="Hide"
            className="flex h-8 w-8 items-center justify-center rounded-full text-stone-500 hover:bg-stone-200/70 hover:text-stone-900 dark:hover:bg-stone-800 dark:hover:text-white"
          >
            <span aria-hidden="true">→</span>
          </button>
        </div>
        <div ref={scroller} aria-live="polite" className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 pb-5">
          {pending ? (
            <>
              <MovieCardSkeleton />
              <MovieCardSkeleton />
              <MovieCardSkeleton />
            </>
          ) : error ? (
            <ErrorNote message={error} />
          ) : results && results.length === 0 ? (
            <p className="text-stone-500">No matches found. Try different picks.</p>
          ) : (
            results?.map((r, i) => (
              <div
                key={r.movie.imdb_id}
                className={`animate-[rise_500ms_ease-out_both] transition-opacity motion-reduce:animate-none ${stale ? 'opacity-50' : ''}`}
                style={{ animationDelay: `${i * 90}ms` }}
                onMouseEnter={() => onFocusResult(r.movie.imdb_id)}
                onMouseLeave={() => onFocusResult(null)}
                onFocus={() => onFocusResult(r.movie.imdb_id)}
                onBlur={() => onFocusResult(null)}
              >
                <MovieCard movie={r.movie} reasons={r.reasons} match={r.match} rank={i + 1} />
              </div>
            ))
          )}
        </div>
      </div>
    </aside>
  )
}

/**
 * Mobile: a tray between the theater and the dock with one result card at a time.
 * Swipe through them and the theater points at each one's seat. The header
 * collapses it to give the map the room back.
 */
export function ResultsTray({ pending, error, results, stale, open, onOpenChange, onFocusResult }: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const list = results ?? []
  // Which card is in view, per set of results: a new blend starts at the top pick.
  // (The card strip remounts with each blend, so its scroll starts there too.)
  const [seen, setSeen] = useState({ results, index: 0 })
  const active = seen.results === results ? seen.index : 0
  const setActive = (index: number) => setSeen({ results, index })

  const focusId = open && !pending && !error ? (list[active]?.movie.imdb_id ?? null) : null
  useEffect(() => onFocusResult(focusId), [focusId, onFocusResult])

  function onScroll() {
    const el = scroller.current
    const first = el?.firstElementChild as HTMLElement | null
    if (!el || !first) return
    const step = first.offsetWidth + 12 // card width + gap-3
    setActive(Math.min(list.length - 1, Math.max(0, Math.round(el.scrollLeft / step))))
  }

  function goTo(i: number) {
    const el = scroller.current
    const card = el?.children[i] as HTMLElement | undefined
    if (el && card) el.scrollTo({ left: card.offsetLeft - el.offsetLeft - 16, behavior: 'smooth' })
  }

  return (
    <section aria-label="Your blend" className="relative z-10 shrink-0 border-t border-stone-200/80 bg-stone-50/95 dark:border-stone-800/80 dark:bg-stone-950/95">
      <div className="flex items-center gap-2 px-4 py-2">
        <button
          type="button"
          onClick={() => onOpenChange(!open)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span className="h-2 w-2 shrink-0 rounded-full bg-sky-600 dark:bg-sky-400" />
          <h2 className="font-semibold">{pending ? 'Blending…' : 'Your blend'}</h2>
          {stale && !pending && <StaleNote className="truncate" />}
          <svg
            viewBox="0 0 24 24"
            aria-hidden="true"
            className={`ml-auto h-4 w-4 shrink-0 text-stone-500 transition-transform ${open ? '' : 'rotate-180'}`}
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
        {open && list.length > 1 && !pending && !error && (
          <div className="flex gap-1.5" role="tablist" aria-label="Results">
            {list.map((r, i) => (
              <button
                key={r.movie.imdb_id}
                type="button"
                role="tab"
                aria-selected={i === active}
                aria-label={`${i + 1}. ${r.movie.title}`}
                onClick={() => goTo(i)}
                className={`h-2 rounded-full transition-all ${i === active ? 'w-5 bg-sky-600 dark:bg-sky-400' : 'w-2 bg-stone-300 dark:bg-stone-700'}`}
              />
            ))}
          </div>
        )}
      </div>

      <div className={`grid transition-[grid-template-rows] duration-400 ease-out motion-reduce:transition-none ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
        <div className="min-h-0 overflow-hidden" inert={!open}>
          <div aria-live="polite" className="pb-3">
            {pending ? (
              <div className="flex gap-3 overflow-hidden px-4">
                <div className="w-[86%] shrink-0">
                  <MovieCardSkeleton compact />
                </div>
                <div className="w-[86%] shrink-0">
                  <MovieCardSkeleton compact />
                </div>
              </div>
            ) : error ? (
              <div className="px-4">
                <ErrorNote message={error} />
              </div>
            ) : list.length === 0 ? (
              <p className="px-4 text-stone-500">No matches found. Try different picks.</p>
            ) : (
              <div
                ref={scroller}
                onScroll={onScroll}
                className={`flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${stale ? 'opacity-60' : ''}`}
              >
                {list.map((r, i) => (
                  <div
                    key={r.movie.imdb_id}
                    className="w-[86%] shrink-0 snap-start animate-[rise_500ms_ease-out_both] motion-reduce:animate-none"
                    style={{ animationDelay: `${i * 90}ms` }}
                  >
                    <MovieCard movie={r.movie} reasons={r.reasons} match={r.match} rank={i + 1} compact />
                  </div>
                ))}
                <div aria-hidden="true" className="w-1 shrink-0" />
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
