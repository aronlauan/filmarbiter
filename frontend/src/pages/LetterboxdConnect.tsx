import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  parseLetterboxdUsername,
  startLetterboxdImport,
  verifyLetterboxd,
  type VerifyResponse,
  type VerifyStatus,
} from '../api'
import { errorStatus, verifyMessage } from '../letterboxd'

const REDIRECT_DELAY_MS = 1200
type MessageStatus = VerifyStatus | 'unavailable' | 'error'
const KNOWN_ERRORS: MessageStatus[] = ['not_found', 'private', 'invalid', 'unavailable', 'error']

export default function LetterboxdConnect() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [input, setInput] = useState(params.get('user') ?? '')
  const [checked, setChecked] = useState('')
  // Error passed back from the suggestions page (e.g. a stale link to a deleted account).
  const redirectError = KNOWN_ERRORS.find((s) => s === params.get('error')) ?? null
  const [showRedirectError, setShowRedirectError] = useState(redirectError !== null)

  const verify = useMutation<VerifyResponse, unknown, string>({ mutationFn: verifyLetterboxd })
  // Start the import as soon as the account checks out; the suggestions page picks
  // up the same job (the API reuses running imports).
  const startImport = useMutation({ mutationFn: (u: string) => startLetterboxdImport(u) })

  const profile = verify.data?.status === 'ok' ? verify.data.profile : null
  const hasFilms = (profile?.films_count ?? 0) > 0
  const suggestionsPath = profile ? `/letterboxd/${encodeURIComponent(profile.username)}` : ''

  useEffect(() => {
    if (!profile || !hasFilms) return
    const t = setTimeout(() => navigate(suggestionsPath), REDIRECT_DELAY_MS)
    return () => clearTimeout(t)
  }, [profile, hasFilms, navigate, suggestionsPath])

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const username = parseLetterboxdUsername(input)
    if (!username) return
    setChecked(username)
    setShowRedirectError(false)
    verify.mutate(username, {
      onSuccess: (r) => {
        if (r.status === 'ok' && r.profile && r.profile.films_count > 0) {
          startImport.mutate(r.profile.username)
        }
      },
    })
  }

  let problem: MessageStatus | null = null
  if (verify.isError) problem = errorStatus(verify.error)
  else if (verify.data && verify.data.status !== 'ok') problem = verify.data.status
  else if (showRedirectError) problem = redirectError

  return (
    <section className="mx-auto max-w-xl space-y-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">Use my Letterboxd</h1>
        <p className="text-stone-600 dark:text-stone-400">
          Enter your Letterboxd username and we'll suggest movies based on how you've rated what you've
          already seen. We only read your public profile. No login needed.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-3" noValidate>
        <label htmlFor="lb-username" className="block text-sm font-medium">
          Letterboxd username
        </label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            id="lb-username"
            type="text"
            value={input}
            onChange={(e) => {
              setInput(e.target.value)
              // Editing after a result clears it (and cancels a pending redirect).
              if (verify.data || verify.isError) verify.reset()
            }}
            placeholder="yourname or letterboxd.com/yourname"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            aria-describedby="lb-status"
            aria-invalid={problem !== null && problem !== 'unavailable'}
            className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-4 py-3 text-base shadow-sm outline-none placeholder:text-stone-400 focus:border-stone-500 focus:ring-2 focus:ring-stone-300 dark:border-stone-700 dark:bg-stone-900 dark:focus:ring-stone-700"
          />
          <button
            type="submit"
            disabled={verify.isPending || !input.trim() || (profile !== null && hasFilms)}
            className="rounded-lg bg-stone-900 px-6 py-3 font-semibold text-white transition hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-stone-100 dark:text-stone-900 dark:hover:bg-stone-300"
          >
            {verify.isPending ? 'Checking…' : 'Find me'}
          </button>
        </div>
      </form>

      <div id="lb-status" aria-live="polite">
        {verify.isPending && (
          <p className="flex items-center gap-2 text-stone-600 dark:text-stone-400">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-stone-300 border-t-stone-700 dark:border-stone-700 dark:border-t-stone-300" />
            Checking Letterboxd for “{checked}”…
          </p>
        )}

        {problem && !verify.isPending && (
          <p
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
          >
            {verifyMessage(problem, checked || params.get('user') || input)}
          </p>
        )}

        {profile && (
          <div className="flex items-center gap-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950/40">
            {profile.avatar_url ? (
              <img src={profile.avatar_url} alt="" className="h-14 w-14 shrink-0 rounded-full object-cover" />
            ) : (
              <div
                aria-hidden="true"
                className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-emerald-200 text-xl font-semibold text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100"
              >
                {profile.display_name.slice(0, 1).toUpperCase()}
              </div>
            )}
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
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
