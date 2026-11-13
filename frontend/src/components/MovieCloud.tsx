import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import { posterSrc, type RolledMovie } from '../api'
import { useElementSize } from '../hooks'

/** shaking: gathered in the middle, rattling. spread: thrown out into a turning cloud. */
export type CloudPhase = 'shaking' | 'spread'

interface Props {
  /** null entries are face-down cards, shown before the first throw lands. */
  items: (RolledMovie | null)[]
  phase: CloudPhase
  reducedMotion: boolean
  /** Told which movie is flipped open (or null), e.g. to tint the page around it. */
  onOpenChange?: (rolled: RolledMovie | null) => void
}

// --- 3D maths: points on a unit sphere, turned by a 3x3 rotation matrix ---------

type Vec = [number, number, number]
/** Row-major 3x3 matrix. */
type Mat = number[]

const IDENTITY: Mat = [1, 0, 0, 0, 1, 0, 0, 0, 1]

function mul(a: Mat, b: Mat): Mat {
  const out = new Array<number>(9)
  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 3; c++) {
      out[r * 3 + c] = a[r * 3] * b[c] + a[r * 3 + 1] * b[3 + c] + a[r * 3 + 2] * b[6 + c]
    }
  }
  return out
}

function apply(m: Mat, [x, y, z]: Vec): Vec {
  return [m[0] * x + m[1] * y + m[2] * z, m[3] * x + m[4] * y + m[5] * z, m[6] * x + m[7] * y + m[8] * z]
}

/** Turn about the screen's vertical axis: positive moves the front of the cloud right. */
function rotY(t: number): Mat {
  const c = Math.cos(t), s = Math.sin(t)
  return [c, 0, s, 0, 1, 0, -s, 0, c]
}

/** Turn about the screen's horizontal axis: negative moves the front of the cloud down. */
function rotX(t: number): Mat {
  const c = Math.cos(t), s = Math.sin(t)
  return [1, 0, 0, 0, c, -s, 0, s, c]
}

/** Turn by angle t about a unit axis (Rodrigues' formula). */
function rotAxis([x, y, z]: Vec, t: number): Mat {
  const c = Math.cos(t), s = Math.sin(t), C = 1 - c
  return [
    c + x * x * C, x * y * C - z * s, x * z * C + y * s,
    y * x * C + z * s, c + y * y * C, y * z * C - x * s,
    z * x * C - y * s, z * y * C + x * s, c + z * z * C,
  ]
}

/** n points spread evenly over a unit sphere (a Fibonacci lattice). */
function spherePoints(n: number): Vec[] {
  const golden = Math.PI * (3 - Math.sqrt(5))
  return Array.from({ length: n }, (_, i) => {
    const y = 1 - (2 * (i + 0.5)) / n
    const r = Math.sqrt(1 - y * y)
    return [Math.cos(i * golden) * r, y, Math.sin(i * golden) * r]
  })
}

// --- Feel ------------------------------------------------------------------------

/** Idle drift, in radians per ms (about 8°/s), and slower while the mouse is over the cloud. */
const DRIFT = 0.00015
const DRIFT_HOVER = 0.00004
/** A fresh throw sets the cloud spinning this fast before it settles into its drift. */
const THROW_SPIN = 0.0024
/** Radians of turn per pixel dragged. */
const DRAG_TURN = 0.006
/** Movement (px) before a press counts as a drag rather than a tap (more for fingers). */
const DRAG_SLOP = 6
const TOUCH_SLOP = 10
/** On touch, holding still this long (ms) grabs the cloud, so a drag spins it instead of scrolling. */
const HOLD_MS = 250
/** Fastest a flick can set the cloud turning, radians per ms (about 230°/s). */
const MAX_FLICK = 0.004
const FLIP_MS = 600

// Small fixed tilts so posters look tossed, not tiled.
const TILT = [-4, 3, -2, 5, -3, 2, -5, 4, -1, 3, -4, 2, 5, -2, 3]
/** Each poster's place in the hand while shaking: x, y, rotation. */
const HAND: Vec[] = [
  [-3, 2, -5],
  [4, -1, 4],
  [-1, -4, -2],
  [2, 3, 6],
  [0, 0, -1],
  [-4, -2, 3],
  [3, 3, -4],
  [-1, 4, 2],
]

const faceStyle: CSSProperties = { backfaceVisibility: 'hidden', WebkitBackfaceVisibility: 'hidden' }

function formatRuntime(min: number | null): string | null {
  if (!min) return null
  const h = Math.floor(min / 60)
  return h ? `${h}h ${min % 60}m` : `${min}m`
}

/** The back of a flipped poster: everything about the movie. */
function CardBack({ rolled, roomy, onClose, closeRef }: { rolled: RolledMovie; roomy: boolean; onClose: () => void; closeRef: (el: HTMLButtonElement | null) => void }) {
  const m = rolled.movie
  const meta = [m.year, formatRuntime(m.runtime_minutes), m.imdb_rating ? `★ ${m.imdb_rating.toFixed(1)}` : null].filter(Boolean)
  const directors = m.directors.map((d) => d.name).join(', ')
  const cast = m.cast.slice(0, 3).map((c) => c.name).join(', ')
  const src = posterSrc(m.poster_url, 'w342')
  return (
    <div className={`flex h-full gap-5 overflow-y-auto overscroll-contain p-5 text-left sm:p-6 ${roomy ? 'flex-row' : 'flex-col'}`}>
      <div className={`flex shrink-0 gap-4 ${roomy ? 'w-40 flex-col' : 'items-end'}`}>
        {src && <img src={src} alt="" className={`aspect-[2/3] rounded-xl object-cover shadow-lg ${roomy ? 'w-full' : 'w-24'}`} />}
        {!roomy && (
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold tracking-widest text-amber-600 uppercase dark:text-amber-400">{rolled.genre} pick</p>
            <h2 className="mt-0.5 text-2xl leading-tight font-bold tracking-tight">{m.title}</h2>
            <p className="mt-1 text-sm text-stone-600 dark:text-stone-400">{meta.join(' · ')}</p>
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        {roomy && (
          <>
            <p className="text-xs font-semibold tracking-widest text-amber-600 uppercase dark:text-amber-400">{rolled.genre} pick</p>
            <h2 className="mt-0.5 pr-10 text-3xl leading-tight font-bold tracking-tight text-balance">{m.title}</h2>
            <p className="mt-1 text-stone-600 dark:text-stone-400">{meta.join(' · ')}</p>
          </>
        )}
        {m.genres.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {m.genres.map((g) => (
              <li key={g} className="rounded-full bg-stone-900/5 px-2.5 py-0.5 text-xs text-stone-700 dark:bg-white/10 dark:text-stone-300">
                {g}
              </li>
            ))}
          </ul>
        )}
        {m.overview && <p className="mt-3 text-sm leading-relaxed text-stone-700 sm:text-base dark:text-stone-300">{m.overview}</p>}
        {(directors || cast) && (
          <p className="mt-3 text-sm text-stone-500">
            {directors && <>Dir. {directors}</>}
            {directors && cast && ' · '}
            {cast}
          </p>
        )}
        <p className="mt-4 flex gap-5 text-sm font-medium">
          <a href={m.letterboxd_url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
            Letterboxd ↗
          </a>
          <a href={m.imdb_url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
            IMDb ↗
          </a>
        </p>
      </div>
      <button
        ref={closeRef}
        type="button"
        onClick={onClose}
        aria-label="Flip back"
        className="absolute top-3 right-3 flex h-9 w-9 items-center justify-center rounded-full bg-stone-900/5 text-lg text-stone-600 transition hover:bg-stone-900/10 hover:text-stone-900 focus-visible:outline-2 focus-visible:outline-amber-500 dark:bg-white/10 dark:text-stone-300 dark:hover:bg-white/20 dark:hover:text-white"
      >
        ✕
      </button>
    </div>
  )
}

/** Where a card sat on screen (relative to the cloud's centre) when it was opened. */
interface Placed {
  x: number
  y: number
  s: number
}

interface Opened {
  i: number
  from: Placed
  /** from: still where the card sat; open: flipped and enlarged; closing: shrinking back. */
  stage: 'from' | 'open' | 'closing'
}

/**
 * Posters floating on a slowly turning sphere. Drag (or swipe sideways) to spin it,
 * arrow keys too; tap a poster to flip it over for its details. Positions are written
 * straight to the DOM each animation frame rather than through React state.
 */
export default function MovieCloud({ items, phase, reducedMotion, onOpenChange }: Props) {
  const boxRef = useRef<HTMLDivElement>(null)
  const { width: w = 0, height: h = 0 } = useElementSize(boxRef)
  const cards = useRef<(HTMLButtonElement | null)[]>([])
  const placed = useRef<Placed[]>([])
  const [opened, setOpened] = useState<Opened | null>(null)
  const closeButton = useRef<HTMLButtonElement | null>(null)

  // Everything the animation loop reads, kept in one ref so the loop never restarts.
  const sim = useRef({
    rot: mul(rotX(-0.25), IDENTITY), // tipped slightly, so the top of the cloud shows
    vx: DRIFT, // turn speeds, radians per ms
    vy: 0,
    k: 0, // 0 = gathered in the hand, 1 = spread out into the cloud
    kv: 0,
    hovering: false,
    drag: null as null | {
      id: number
      touch: boolean
      x0: number
      y0: number
      x: number
      y: number
      t: number
      moved: boolean
      /** Touch only: held still long enough to grab the cloud, so the page won't scroll. */
      held: boolean
      /** Smoothed turn speed of the drag, radians per ms, kept for the flick on release. */
      vx: number
      vy: number
    },
    /** A card brought round to the front for keyboard users. */
    seek: null as number | null,
    points: [] as Vec[],
  })
  const dragged = useRef(false) // the last press was a drag, so its click isn't a tap
  const holdTimer = useRef(0)
  const [grabbed, setGrabbed] = useState(false)

  const n = items.length
  const shaking = phase === 'shaking'
  const width = w || 960
  const height = h || 480
  const cardW = Math.max(52, Math.min(110, width * 0.16, height * 0.2))
  const cardH = cardW * 1.5
  // An ellipsoid: as tall as fits, and up to about twice as wide on wide screens.
  const ry = Math.max(40, height / 2 - cardH * 0.62)
  const rx = Math.max(40, Math.min(width / 2 - cardW * 0.66, ry * 1.9))
  const roomy = width >= 560
  const openW = Math.min(width, roomy ? 720 : 440)
  const openH = Math.min(height, roomy ? 460 : 560)

  // Spin Again closes any open card as the posters gather up.
  const [lastPhase, setLastPhase] = useState(phase)
  if (phase !== lastPhase) {
    setLastPhase(phase)
    if (phase === 'shaking') setOpened(null)
  }

  // Values the loop needs from this render, handed over before the next frame.
  const live = useRef({ rx, ry, shaking, reducedMotion, open: null as number | null })
  const openIndex = opened?.i ?? null
  useLayoutEffect(() => {
    live.current = { rx, ry, shaking, reducedMotion, open: openIndex }
    if (sim.current.points.length !== n) sim.current.points = spherePoints(n)
  })

  // A fresh throw bursts out of the hand with a spin.
  useEffect(() => {
    if (phase !== 'spread') return
    sim.current.vx = reducedMotion ? 0 : THROW_SPIN
    sim.current.vy = 0
  }, [phase, reducedMotion])

  useEffect(() => {
    onOpenChange?.(openIndex === null ? null : items[openIndex])
  }, [openIndex, items, onOpenChange])

  // The animation loop.
  useEffect(() => {
    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      const dt = Math.min(now - last, 50)
      last = now
      const s = sim.current
      const { rx, ry, shaking, reducedMotion, open } = live.current

      // Gather into the hand, or spring out into the cloud with a little overshoot.
      const target = shaking ? 0 : 1
      if (reducedMotion) {
        s.k = target
      } else {
        for (let step = 0; step < dt / 16; step++) {
          if (target === 0) {
            s.k += (0 - s.k) * 0.16
          } else {
            s.kv = (s.kv + (target - s.k) * 0.07) * 0.8
            s.k += s.kv
          }
        }
      }

      // Turn: held still while a card is open or being dragged, otherwise coasting
      // back towards the idle drift (or swinging a keyboard-focused card to the front).
      if (open === null && !s.drag) {
        if (s.seek !== null && s.points[s.seek]) {
          const p = apply(s.rot, s.points[s.seek])
          const angle = Math.acos(Math.max(-1, Math.min(1, p[2])))
          const axisLen = Math.hypot(p[1], p[0])
          if (angle < 0.01 || axisLen < 1e-6) {
            s.seek = null
          } else {
            const axis: Vec = [p[1] / axisLen, -p[0] / axisLen, 0]
            s.rot = mul(rotAxis(axis, angle * Math.min(1, dt / 120)), s.rot)
          }
        } else {
          s.rot = mul(mul(rotY(s.vx * dt), rotX(s.vy * dt)), s.rot)
          const drift = reducedMotion ? 0 : s.hovering ? DRIFT_HOVER : DRIFT
          const ease = 1 - Math.exp(-dt / 700)
          s.vx += (drift - s.vx) * ease
          s.vy += (0 - s.vy) * ease
        }
      }

      // Place every card: depth sets its size, fade and stacking order.
      const k = s.k
      s.points.forEach((pt, i) => {
        const el = cards.current[i]
        if (!el) return
        const p = apply(s.rot, pt)
        const [hx, hy, hr] = HAND[i % HAND.length]
        const z = p[2] * k
        const x = p[0] * rx * k + hx * (1 - k)
        const y = p[1] * ry * k + hy * (1 - k)
        const scale = 1 + z * 0.32
        const yaw = p[0] * k * 28 // posters near the edges turn a little, like the sphere's surface
        const tilt = TILT[i % TILT.length] * k + hr * (1 - k)
        placed.current[i] = { x, y, s: scale }
        el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) rotateY(${yaw.toFixed(1)}deg) rotate(${tilt.toFixed(1)}deg) scale(${scale.toFixed(3)})`
        el.style.opacity = open === i ? '0' : shaking ? '1' : (0.28 + 0.72 * ((z + 1) / 2) ** 1.3).toFixed(3)
        el.style.zIndex = String(shaking ? i : Math.round((z + 1) * 500))
        el.style.pointerEvents = shaking || open === i || z < -0.35 ? 'none' : 'auto'
      })
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [])

  // --- Dragging ---------------------------------------------------------------

  // Once a finger has grabbed the cloud, stop the page scrolling under it. This needs a
  // non-passive native listener: React's touch handlers can't cancel the scroll.
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    const onTouchMove = (e: TouchEvent) => {
      if (sim.current.drag?.held && e.cancelable) e.preventDefault()
    }
    box.addEventListener('touchmove', onTouchMove, { passive: false })
    return () => {
      box.removeEventListener('touchmove', onTouchMove)
      window.clearTimeout(holdTimer.current)
    }
  }, [])

  const grab = () => {
    const d = sim.current.drag
    if (!d || d.moved) return
    d.held = true
    d.moved = true
    dragged.current = true // letting go after a hold isn't a tap on a poster
    setGrabbed(true)
    navigator.vibrate?.(10)
  }

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (opened || (e.pointerType === 'mouse' && e.button !== 0)) return
    sim.current.seek = null
    sim.current.drag = {
      id: e.pointerId,
      touch: e.pointerType !== 'mouse',
      x0: e.clientX,
      y0: e.clientY,
      x: e.clientX,
      y: e.clientY,
      t: performance.now(),
      moved: false,
      held: false,
      vx: 0,
      vy: 0,
    }
    dragged.current = false
    window.clearTimeout(holdTimer.current)
    if (e.pointerType !== 'mouse') holdTimer.current = window.setTimeout(grab, HOLD_MS)
  }

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const s = sim.current
    const d = s.drag
    if (!d || d.id !== e.pointerId) return
    if (!d.moved) {
      const mx = e.clientX - d.x0
      const my = e.clientY - d.y0
      if (Math.hypot(mx, my) < (d.touch ? TOUCH_SLOP : DRAG_SLOP)) return
      // Moved before the hold grabbed it: on touch, a swipe that starts mostly vertical
      // is the page scrolling, so let it go. One that starts sideways spins the cloud.
      window.clearTimeout(holdTimer.current)
      if (d.touch && Math.abs(my) > Math.abs(mx)) {
        s.drag = null
        return
      }
      d.moved = true
      // Start the turn from here, so the slop doesn't land as one big jump.
      d.x = e.clientX
      d.y = e.clientY
      d.t = performance.now()
      dragged.current = true
      // Only capture once it's a drag, so a plain tap still clicks the poster under it.
      e.currentTarget.setPointerCapture(e.pointerId)
    }
    const now = performance.now()
    const dx = e.clientX - d.x
    const dy = e.clientY - d.y
    // Touch events can land a millisecond apart, so floor the interval and smooth
    // the speed: one jittery sample shouldn't fling the cloud.
    const dt = Math.max(now - d.t, 8)
    s.rot = mul(mul(rotY(dx * DRAG_TURN), rotX(-dy * DRAG_TURN)), s.rot)
    d.vx += ((dx * DRAG_TURN) / dt - d.vx) * 0.4
    d.vy += ((-dy * DRAG_TURN) / dt - d.vy) * 0.4
    d.x = e.clientX
    d.y = e.clientY
    d.t = now
  }

  const endDrag = (e: PointerEvent<HTMLDivElement>) => {
    const s = sim.current
    const d = s.drag
    if (!d || d.id !== e.pointerId) return
    s.drag = null
    window.clearTimeout(holdTimer.current)
    setGrabbed(false)
    if (!d.moved) return
    // Coast on with the flick, capped. A pause before letting go, or the browser
    // taking the gesture over (pointercancel), means no flick.
    if (e.type === 'pointercancel' || performance.now() - d.t > 80) {
      s.vx = 0
      s.vy = 0
      return
    }
    const speed = Math.hypot(d.vx, d.vy)
    const cap = speed > MAX_FLICK ? MAX_FLICK / speed : 1
    s.vx = d.vx * cap
    s.vy = d.vy * cap
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const s = sim.current
    const nudge = 0.0016
    if (e.key === 'ArrowLeft') s.vx = -nudge
    else if (e.key === 'ArrowRight') s.vx = nudge
    else if (e.key === 'ArrowUp') s.vy = nudge
    else if (e.key === 'ArrowDown') s.vy = -nudge
    else return
    s.seek = null
    e.preventDefault()
  }

  // --- Flipping a card open ---------------------------------------------------

  const openCard = (i: number) => {
    if (dragged.current || shaking || !items[i]) return
    const from = placed.current[i] ?? { x: 0, y: 0, s: 1 }
    setOpened({ i, from, stage: 'from' })
    // Two frames: let it render where the card sits, then animate to the middle.
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        setOpened((o) => (o && o.i === i ? { ...o, stage: 'open' } : o))
        closeButton.current?.focus({ preventScroll: true })
      }),
    )
  }

  const closeCard = useCallback(() => {
    setOpened((o) => {
      if (!o || o.stage === 'closing') return o
      const i = o.i
      window.setTimeout(
        () => {
          setOpened((cur) => (cur && cur.i === i && cur.stage === 'closing' ? null : cur))
          cards.current[i]?.focus({ preventScroll: true })
        },
        reducedMotion ? 0 : FLIP_MS,
      )
      return { ...o, stage: 'closing' }
    })
  }, [reducedMotion])

  useEffect(() => {
    if (!opened) return
    const onKey = (e: globalThis.KeyboardEvent) => e.key === 'Escape' && closeCard()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [opened, closeCard])

  const openRolled = opened ? items[opened.i] : null
  const big = opened?.stage === 'open'
  const ow = big ? openW : cardW * (opened?.from.s ?? 1)
  const oh = big ? openH : cardH * (opened?.from.s ?? 1)
  const ease = reducedMotion ? 'none' : `${FLIP_MS}ms cubic-bezier(.3,1.05,.5,1)`

  return (
    <div
      ref={boxRef}
      role="group"
      aria-label="Movie cloud: drag (on touch screens, hold then drag) or use the arrow keys to spin it, and pick a poster to flip it over"
      aria-busy={shaking}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onPointerEnter={(e) => e.pointerType === 'mouse' && (sim.current.hovering = true)}
      onPointerLeave={(e) => e.pointerType === 'mouse' && (sim.current.hovering = false)}
      onKeyDown={onKeyDown}
      onFocus={(e) => {
        // Keyboard users: swing the focused poster round to the front.
        const i = Number((e.target as HTMLElement).dataset.index)
        if (!Number.isNaN(i) && (e.target as HTMLElement).matches(':focus-visible')) sim.current.seek = i
      }}
      // Touch: a quick vertical swipe scrolls the page; a sideways swipe, or a hold then
      // a drag in any direction, spins the cloud. No long-press menus or image callouts.
      onContextMenu={(e) => sim.current.drag?.touch && e.preventDefault()}
      style={{ touchAction: 'pan-y', WebkitTouchCallout: 'none' }}
      className="relative h-full w-full cursor-grab select-none active:cursor-grabbing"
    >
      {/* Grabbed: the cloud draws in slightly, so you can feel it's held. */}
      <div className={`absolute inset-0 transition-[scale] duration-200 ${grabbed ? 'scale-[0.96]' : ''} ${shaking ? 'animate-[shake_500ms_ease-in-out_400ms_infinite] motion-reduce:animate-none' : ''}`}>
        {items.map((r, i) => {
          const m = r?.movie
          const src = m ? posterSrc(m.poster_url, 'w185') : null
          return (
            <button
              key={i}
              ref={(el) => {
                cards.current[i] = el
              }}
              data-index={i}
              type="button"
              disabled={r === null}
              aria-label={r && m ? `${r.genre}: ${m.title}${m.year ? ` (${m.year})` : ''}` : 'Shuffling'}
              onClick={() => openCard(i)}
              draggable={false}
              style={{ width: cardW, height: cardH, marginLeft: -cardW / 2, marginTop: -cardH / 2, opacity: 0 }}
              className="group absolute top-1/2 left-1/2 rounded-xl will-change-transform focus-visible:outline-none"
            >
              <span className="block h-full w-full overflow-hidden rounded-xl shadow-lg shadow-stone-900/30 ring-1 ring-black/5 transition duration-200 group-hover:scale-110 group-hover:shadow-xl group-focus-visible:ring-4 group-focus-visible:ring-amber-400 dark:shadow-black/60 dark:ring-white/10">
                {src ? (
                  <img src={src} alt="" draggable={false} className="h-full w-full object-cover" />
                ) : m ? (
                  <span className="flex h-full w-full items-center justify-center bg-stone-200 p-1.5 text-center text-[10px] leading-tight text-stone-600 dark:bg-stone-800 dark:text-stone-300">
                    {m.title}
                  </span>
                ) : (
                  // Face down: the back of a card, before the first throw.
                  <span className="flex h-full w-full items-center justify-center bg-linear-to-br from-amber-400 to-orange-600 text-2xl font-black text-white/80">
                    ?
                  </span>
                )}
              </span>
            </button>
          )
        })}
      </div>

      {opened && openRolled && (
        <>
          <div
            aria-hidden="true"
            onClick={closeCard}
            className={`absolute -inset-2 z-[1500] cursor-default rounded-3xl bg-stone-50/60 backdrop-blur-sm transition-opacity duration-300 dark:bg-stone-950/60 ${
              opened.stage === 'open' ? 'opacity-100' : 'opacity-0'
            }`}
          />
          {/* The opened poster, grown from where it sat in the cloud and flipped over. */}
          <div
            className="absolute top-1/2 left-1/2 z-[2000] cursor-default"
            onPointerDown={(e) => e.stopPropagation()}
            style={{
              width: ow,
              height: oh,
              marginLeft: -ow / 2,
              marginTop: -oh / 2,
              transform: big ? 'translate(0, 0)' : `translate(${opened.from.x}px, ${opened.from.y}px)`,
              perspective: 1400,
              transition: opened.stage === 'from' ? 'none' : ['width', 'height', 'margin-left', 'margin-top', 'transform'].map((p) => `${p} ${ease}`).join(', '),
            }}
          >
            <div
              className="relative h-full w-full"
              style={{
                transformStyle: 'preserve-3d',
                transform: big ? 'rotateY(180deg)' : 'none',
                transition: opened.stage === 'from' || reducedMotion ? 'none' : `transform ${FLIP_MS}ms cubic-bezier(.45,0,.25,1)`,
              }}
            >
              <div style={faceStyle} className="absolute inset-0 overflow-hidden rounded-xl shadow-2xl" aria-hidden="true">
                {openRolled.movie.poster_url && (
                  <img src={posterSrc(openRolled.movie.poster_url, 'w185') ?? undefined} alt="" className="h-full w-full object-cover" />
                )}
              </div>
              <div
                role="dialog"
                aria-label={openRolled.movie.title}
                style={{ ...faceStyle, transform: 'rotateY(180deg)' }}
                className="absolute inset-0 overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 shadow-stone-900/30 ring-black/5 dark:bg-stone-900 dark:shadow-black/60 dark:ring-white/10"
              >
                <CardBack
                  rolled={openRolled}
                  roomy={roomy}
                  onClose={closeCard}
                  closeRef={(el) => {
                    closeButton.current = el
                  }}
                />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
