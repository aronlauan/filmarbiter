import { ApiError, type VerifyStatus } from './api'

/** 4.5 -> "★★★★½" (Letterboxd's own notation). */
export function stars(rating: number | null): string {
  if (rating === null) return ''
  const full = Math.floor(rating)
  return '★'.repeat(full) + (rating - full >= 0.5 ? '½' : '')
}

/** User-facing message for a verification outcome that isn't "ok". */
export function verifyMessage(status: VerifyStatus | 'unavailable' | 'error', username: string): string {
  switch (status) {
    case 'not_found':
      return `We couldn't find a Letterboxd user named "${username}". Check the spelling.`
    case 'private':
      return `"${username}"'s profile is private, so we can't see their films.`
    case 'invalid':
      return 'Letterboxd usernames only use letters, numbers and underscores.'
    case 'unavailable':
      return "Letterboxd isn't responding right now. Try again in a minute."
    default:
      return 'Something went wrong. Try again.'
  }
}

/** Map a thrown verify/import error to a message status. */
export function errorStatus(err: unknown): 'unavailable' | 'error' {
  return err instanceof ApiError && (err.status === 503 || err.status === 0) ? 'unavailable' : 'error'
}

export function importErrorMessage(error: string | null): string {
  switch (error) {
    case 'not_found':
      return 'That Letterboxd account no longer exists.'
    case 'private':
      return 'That profile is private, so we can’t see its films.'
    case 'letterboxd_unavailable':
      return 'Letterboxd stopped responding while we were reading your films. Try again in a minute.'
    case 'interrupted':
      return 'The import was interrupted. Try again.'
    default:
      return 'Something went wrong while importing your films. Try again.'
  }
}
