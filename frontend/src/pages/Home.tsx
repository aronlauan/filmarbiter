import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { posterSrc, rollMovies, type RolledMovie } from '../api'
import { BlendIcon } from '../components/BlendButton'
import MovieCloud, { type CloudPhase } from '../components/MovieCloud'
import { LETTERBOXD_ENABLED } from '../features'
import { useMediaQuery } from '../hooks'

/** Every throw deals movies from each of these genres. */
const GENRES = ['Comedy', 'Action', 'Drama', 'Horror', 'Thriller', 'Romance', 'Sci-Fi', 'Animation', 'Crime', 'Mystery']
/** Movies per genre in each throw: 30 in all, enough to fill out the cloud. */
const PER_GENRE = 1
const COUNT = GENRES.length * PER_GENRE

/** Remember this many recent movies (6 throws' worth) so spinning again doesn't repeat them. */
const HISTORY = 180
/** Keep the posters shaking at least this long (gathering takes the first ~400ms). */
const SHAKE_MS = 1200

function shuffled<T>(items: T[]): T[] {
  const a = [...items]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

/** The last throw (and recent history) outlives Home unmounting, so leaving for another tab
 *  and coming back shows the same movies. Only Spin Again deals new ones. */
const SAVED_KEY = 'filmarbiter:home-roll'
type SavedRoll = { rolled: RolledMovie[]; history: string[] }

function loadSaved(): SavedRoll | null {
  try {
    const raw = sessionStorage.getItem(SAVED_KEY)
    if (!raw) return null
    const saved = JSON.parse(raw) as SavedRoll
    return Array.isArray(saved.rolled) && saved.rolled.length && Array.isArray(saved.history) ? saved : null
  } catch {
    return null
  }
}

function save(roll: SavedRoll) {
  try {
    sessionStorage.setItem(SAVED_KEY, JSON.stringify(roll))
  } catch {
    // Storage unavailable: the throw just won't survive leaving the page.
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Resolves once the image is in the browser cache (or failed, or took too long),
 *  so posters land with their pictures instead of popping in after. */
function preload(src: string | null): Promise<void> {
  if (!src) return Promise.resolve()
  return new Promise((resolve) => {
    const img = new Image()
    const done = () => resolve()
    img.onload = img.onerror = done
    setTimeout(done, 2500)
    img.src = src
  })
}

function ShuffleIcon({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7h3.5c2 0 3.2 1 4.3 2.7l2.4 4.6C14.3 16 15.5 17 17.5 17H21M18 14l3 3-3 3" />
      <path d="M3 17h3.5c1.4 0 2.4-.5 3.2-1.4M14.3 8.4C15.1 7.5 16.1 7 17.5 7H21M18 4l3 3-3 3" />
    </svg>
  )
}

function StarIcon({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
      <path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" />
    </svg>
  )
}

/** A big, colorful way into one of the app's tailored modes. */
function ModeButton({ to, icon, title, body, className }: { to: string; icon: ReactNode; title: string; body: string; className: string }) {
  return (
    <Link
      to={to}
      className={`group flex items-center gap-4 rounded-3xl p-5 text-left text-white shadow-xl transition hover:-translate-y-1 hover:shadow-2xl focus-visible:outline-2 focus-visible:outline-offset-4 active:translate-y-0 active:scale-[0.98] sm:gap-5 sm:p-6 ${className}`}
    >
      <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white/20 ring-1 ring-white/30 sm:h-16 sm:w-16">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-xl font-bold tracking-tight sm:text-2xl">{title}</span>
        <span className="mt-0.5 block text-sm text-white/85">{body}</span>
      </span>
      <span
        aria-hidden="true"
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white text-xl font-bold text-stone-900 shadow transition group-hover:translate-x-1"
      >
        →
      </span>
    </Link>
  )
}

export default function Home() {
  const [saved] = useState(loadSaved)
  const [rolled, setRolled] = useState<RolledMovie[]>(saved?.rolled ?? [])
  const [phase, setPhase] = useState<CloudPhase>(saved ? 'spread' : 'shaking')
  /** The poster flipped open in the cloud, if any. */
  const [opened, setOpened] = useState<RolledMovie | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
  const history = useRef<string[]>(saved?.history ?? [])
  const rollId = useRef(0)

  const roll = useCallback(async () => {
    const id = ++rollId.current // a newer roll makes this one's result moot
    setPhase('shaking')
    try {
      const [dealt] = await Promise.all([
        rollMovies(GENRES, PER_GENRE, history.current).then(async (rs) => {
          await Promise.all(rs.map((r) => preload(posterSrc(r.movie.poster_url, 'w185'))))
          return shuffled(rs) // mix the genres around the cloud
        }),
        sleep(reducedMotion ? 0 : SHAKE_MS),
      ])
      if (id !== rollId.current) return
      if (dealt.length === 0) {
        setError('No movies to deal right now.')
      } else {
        setError(null)
        setRolled(dealt)
        const ids = dealt.map((r) => r.movie.imdb_id)
        history.current = [...ids, ...history.current.filter((x) => !ids.includes(x))].slice(0, HISTORY)
        save({ rolled: dealt, history: history.current })
      }
    } catch (err) {
      if (id !== rollId.current) return
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    }
    setPhase('spread')
  }, [reducedMotion])

  // Throw the first handful right away, unless an earlier throw is still on the table.
  const started = useRef(saved !== null)
  useEffect(() => {
    if (started.current) return
    started.current = true
    void roll()
  }, [roll])

  // The "more below" hint bows out once the visitor has started scrolling.
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Face-down cards to shake before the first throw lands.
  const items: (RolledMovie | null)[] = rolled.length ? rolled : Array(COUNT).fill(null)
  const glow = posterSrc((opened ?? rolled[0])?.movie.poster_url ?? null, 'w92')

  return (
    <div className="space-y-16">
      {/* Sized to the screen (under the header and page padding), so the whole cloud fits without scrolling. */}
      <section className="relative isolate flex h-[calc(100dvh-7.5rem)] min-h-[26rem] flex-col">
        {/* The flipped (or first) poster, blurred into a soft glow behind everything. */}
        {glow && (
          <div
            key={glow}
            aria-hidden="true"
            className="pointer-events-none absolute -inset-x-8 -top-16 -bottom-8 -z-10 animate-[fade_700ms_ease-out] bg-cover bg-center opacity-25 blur-3xl saturate-150 motion-reduce:animate-none dark:opacity-20"
            style={{ backgroundImage: `url(${glow})` }}
          />
        )}

        <header className="shrink-0 text-center">
          <h1 className="text-3xl font-bold tracking-tight sm:text-5xl">Just pick a movie already.</h1>
          <p className="mt-1.5 text-sm text-stone-600 sm:text-base dark:text-stone-400">Tap a poster in the cloud to flip it.</p>
        </header>

        {/* The cloud: posters gather and shake here, then burst out into a sphere you can spin. */}
        <div className="relative my-3 min-h-0 flex-1 sm:my-5">
          <MovieCloud items={items} phase={phase} reducedMotion={reducedMotion} onOpenChange={setOpened} />
        </div>

        <div className="flex shrink-0 flex-col items-center gap-2">
          <button
            type="button"
            onClick={() => void roll()}
            className="flex items-center gap-3 rounded-full bg-amber-500 px-7 py-3 text-lg font-semibold text-stone-950 shadow-lg shadow-amber-600/30 transition hover:-translate-y-0.5 hover:bg-amber-400 hover:shadow-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-500 active:translate-y-0 active:scale-[0.97] sm:px-8 sm:py-4 dark:bg-amber-400 dark:hover:bg-amber-300"
          >
            <ShuffleIcon className="h-6 w-6 shrink-0" />
            {rolled.length ? 'Spin Again' : 'Spin'}
          </button>
          {error && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-400">
              {error}
            </p>
          )}
          {/* The cloud fills the first screen, so point the way to what's below it. */}
          <a
            href="#more"
            onClick={(e) => {
              e.preventDefault()
              document.getElementById('more')?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth' })
            }}
            aria-hidden={scrolled}
            tabIndex={scrolled ? -1 : undefined}
            className={`group mt-1 flex flex-col items-center text-base font-bold tracking-wide transition-opacity duration-300 sm:mt-2 sm:text-lg ${
              scrolled ? 'pointer-events-none opacity-0' : ''
            }`}
          >
            <span className="text-stone-800 transition-colors group-hover:text-amber-700 dark:text-stone-100 dark:group-hover:text-amber-300">Or pick a movie a different way</span>
            <svg
              viewBox="0 0 24 24"
              aria-hidden="true"
              className="-mt-0.5 h-6 w-6 animate-[nudge_1.6s_ease-in-out_infinite] text-amber-600 motion-reduce:animate-none dark:text-amber-400"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </a>
        </div>
      </section>

      <section id="more" className="scroll-mt-6">
        <h2 className="text-center text-2xl font-bold tracking-tight sm:text-left">Get picks made for you</h2>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <ModeButton
            to="/blend"
            icon={<BlendIcon className="h-8 w-8 sm:h-9 sm:w-9" />}
            title="The Blender"
            body="Mix up to 5 favorites into 3 movies that match them all."
            className="bg-linear-to-br from-sky-500 to-indigo-600 shadow-indigo-600/25 focus-visible:outline-indigo-500"
          />
          <ModeButton
            to="/letterboxd"
            icon={<StarIcon className="h-8 w-8 sm:h-9 sm:w-9" />}
            title="Your Letterboxd"
            body={LETTERBOXD_ENABLED ? "Get picks based on how you've rated films." : 'Coming soon…'}
            className="bg-linear-to-br from-emerald-500 to-teal-700 shadow-emerald-700/25 focus-visible:outline-emerald-500"
          />
        </div>
      </section>
    </div>
  )
}
