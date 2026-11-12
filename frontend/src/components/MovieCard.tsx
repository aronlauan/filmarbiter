import type { BecauseFilm, MatchReasons, MovieDetail } from '../api'
import { stars } from '../letterboxd'
import Poster from './Poster'

interface Props {
  movie: MovieDetail
  reasons?: MatchReasons
  /** Letterboxd: the user's films this pick is based on. */
  because?: BecauseFilm[]
  rank?: number
  /** Blender: match percentage, shown on the poster. */
  match?: number
  /** Tighter layout for narrow trays: smaller poster, shorter overview, no cast line. */
  compact?: boolean
}

function formatRuntime(min: number | null): string | null {
  if (!min) return null
  const h = Math.floor(min / 60)
  return h ? `${h}h ${min % 60}m` : `${min}m`
}

/** "Shares: heist, bank robbery · Crime · Michael Mann (director)" */
function reasonsText(r: MatchReasons): string | null {
  const parts = [r.keywords.join(', '), r.genres.join('/'), r.people.join(', ')].filter(Boolean)
  return parts.length ? parts.join(' · ') : null
}

export default function MovieCard({ movie: m, reasons, because, rank, match, compact = false }: Props) {
  const why = reasons ? reasonsText(reasons) : null
  const meta = [
    m.year,
    formatRuntime(m.runtime_minutes),
    m.imdb_rating ? `★ ${m.imdb_rating.toFixed(1)} IMDb` : null,
  ].filter(Boolean)
  const directors = m.directors.map((d) => d.name).join(', ')
  const cast = m.cast.slice(0, 3).map((c) => c.name).join(', ')

  return (
    <article
      className={`flex h-full items-start rounded-xl border border-stone-200 bg-white shadow-sm dark:border-stone-800 dark:bg-stone-900 ${
        compact ? 'gap-3 p-3' : 'gap-4 p-4 sm:gap-5'
      }`}
    >
      <div className={`relative shrink-0 ${compact ? 'w-16' : 'w-24 sm:w-32'}`}>
        <Poster url={m.poster_url} title={m.title} size="w185" className="w-full rounded-md" />
        {match !== undefined && (
          <p
            title="How well this fits all of your picks"
            className={`absolute inset-x-1 bottom-1 rounded bg-sky-600/95 text-center leading-tight font-semibold text-white shadow tabular-nums backdrop-blur-sm dark:bg-sky-500/95 ${
              compact ? 'py-0.5 text-[11px]' : 'py-1 text-sm'
            }`}
          >
            {match}%<span className={compact ? 'sr-only' : 'font-normal'}> match</span>
          </p>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <h3 className={`leading-tight font-semibold ${compact ? 'text-base' : 'text-lg'}`}>
          {rank !== undefined && <span className="text-stone-400">{rank}. </span>}
          {m.title}
        </h3>
        {m.original_title && !compact && <p className="text-sm text-stone-500 italic">{m.original_title}</p>}
        <p className="mt-1 text-sm text-stone-600 dark:text-stone-400">{meta.join(' · ')}</p>
        {m.genres.length > 0 && (
          <p className="text-sm text-stone-600 dark:text-stone-400">{m.genres.join(', ')}</p>
        )}

        {because && because.length > 0 && (
          <p className="mt-2 text-sm text-stone-700 dark:text-stone-300">
            <span className="font-medium">Because you rated </span>
            {because.map((b, i) => (
              <span key={b.imdb_id}>
                {i > 0 && ', '}
                {b.title}
                {b.rating !== null && (
                  <>
                    {' '}
                    <span aria-hidden="true" className="text-emerald-700 dark:text-emerald-400">
                      {stars(b.rating)}
                    </span>
                    <span className="sr-only">{b.rating} out of 5</span>
                  </>
                )}
                {b.liked && (
                  <>
                    {' '}
                    <span aria-hidden="true" className="text-orange-600 dark:text-orange-400">
                      ♥
                    </span>
                    <span className="sr-only">(liked)</span>
                  </>
                )}
              </span>
            ))}
          </p>
        )}

        {why && (
          <p className={`mt-2 rounded-md bg-amber-50 px-2 py-1 text-sm ${compact ? 'line-clamp-2' : ''} text-amber-900 dark:bg-amber-950/50 dark:text-amber-200`}>
            <span className="font-medium">Why: </span>
            {why}
          </p>
        )}

        {m.overview && (
          <p className={`mt-2 text-sm ${compact ? 'line-clamp-2' : 'line-clamp-4'} text-stone-700 dark:text-stone-300`}>{m.overview}</p>
        )}
        {(directors || cast) && !compact && (
          <p className="mt-2 text-xs text-stone-500">
            {directors && <>Dir. {directors}</>}
            {directors && cast && ' · '}
            {cast}
          </p>
        )}

        <p className={`flex gap-4 text-sm ${compact ? 'mt-2' : 'mt-3'}`}>
          <a href={m.letterboxd_url} target="_blank" rel="noreferrer" className="font-medium underline-offset-2 hover:underline">
            Letterboxd ↗
          </a>
          <a href={m.imdb_url} target="_blank" rel="noreferrer" className="font-medium underline-offset-2 hover:underline">
            IMDb ↗
          </a>
        </p>
      </div>
    </article>
  )
}

export function MovieCardSkeleton({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`flex h-full animate-pulse rounded-xl border border-stone-200 dark:border-stone-800 ${
        compact ? 'gap-3 p-3' : 'gap-4 p-4 sm:gap-5'
      }`}
      aria-hidden="true"
    >
      <div className={`aspect-[2/3] shrink-0 rounded-md bg-stone-200 dark:bg-stone-800 ${compact ? 'w-16' : 'w-24 sm:w-32'}`} />
      <div className="flex-1 space-y-3 py-1">
        <div className="h-5 w-2/3 rounded bg-stone-200 dark:bg-stone-800" />
        <div className="h-4 w-1/3 rounded bg-stone-200 dark:bg-stone-800" />
        <div className="h-4 w-full rounded bg-stone-200 dark:bg-stone-800" />
        <div className="h-4 w-5/6 rounded bg-stone-200 dark:bg-stone-800" />
      </div>
    </div>
  )
}
