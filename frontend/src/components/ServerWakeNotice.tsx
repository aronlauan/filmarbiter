import { useEffect, useState } from 'react'
import { checkHealth } from '../api'

/** Show the notice only if the server hasn't answered by then (a warm one answers in ~0.1s). */
const SLOW_MS = 1500
/** While it boots, Render can answer with an error instead of holding the request; try again. */
const RETRY_MS = 3000
const MAX_ATTEMPTS = 20

type State = 'checking' | 'waking' | 'done'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Pings the API on page load. That starts waking a napping server before the visitor
 *  clicks anything, and if the wake-up is slow it says so instead of looking broken. */
export default function ServerWakeNotice() {
  const [state, setState] = useState<State>('checking')

  useEffect(() => {
    const ctl = new AbortController()
    const slow = setTimeout(() => setState((s) => (s === 'checking' ? 'waking' : s)), SLOW_MS)
    void (async () => {
      for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
        try {
          await checkHealth(ctl.signal)
          break
        } catch {
          if (ctl.signal.aborted) return
          await sleep(RETRY_MS)
          if (ctl.signal.aborted) return
        }
      }
      // Awake, or still unreachable: either way the pages report their own errors from here.
      clearTimeout(slow)
      setState('done')
    })()
    return () => {
      ctl.abort()
      clearTimeout(slow)
    }
  }, [])

  if (state !== 'waking') return null
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex justify-center px-4">
      <div
        role="status"
        className="pointer-events-auto flex max-w-md items-start gap-3 rounded-2xl border border-stone-200 bg-white/95 p-4 shadow-xl backdrop-blur dark:border-stone-700 dark:bg-stone-900/95"
      >
        <span
          aria-hidden="true"
          className="mt-0.5 h-5 w-5 shrink-0 rounded-full border-2 border-stone-300 border-t-amber-500 motion-safe:animate-spin dark:border-stone-600 dark:border-t-amber-400"
        />
        <div className="text-sm">
          <p className="font-semibold">Waking up the server…</p>
          <p className="mt-1 text-stone-600 dark:text-stone-400">
            filmarbiter runs entirely on free tiers, so the server naps whenever nobody's around. Give it a minute: it isn't fast, but it is free.
          </p>
        </div>
      </div>
    </div>
  )
}
