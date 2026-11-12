import { ApiError, SERVER_UNREACHABLE, type VerifyStatus } from './api'

/** 4.5 -> "★★★★½" (Letterboxd's own notation). */
export function stars(rating: number | null): string {
  if (rating === null) return ''
  const full = Math.floor(rating)
  return '★'.repeat(full) + (rating - full >= 0.5 ? '½' : '')
}

export type MessageStatus = VerifyStatus | 'no_results' | 'unavailable' | 'offline' | 'error'

/** User-facing message for a verification outcome that isn't "ok". */
export function verifyMessage(status: MessageStatus, username: string): string {
  switch (status) {
    case 'no_results':
      return `No Letterboxd accounts match "${username}". Check the spelling, or try your username instead of your name.`
    case 'not_found':
      return `We couldn't find a Letterboxd user named "${username}". Check the spelling.`
    case 'private':
      return `"${username}"'s profile is private, so we can't see their films.`
    case 'invalid':
      return 'Letterboxd usernames only use letters, numbers and underscores.'
    case 'unavailable':
      return "Letterboxd isn't responding right now. Try again in a minute."
    case 'offline':
      return SERVER_UNREACHABLE
    default:
      return 'Something went wrong. Try again.'
  }
}

/** Map a thrown verify/import error to a message status. */
export function errorStatus(err: unknown): 'unavailable' | 'offline' | 'error' {
  if (!(err instanceof ApiError)) return 'error'
  if (err.status === 0) return 'offline' // our server, not Letterboxd
  return err.status === 503 ? 'unavailable' : 'error'
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
