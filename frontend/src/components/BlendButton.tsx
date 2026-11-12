import { MAX_PICKS } from '../api'

interface Props {
  count: number
  pending: boolean
  /** The shown results belong to an older set of picks. */
  stale: boolean
  /** Show the picks count (the mobile dock already shows the picks). */
  showCount?: boolean
  onClick: () => void
  className?: string
}

/** A countertop blender: lid, jar with handle, blades, motor base. While blending,
 *  it jiggles on the counter and its blades whirl. */
function BlendIcon({ spinning }: { spinning: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={`-my-1 h-6 w-6 shrink-0 ${spinning ? 'animate-[jiggle_180ms_linear_infinite] motion-reduce:animate-none' : ''}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* Lid with its cap */}
      <path d="M6 3.5h10M10 3.5V2h2v1.5" />
      {/* Jar, narrowing toward the base */}
      <path d="M6 5.5h10l-1.4 9H7.4z" />
      {/* Handle */}
      <path d="M15.7 7.5H18.5v4.5h-3.5" />
      {/* Blades */}
      <g className={`origin-center [transform-box:fill-box] ${spinning ? 'animate-[whirl_120ms_linear_infinite] motion-reduce:animate-none' : ''}`}>
        <path d="M8.8 11.2 11 12.4l2.2-1.2M11 12.4v1.4" />
      </g>
      {/* Motor base with a dial */}
      <path d="M6.5 14.5h9l1 7h-11z" />
      <circle cx="11" cy="18" r="1.2" />
    </svg>
  )
}

/** The Blender's main action, kept apart from search and picks so it's always easy to find.
 *  Callers position it (`relative`, `absolute`, …) through `className`. */
export default function BlendButton({ count, pending, stale, showCount = true, onClick, className = '' }: Props) {
  const label = pending ? 'Blending…' : stale ? 'Blend again' : 'Blend'
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={count === 0 || pending}
      className={`flex items-center justify-center gap-2 rounded-full bg-amber-500 px-6 py-3 font-semibold text-stone-950 shadow-lg shadow-amber-600/25 transition hover:bg-amber-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-500 active:scale-[0.97] disabled:cursor-not-allowed disabled:bg-stone-300 disabled:text-stone-500 disabled:shadow-none dark:bg-amber-400 dark:hover:bg-amber-300 dark:disabled:bg-stone-800 dark:disabled:text-stone-500 ${className}`}
    >
      {stale && !pending && (
        <span
          aria-hidden="true"
          className="absolute inset-0 animate-ping rounded-full bg-amber-400/40 [animation-duration:2s] motion-reduce:hidden"
        />
      )}
      <BlendIcon spinning={pending} />
      <span className="relative">{label}</span>
      {showCount && (
      <span className="relative rounded-full bg-stone-950/10 px-2 py-0.5 font-mono text-xs tabular-nums dark:bg-stone-950/15">
        {count}/{MAX_PICKS}
      </span>
      )}
    </button>
  )
}
