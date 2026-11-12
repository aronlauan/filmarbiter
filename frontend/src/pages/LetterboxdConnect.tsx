import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  parseLetterboxdUsername,
  searchLetterboxd,
  startLetterboxdImport,
  verifyLetterboxd,
  type LetterboxdMember,
  type MemberSearchResponse,
  type VerifyResponse,
} from '../api'
import { errorStatus, verifyMessage, type MessageStatus } from '../letterboxd'

const REDIRECT_DELAY_MS = 1200
const KNOWN_ERRORS: MessageStatus[] = ['not_found', 'private', 'invalid', 'unavailable', 'offline', 'error']

function Avatar({ name, url, size }: { name: string; url: string | null; size: 'sm' | 'lg' }) {
  const cls = size === 'lg' ? 'h-14 w-14 text-xl' : 'h-10 w-10 text-base'
  return url ? (
    <img src={url} alt="" className={`${cls} shrink-0 rounded-full object-cover`} />
  ) : (
    <div
      aria-hidden="true"
      className={`${cls} flex shrink-0 items-center justify-center rounded-full bg-stone-200 font-semibold text-stone-700 dark:bg-stone-800 dark:text-stone-200`}
    >
      {name.slice(0, 1).toUpperCase()}
    </div>
  )
}

export default function LetterboxdConnect() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [input, setInput] = useState(params.get('user') ?? '')
  const [searched, setSearched] = useState('')
  // Error passed back from the suggestions page (e.g. a stale link to a deleted account).
  const redirectError = KNOWN_ERRORS.find((s) => s === params.get('error')) ?? null
  const [showRedirectError, setShowRedirectError] = useState(redirectError !== null)

  const search = useMutation<MemberSearchResponse, unknown, string>({ mutationFn: searchLetterboxd })
  // Picking an account from the results verifies it (film count, private or not).
  const verify = useMutation<VerifyResponse, unknown, string>({ mutationFn: verifyLetterboxd })
  // Start the import as soon as the account checks out; the suggestions page picks
  // up the same job (the API reuses running imports).
  const startImport = useMutation({ mutationFn: (u: string) => startLetterboxdImport(u) })

  const profile = verify.data?.status === 'ok' ? verify.data.profile : null
  const hasFilms = (profile?.films_count ?? 0) > 0
  const suggestionsPath = profile ? `/letterboxd/${encodeURIComponent(profile.username)}` : ''
  const candidates = search.data?.results ?? []

  useEffect(() => {
    if (!profile || !hasFilms) return
    const t = setTimeout(() => navigate(suggestionsPath), REDIRECT_DELAY_MS)
    return () => clearTimeout(t)
  }, [profile, hasFilms, navigate, suggestionsPath])

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const query = parseLetterboxdUsername(input)
    if (!query) return
    setSearched(query)
    setShowRedirectError(false)
    verify.reset()
    search.mutate(query)
  }

  function choose(member: LetterboxdMember) {
    verify.mutate(member.username, {
      onSuccess: (r) => {
        if (r.status === 'ok' && r.profile && r.profile.films_count > 0) {
          startImport.mutate(r.profile.username)
        }
      },
    })
  }

  let problem: MessageStatus | null = null
  let problemName = searched || params.get('user') || input
  if (search.isError) problem = errorStatus(search.error)
  else if (search.data?.match === 'none') problem = 'no_results'
  else if (verify.isError) problem = errorStatus(verify.error)
  else if (verify.data && verify.data.status !== 'ok') {
    problem = verify.data.status
    problemName = verify.variables ?? problemName
  } else if (showRedirectError) problem = redirectError

  const busy = search.isPending || verify.isPending

  return (
    <section className="mx-auto max-w-xl space-y-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">Use my Letterboxd</h1>
        <p className="text-stone-600 dark:text-stone-400">
          Enter your Letterboxd username or name and we'll suggest movies based on how you've rated
          what you've already seen. We only read your public profile. No login needed.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-3" noValidate>
        <label htmlFor="lb-username" className="block text-sm font-medium">
          Letterboxd username or name
        </label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            id="lb-username"
            type="text"
            value={input}
            onChange={(e) => {
              setInput(e.target.value)
              // Editing after a result clears it (and cancels a pending redirect).
              if (search.data || search.isError) search.reset()
              if (verify.data || verify.isError) verify.reset()
            }}
            placeholder="yourname or letterboxd.com/yourname"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            maxLength={64}
            aria-describedby="lb-status"
            aria-invalid={problem === 'no_results' || problem === 'not_found' || problem === 'private'}
            className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-4 py-3 text-base shadow-sm outline-none placeholder:text-stone-400 focus:border-stone-500 focus:ring-2 focus:ring-stone-300 dark:border-stone-700 dark:bg-stone-900 dark:focus:ring-stone-700"
          />
          <button
            type="submit"
            disabled={busy || !input.trim() || (profile !== null && hasFilms)}
            className="rounded-lg bg-stone-900 px-6 py-3 font-semibold text-white transition hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-stone-100 dark:text-stone-900 dark:hover:bg-stone-300"
          >
            {search.isPending ? 'Searching…' : 'Find me'}
          </button>
        </div>
      </form>

      <div id="lb-status" aria-live="polite" className="space-y-4">
        {search.isPending && (
          <p className="flex items-center gap-2 text-stone-600 dark:text-stone-400">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-stone-300 border-t-stone-700 dark:border-stone-700 dark:border-t-stone-300" />
            Searching Letterboxd for “{searched}”…
          </p>
        )}

        {problem && !busy && (
          <p
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
          >
            {verifyMessage(problem, problemName)}
          </p>
        )}

        {candidates.length > 0 && !profile && (
          <div className="space-y-3">
            <p className="text-stone-700 dark:text-stone-300">
              {search.data?.match === 'exact'
                ? candidates.length === 1
                  ? 'Is this you?'
                  : 'Which one is you?'
                : `No account matches “${search.data?.query}” exactly. Is it one of these?`}
            </p>
            <ul className="divide-y divide-stone-200 overflow-hidden rounded-xl border border-stone-200 dark:divide-stone-800 dark:border-stone-800">
              {candidates.map((m) => {
                const checking = verify.isPending && verify.variables === m.username
                return (
                  <li key={m.username}>
                    <button
                      type="button"
                      onClick={() => choose(m)}
                      disabled={verify.isPending}
                      className="flex w-full items-center gap-3 bg-white px-4 py-3 text-left transition hover:bg-stone-50 focus-visible:bg-stone-50 focus-visible:outline-none disabled:cursor-wait disabled:opacity-60 dark:bg-stone-900 dark:hover:bg-stone-800 dark:focus-visible:bg-stone-800"
                    >
                      <Avatar name={m.display_name} url={m.avatar_url} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{m.display_name}</span>
                        <span className="block truncate text-sm text-stone-500 dark:text-stone-400">
                          @{m.username}
                          {m.badge && ` · ${m.badge}`}
                        </span>
                      </span>
                      <span className="shrink-0 text-sm font-medium text-stone-600 dark:text-stone-300">
                        {checking ? 'Checking…' : "That's me"}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
            <p className="text-sm text-stone-500 dark:text-stone-400">
              Not listed? Try your exact username, or paste your profile link.
            </p>
          </div>
        )}

        {profile && (
          <div className="flex items-center gap-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950/40">
            <Avatar name={profile.display_name} url={profile.avatar_url} size="lg" />
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-emerald-900 dark:text-emerald-100">
                Found {profile.display_name}
              </p>
              <p className="text-sm text-emerald-800 dark:text-emerald-300">
                @{profile.username} · {profile.films_count.toLocaleString()} films logged
              </p>
              {hasFilms ? (
                <p className="mt-1 text-sm text-emerald-800 dark:text-emerald-300">
                  Taking you to your picks…{' '}
                  <Link to={suggestionsPath} className="font-medium underline">
                    Go now
                  </Link>
                </p>
              ) : (
                <p className="mt-1 text-sm text-amber-800 dark:text-amber-300">
                  This account hasn't logged any films yet, so there's nothing to base picks on.{' '}
                  <Link to={suggestionsPath} className="font-medium underline">
                    Continue anyway
                  </Link>
                  {candidates.length > 1 && (
                    <>
                      {' · '}
                      <button type="button" onClick={() => verify.reset()} className="font-medium underline">
                        Pick another account
                      </button>
                    </>
                  )}
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
