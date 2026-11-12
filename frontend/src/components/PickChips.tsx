import { MAX_PICKS, type MovieSummary } from '../api'
import Poster from './Poster'

interface Props {
  picks: MovieSummary[]
  onRemove: (imdbId: string) => void
}

/** Selected movies as poster tiles, with empty slots up to MAX_PICKS. */
export default function PickChips({ picks, onRemove }: Props) {
  const empty = MAX_PICKS - picks.length
  return (
    <ul className="grid grid-cols-5 gap-2 sm:gap-3" aria-label="Your picks">
      {picks.map((m) => (
        <li key={m.imdb_id} className="group relative">
          <Poster url={m.poster_url} title={m.title} size="w185" className="w-full rounded-md shadow" />
          <p className="mt-1 truncate text-xs text-stone-600 dark:text-stone-400" title={m.title}>
            {m.title}
          </p>
          <button
            type="button"
            onClick={() => onRemove(m.imdb_id)}
            aria-label={`Remove ${m.title}`}
            className="absolute top-1 right-1 flex h-7 w-7 items-center justify-center rounded-full bg-black/70 text-sm text-white hover:bg-black focus-visible:outline-2 focus-visible:outline-white"
          >
            ✕
          </button>
        </li>
      ))}
      {Array.from({ length: empty }, (_, i) => (
        <li
          key={`empty-${i}`}
          aria-hidden="true"
          className="aspect-[2/3] rounded-md border-2 border-dashed border-stone-300 dark:border-stone-700"
        />
      ))}
    </ul>
  )
}
