import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useState } from 'react'
import { isServerUnreachable, searchMovies, SERVER_UNREACHABLE, type MovieSummary } from '../api'
import Poster from './Poster'

interface Props {
  onSelect: (movie: MovieSummary) => void
  pickedIds: Set<string>
  disabled?: boolean
  placeholder?: string
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

/** Title autocomplete (ARIA combobox). */
export default function MovieSearch({ onSelect, pickedIds, disabled, placeholder }: Props) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const listId = useId()
  const term = useDebounced(text.trim(), 250)

  const { data = [], isFetching, isError, error } = useQuery({
    queryKey: ['search', term],
    queryFn: ({ signal }) => searchMovies(term, signal),
    enabled: term.length >= 2,
    staleTime: 5 * 60_000,
  })
  const results = term.length >= 2 ? data : []
  const showList = open && term.length >= 2

  function choose(movie: MovieSummary) {
    if (pickedIds.has(movie.imdb_id)) return
    onSelect(movie)
    setText('')
    setOpen(false)
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setActive((i) => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && showList && results[active]) {
      e.preventDefault()
      choose(results[active])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="relative">
      <input
        type="search"
        role="combobox"
        aria-label="Search for a movie"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && results[active] ? `${listId}-${active}` : undefined}
        value={text}
        disabled={disabled}
        placeholder={placeholder ?? 'Search for a movie…'}
        onChange={(e) => {
          setText(e.target.value)
          setActive(0)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
        className="w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base shadow-sm outline-none placeholder:text-stone-400 focus:border-stone-500 focus:ring-2 focus:ring-stone-300 disabled:cursor-not-allowed disabled:opacity-60 dark:border-stone-700 dark:bg-stone-900 dark:focus:border-stone-500 dark:focus:ring-stone-700"
      />

      {showList && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 max-h-96 w-full overflow-auto rounded-lg border border-stone-200 bg-white py-1 shadow-lg dark:border-stone-700 dark:bg-stone-900"
        >
          {results.map((m, i) => {
            const picked = pickedIds.has(m.imdb_id)
            return (
              <li
                key={m.imdb_id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                aria-disabled={picked}
                // mousedown (not click) so the input's blur doesn't close the list first
                onMouseDown={(e) => {
                  e.preventDefault()
                  choose(m)
                }}
                onMouseEnter={() => setActive(i)}
                className={`flex cursor-pointer items-center gap-3 px-3 py-2 ${
                  i === active ? 'bg-stone-100 dark:bg-stone-800' : ''
                } ${picked ? 'cursor-default opacity-50' : ''}`}
              >
                <Poster url={m.poster_url} title={m.title} size="w92" className="w-8 shrink-0 rounded" />
                <span className="min-w-0 flex-1 truncate">
                  {m.title}
                  {m.year && <span className="text-stone-500"> ({m.year})</span>}
                </span>
                {picked && <span className="text-xs text-stone-500">Added</span>}
              </li>
            )
          })}
          {results.length === 0 && (
            <li className="px-3 py-2 text-sm text-stone-500">
              {isError
                ? isServerUnreachable(error)
                  ? SERVER_UNREACHABLE
                  : 'Search failed. Try again.'
                : isFetching
                  ? 'Searching…'
                  : 'No movies found.'}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
