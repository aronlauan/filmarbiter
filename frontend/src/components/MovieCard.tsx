import type { MatchReasons, MovieDetail } from '../api'
import Poster from './Poster'

interface Props {
  movie: MovieDetail
  reasons?: MatchReasons
  rank?: number
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

export default function MovieCard({ movie: m, reasons, rank }: Props) {
  const why = reasons ? reasonsText(reasons) : null
  const meta = [
    m.year,
    formatRuntime(m.runtime_minutes),
    m.imdb_rating ? `★ ${m.imdb_rating.toFixed(1)} IMDb` : null,
  ].filter(Boolean)
  const directors = m.directors.map((d) => d.name).join(', ')
  const cast = m.cast.slice(0, 3).map((c) => c.name).join(', ')

  return (
    <article className="flex items-start gap-4 rounded-xl border border-stone-200 bg-white p-4 shadow-sm sm:gap-5 dark:border-stone-800 dark:bg-stone-900">
      <Poster url={m.poster_url} title={m.title} size="w185" className="w-24 shrink-0 rounded-md sm:w-32" />
      <div className="min-w-0 flex-1">
        <h3 className="text-lg leading-tight font-semibold">
          {rank !== undefined && <span className="text-stone-400">{rank}. </span>}
          {m.title}
        </h3>
        {m.original_title && <p className="text-sm text-stone-500 italic">{m.original_title}</p>}
        <p className="mt-1 text-sm text-stone-600 dark:text-stone-400">{meta.join(' · ')}</p>
        {m.genres.length > 0 && (
          <p className="text-sm text-stone-600 dark:text-stone-400">{m.genres.join(', ')}</p>
        )}

        {why && (
          <p className="mt-2 rounded-md bg-amber-50 px-2 py-1 text-sm text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
            <span className="font-medium">Why: </span>
            {why}
          </p>
        )}

        {m.overview && (
          <p className="mt-2 line-clamp-4 text-sm text-stone-700 dark:text-stone-300">{m.overview}</p>
        )}
        {(directors || cast) && (
          <p className="mt-2 text-xs text-stone-500">
            {directors && <>Dir. {directors}</>}
            {directors && cast && ' · '}
            {cast}
          </p>
        )}

        <p className="mt-3 flex gap-4 text-sm">
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

export function MovieCardSkeleton() {
  return (
    <div className="flex animate-pulse gap-4 rounded-xl border border-stone-200 p-4 sm:gap-5 dark:border-stone-800" aria-hidden="true">
      <div className="aspect-[2/3] w-24 shrink-0 rounded-md bg-stone-200 sm:w-32 dark:bg-stone-800" />
      <div className="flex-1 space-y-3 py-1">
        <div className="h-5 w-2/3 rounded bg-stone-200 dark:bg-stone-800" />
        <div className="h-4 w-1/3 rounded bg-stone-200 dark:bg-stone-800" />
        <div className="h-4 w-full rounded bg-stone-200 dark:bg-stone-800" />
        <div className="h-4 w-5/6 rounded bg-stone-200 dark:bg-stone-800" />
      </div>
    </div>
  )
}
