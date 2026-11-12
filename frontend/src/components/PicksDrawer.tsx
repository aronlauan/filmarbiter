import { useEffect, useRef, useState, type ReactNode, type Ref } from 'react'
import { flushSync } from 'react-dom'
import { MAX_PICKS, type MovieSummary } from '../api'
import MovieSearch from './MovieSearch'
import PickChips from './PickChips'
import Poster from './Poster'

interface PicksProps {
  picks: MovieSummary[]
  onAdd: (movie: MovieSummary) => void
  onRemove: (imdbId: string) => void
  open: boolean
  onOpenChange: (open: boolean) => void
}

function SearchIcon({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="11" cy="11" r="6.5" />
      <path d="m20 20-4.2-4.2" />
    </svg>
  )
}

/** Tiny poster slots, filled with picks; the collapsed drawer's at-a-glance view. */
function MiniSlots({ picks, className }: { picks: MovieSummary[]; className: string }) {
  return (
    <>
      {picks.map((m) => (
        <Poster key={m.imdb_id} url={m.poster_url} title="" size="w92" className={`${className} rounded-sm shadow-sm ring-2 ring-amber-500/80 dark:ring-amber-400/80`} />
      ))}
      {Array.from({ length: MAX_PICKS - picks.length }, (_, i) => (
        <span key={i} className={`${className} aspect-[2/3] rounded-sm border border-dashed border-stone-400/70 dark:border-stone-600`} />
      ))}
    </>
  )
}

/** Search plus picks: what the drawer holds on every screen size. */
function PicksPanel({
  picks,
  onAdd,
  onRemove,
  searchRef,
  sheet,
}: Pick<PicksProps, 'picks' | 'onAdd' | 'onRemove'> & { searchRef?: Ref<HTMLInputElement>; sheet: boolean }) {
  const full = picks.length >= MAX_PICKS
  const search = (
    <MovieSearch
      ref={searchRef}
      pickedIds={new Set(picks.map((p) => p.imdb_id))}
      disabled={full}
      placeholder={full ? `That's ${MAX_PICKS}. Remove one to swap it out.` : undefined}
      onSelect={onAdd}
      // In the bottom sheet the keyboard sits below, so suggestions open upward.
      listClassName={sheet ? 'bottom-full mb-1 max-h-[min(18rem,45dvh)]' : undefined}
    />
  )
  return sheet ? (
    <div className="space-y-4">
      <PickChips picks={picks} onRemove={onRemove} />
      {search}
    </div>
  ) : (
    <div className="space-y-4">
      {search}
      <PickChips picks={picks} onRemove={onRemove} />
    </div>
  )
}

/**
 * Desktop: a slim rail on the theater's left edge that opens into search and picks
 * on hover (or focus, or "/"). It stays open while you're typing in it; a click on
 * the rail, or the pin, keeps it open until you close it.
 */
export function PicksRail({ picks, onAdd, onRemove, open, onOpenChange, forceOpen = false }: PicksProps & { forceOpen?: boolean }) {
  const rootRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const [pinned, setPinned] = useState(false)
  const pinnedRef = useRef(pinned)
  useEffect(() => {
    pinnedRef.current = pinned || forceOpen
  })
  const closeTimer = useRef<number | undefined>(undefined)
  const shown = open || pinned || forceOpen

  const cancelClose = () => window.clearTimeout(closeTimer.current)
  const scheduleClose = () => {
    cancelClose()
    closeTimer.current = window.setTimeout(() => {
      if (!pinnedRef.current && !rootRef.current?.contains(document.activeElement)) onOpenChange(false)
    }, 280)
  }
  useEffect(() => cancelClose, [])

  /** Open the panel and put the cursor in its search. The panel is inert while
   *  closed, so render it open first. */
  const openAndFocus = useRef<(pin: boolean) => void>(() => {})
  useEffect(() => {
    openAndFocus.current = (pin: boolean) => {
      flushSync(() => {
        if (pin) setPinned(true)
        onOpenChange(true)
      })
      searchRef.current?.focus()
    }
  })

  // "/" anywhere on the page jumps to the search.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.key !== '/' || e.metaKey || e.ctrlKey || t?.closest('input, textarea, [contenteditable]')) return
      e.preventDefault()
      openAndFocus.current(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function close() {
    setPinned(false)
    onOpenChange(false)
    ;(document.activeElement as HTMLElement | null)?.blur()
  }

  return (
    <div
      ref={rootRef}
      className="absolute top-3 bottom-3 left-3 z-20"
      onPointerEnter={(e) => {
        if (e.pointerType !== 'mouse') return
        cancelClose()
        onOpenChange(true)
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === 'mouse') scheduleClose()
      }}
      onFocus={() => {
        cancelClose()
        onOpenChange(true)
      }}
      onBlur={(e) => {
        if (!rootRef.current?.contains(e.relatedTarget as Node | null) && !rootRef.current?.matches(':hover')) scheduleClose()
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') close()
      }}
    >
      <div
        className={`relative h-full overflow-hidden rounded-2xl border border-white/70 bg-white/75 shadow-xl shadow-stone-900/10 backdrop-blur-md transition-[width] duration-300 ease-out motion-reduce:transition-none dark:border-stone-700/60 dark:bg-stone-900/80 dark:shadow-black/40 ${
          shown ? 'w-[22rem]' : 'w-16'
        }`}
      >
        {/* Collapsed: a rail with a search button and your picks at a glance. */}
        <button
          type="button"
          inert={shown}
          aria-label={`Search movies and see your picks (${picks.length} of ${MAX_PICKS})`}
          onClick={() => openAndFocus.current(true)}
          className={`absolute inset-y-0 left-0 flex w-16 flex-col items-center gap-2.5 py-3 transition-opacity duration-150 ${
            shown ? 'opacity-0' : 'opacity-100'
          }`}
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-stone-900 text-white shadow dark:bg-stone-100 dark:text-stone-900">
            <SearchIcon className="h-5 w-5" />
          </span>
          <span className="my-1 h-px w-8 bg-stone-300 dark:bg-stone-700" />
          <MiniSlots picks={picks} className="w-10" />
          <span className="font-mono text-xs text-stone-500 tabular-nums">
            {picks.length}/{MAX_PICKS}
          </span>
        </button>

        {/* Open: search and picks. Fixed width, so the rail's growth reveals it. */}
        <div
          inert={!shown}
          className={`absolute inset-y-0 left-0 flex w-[22rem] flex-col gap-4 p-4 transition-opacity duration-200 ${
            shown ? 'opacity-100 delay-75' : 'opacity-0'
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold tracking-tight">Movie Blender</h2>
              <p className="text-sm text-stone-600 dark:text-stone-400">
                Pick up to {MAX_PICKS} movies with the vibe you're after. We'll find the 3 that best match all of them.
              </p>
            </div>
            {!forceOpen && (
              <button
                type="button"
                onClick={() => (pinned ? close() : setPinned(true))}
                aria-pressed={pinned}
                title={pinned ? 'Close' : 'Keep open'}
                aria-label={pinned ? 'Close search and picks' : 'Keep search and picks open'}
                className="-mt-1 -mr-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-stone-500 hover:bg-stone-200/70 hover:text-stone-900 dark:hover:bg-stone-800 dark:hover:text-white"
              >
                {pinned ? (
                  <span aria-hidden="true">✕</span>
                ) : (
                  <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 17v5M9 3h6l-1 7 3 3v2H7v-2l3-3z" />
                  </svg>
                )}
              </button>
            )}
          </div>
          <PicksPanel picks={picks} onAdd={onAdd} onRemove={onRemove} searchRef={searchRef} sheet={false} />
          <p className="mt-auto text-xs text-stone-500">
            Or click seats on the map to add them. Press <kbd className="rounded border border-stone-300 px-1 font-mono dark:border-stone-700">/</kbd> to search from anywhere.
          </p>
        </div>
      </div>
    </div>
  )
}

/** Vertical swipe on a pointer: the distance moved and whether it counted as a swipe. */
function useSwipe(threshold: number) {
  const start = useRef<number | null>(null)
  const swiped = useRef(false)
  const [drag, setDrag] = useState(0)
  return {
    drag,
    /** True right after a swipe; read (and cleared) by the click that follows it. */
    consumeSwipe() {
      const s = swiped.current
      swiped.current = false
      return s
    },
    handlers(onSwipe: (dy: number) => void, follow: (dy: number) => number) {
      return {
        onPointerDown(e: React.PointerEvent) {
          start.current = e.clientY
          swiped.current = false
          e.currentTarget.setPointerCapture(e.pointerId)
        },
        onPointerMove(e: React.PointerEvent) {
          if (start.current === null) return
          setDrag(follow(e.clientY - start.current))
        },
        onPointerUp(e: React.PointerEvent) {
          if (start.current === null) return
          const dy = e.clientY - start.current
          start.current = null
          setDrag(0)
          if (Math.abs(dy) >= threshold) {
            swiped.current = true
            onSwipe(dy)
          }
        },
        onPointerCancel() {
          start.current = null
          setDrag(0)
        },
      }
    },
  }
}

/**
 * Mobile: a dock along the bottom with your picks at a glance and the Blend button.
 * Tap it or swipe up to open search and picks as a sheet, with the keyboard up and the
 * cursor in the search; swipe down or tap outside to close.
 */
export function PicksDock({ picks, onAdd, onRemove, open, onOpenChange, action }: PicksProps & { action: ReactNode }) {
  const bar = useSwipe(24)
  const sheet = useSwipe(60)
  // The search input, held in state (via a callback ref) so the swipe handlers can use it.
  const [searchInput, setSearchInput] = useState<HTMLInputElement | null>(null)

  /** Open the sheet straight into typing. The sheet is inert while closed, so render it
   *  open first; and focus within the tap itself, or mobile browsers won't raise the keyboard. */
  function openToSearch() {
    flushSync(() => onOpenChange(true))
    searchInput?.focus({ preventScroll: true })
  }

  return (
    <div className="relative z-30 shrink-0">
      {open && (
        <div aria-hidden="true" className="fixed inset-0 bg-stone-950/30" onClick={() => onOpenChange(false)} />
      )}

      <div
        role="dialog"
        aria-label="Search and your picks"
        inert={!open}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onOpenChange(false)
        }}
        style={sheet.drag ? { transform: `translateY(${sheet.drag}px)`, transition: 'none' } : undefined}
        className={`absolute inset-x-0 bottom-full rounded-t-2xl bg-white px-4 pb-4 shadow-[0_-12px_40px_-12px_rgb(0_0_0/0.35)] transition duration-300 ease-out motion-reduce:transition-none dark:bg-stone-900 ${
          open ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-full opacity-0'
        }`}
      >
        <button
          type="button"
          aria-label="Close search and picks"
          className="flex w-full touch-none justify-center pt-2.5 pb-3"
          {...sheet.handlers(
            (dy) => dy > 0 && onOpenChange(false),
            (dy) => Math.max(0, dy),
          )}
          onClick={() => {
            sheet.consumeSwipe()
            onOpenChange(false)
          }}
        >
          <span className="h-1.5 w-10 rounded-full bg-stone-300 dark:bg-stone-700" />
        </button>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="font-semibold">Your picks</h2>
          <span className="text-xs text-stone-500">Up to {MAX_PICKS} · or tap seats on the map</span>
        </div>
        <PicksPanel picks={picks} onAdd={onAdd} onRemove={onRemove} searchRef={setSearchInput} sheet />
      </div>

      <div className="relative flex items-center gap-3 border-t border-stone-200/80 bg-white/90 px-3 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] backdrop-blur-md dark:border-stone-800/80 dark:bg-stone-950/90">
        <button
          type="button"
          aria-expanded={open}
          aria-label={`${open ? 'Close' : 'Open'} search and your picks (${picks.length} of ${MAX_PICKS})`}
          className="relative flex min-w-0 flex-1 touch-none items-center gap-2 py-1 text-left"
          {...bar.handlers(
            (dy) => (dy < 0 ? openToSearch() : onOpenChange(false)),
            () => 0,
          )}
          onClick={() => {
            if (bar.consumeSwipe()) return
            if (open) onOpenChange(false)
            else openToSearch()
          }}
        >
          <span aria-hidden="true" className="absolute -top-1.5 left-1/2 h-1 w-8 -translate-x-1/2 rounded-full bg-stone-300 dark:bg-stone-700" />
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900">
            <SearchIcon className="h-4 w-4" />
          </span>
          {picks.length === 0 ? (
            <span className="truncate text-sm text-stone-500">Search movies to blend</span>
          ) : (
            <span className="flex gap-1">
              <MiniSlots picks={picks} className="w-6" />
            </span>
          )}
        </button>
        {action}
      </div>
    </div>
  )
}
