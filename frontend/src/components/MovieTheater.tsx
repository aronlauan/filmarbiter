import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ExtraSeat, MapNode, MapSection, MovieSummary } from '../api'
import Poster from './Poster'

interface Props {
  /** Board grid spacing in map units (the map spans [-1, 1]). */
  grid: number
  nodes: MapNode[]
  /** Links between similar movies, as index pairs into nodes. */
  edges: [number, number][]
  /** Areas of the house; seats point into this list. */
  sections: MapSection[]
  /** Seats made for picks and results outside the house's seating (/api/map/seats). */
  extras: ExtraSeat[]
  pickIds: string[]
  resultIds: string[]
  /** Results belong to an older set of picks. */
  stale: boolean
  blending: boolean
  /** A result card hovered or focused in the side panel. */
  focusId: string | null
  canAdd: boolean
  onToggle: (movie: MovieSummary) => void
}

interface Palette {
  floor: string
  row: string
  link: string
  linkHot: string
  seat: string
  seatBright: string
  light: string
  label: string
  halo: string
  pick: string
  result: string
  screen: string
}

const LIGHT: Palette = {
  floor: 'rgba(120, 113, 108, 0.08)',
  row: 'rgba(120, 113, 108, 0.16)',
  link: 'rgba(120, 113, 108, 0.22)',
  linkHot: 'rgba(41, 37, 36, 0.6)',
  seat: 'rgba(120, 113, 108, 0.45)',
  seatBright: 'rgba(68, 64, 60, 0.7)',
  light: '#d97706',
  label: '#1c1917',
  halo: 'rgba(255, 255, 255, 0.92)',
  pick: '#d97706',
  result: '#0284c7',
  screen: '#78716c',
}

const DARK: Palette = {
  floor: 'rgba(168, 162, 158, 0.055)',
  row: 'rgba(168, 162, 158, 0.09)',
  link: 'rgba(168, 162, 158, 0.16)',
  linkHot: 'rgba(245, 245, 244, 0.55)',
  seat: 'rgba(168, 162, 158, 0.42)',
  seatBright: 'rgba(214, 211, 209, 0.72)',
  light: '#fef3c7',
  label: '#f5f5f4',
  halo: 'rgba(12, 10, 9, 0.88)',
  pick: '#fbbf24',
  result: '#38bdf8',
  screen: '#e7e5e4',
}

/** Rows curve round the screen: a seat's y rises by CURVE * (distance from center)². */
const CURVE = 0.22
/** Gap between the front row and the screen, in map units. */
const SCREEN_GAP = 0.12
/** Share of seats (most-voted first) drawn brighter. */
const BRIGHT_SHARE = 0.12
const HIT_RADIUS = 10
const LINK_DELAY = 90 // ms between pick→result links starting
const LINK_DURATION = 900
const AMBIENT_SIGNALS = 8
const SIGNAL_SPEED = 0.1 // px per ms
/** Seat width in px tracks zoom between these; posters show on seat backs from POSTER_SEAT. */
const MIN_SEAT = 5
const MAX_SEAT = 56
const POSTER_SEAT = 22
/** Row guides need at least this many seats in a run. */
const MIN_ROW_SEATS = 3
/** A row guide breaks where seats in a section's row are more than this many cells apart. */
const ROW_BREAK = 4
/** Each seat's patch of section floor, in grid cells: wide enough to join neighbors
 *  in a section (≥2 cells apart), narrow enough to leave the aisles (≥3 apart) open. */
const FLOOR_PATCH = 2.4
const POSTER_LOADS_PER_FRAME = 12
/** Auto-framing (after picks or a blend) zooms in at most this far. */
const AUTO_ZOOM = 2.2
/** How far people can zoom in themselves. */
const MAX_ZOOM = 12
/** From this zoom up, seats in view get their titles, so you can read before you click. */
const LABEL_ZOOM = 2.6
const MAX_ZOOM_LABELS = 120
const DRAG_THRESHOLD = 4 // px a press can move and still count as a click
const FONT = 'ui-monospace, SFMono-Regular, Menlo, monospace'
const SIGN_FONT = 'ui-sans-serif, system-ui, sans-serif'

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const onChange = () => setMatches(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [query])
  return matches
}

const easeOut = (p: number) => 1 - (1 - p) ** 3
const isDark = (pal: Palette) => pal === DARK

interface Bounds {
  x0: number
  x1: number
  y0: number
  y1: number
}

function bounds(xy: Float32Array): Bounds {
  const b = { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity }
  for (let i = 0; i < xy.length; i += 2) {
    b.x0 = Math.min(b.x0, xy[i])
    b.x1 = Math.max(b.x1, xy[i])
    b.y0 = Math.min(b.y0, xy[i + 1])
    b.y1 = Math.max(b.y1, xy[i + 1])
  }
  return xy.length ? b : { x0: -1, x1: 1, y0: -1, y1: 1 }
}

/** Control point for a gentle curve from a to b (bowed to one side by 15% of its length). */
function bow(ax: number, ay: number, bx: number, by: number): [number, number] {
  return [(ax + bx) / 2 - (by - ay) * 0.15, (ay + by) / 2 + (bx - ax) * 0.15]
}

/** Point at parameter u along the quadratic curve a→(q)→b. */
function onCurve(ax: number, ay: number, qx: number, qy: number, bx: number, by: number, u: number): [number, number] {
  const a = (1 - u) ** 2
  const b = 2 * (1 - u) * u
  const c = u * u
  return [a * ax + b * qx + c * bx, a * ay + b * qy + c * by]
}

/** Where the camera settles: framing the highlighted movies (zoomed in, capped so the
 *  rest of the house stays in view), or the whole house when there are none. */
function cameraTarget(points: { x: number; y: number }[], board: Bounds): { x: number; y: number; zoom: number } {
  const center = { x: (board.x0 + board.x1) / 2, y: (board.y0 + board.y1) / 2 }
  if (points.length === 0) return { ...center, zoom: 1 }
  const xs = points.map((p) => p.x)
  const ys = points.map((p) => p.y)
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const span = Math.max(x1 - x0, y1 - y0) + 0.6 // padding around the group
  const boardSpan = Math.max(board.x1 - board.x0, board.y1 - board.y0)
  const zoom = Math.min(AUTO_ZOOM, Math.max(1, boardSpan / span))
  // Don't slide the house's edge past the box: at zoom z, 1/z of it shows.
  const clamp = (v: number, lo: number, hi: number) => {
    const half = ((hi - lo) / 2) * (1 - 1 / zoom)
    const mid = (lo + hi) / 2
    return Math.min(mid + half, Math.max(mid - half, v))
  }
  return { x: clamp((x0 + x1) / 2, board.x0, board.x1), y: clamp((y0 + y1) / 2, board.y0, board.y1), zoom }
}

interface Hover {
  index: number
  x: number
  y: number
  /** Container width when hovered, for keeping the card inside the box. */
  boxWidth: number
  /** Touch: tapped open, with buttons; stays until tapped away. */
  pinned: boolean
}

interface Signal {
  edge: number
  start: number
  reverse: boolean
}

function ZoomButton({ label, icon, onClick }: { label: string; icon: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex h-8 w-8 items-center justify-center font-mono text-base text-stone-600 hover:bg-stone-100 hover:text-stone-900 focus-visible:outline-2 focus-visible:outline-amber-500 dark:text-stone-300 dark:hover:bg-stone-800 dark:hover:text-white [&+&]:border-t [&+&]:border-stone-200 dark:[&+&]:border-stone-700"
    >
      {icon}
    </button>
  )
}

/**
 * The Blender's movie theater: the catalog's best-known films as seats in a house
 * facing a screen. Seats sit where the recommender's vectors put them (similar films
 * side by side), on rows that curve round the screen, linked to their nearest
 * neighbors. Aisles split the house into sections of similar films. Hover a seat to see the
 * movie and its neighbors; click to add or remove it as a pick. Zoomed in, seat backs
 * show posters. Purely an extra: everything it does is also possible from the side
 * panel.
 */
export default function MovieTheater(props: Props) {
  const { grid, nodes, edges, sections, extras, pickIds, canAdd, onToggle } = props
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [hover, setHover] = useState<Hover | null>(null)
  const [dragging, setDragging] = useState(false)
  const dark = useMediaQuery('(prefers-color-scheme: dark)')
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')

  // Static per-seat data: visible seats, then extras not already among them.
  const graph = useMemo(() => {
    const seen = new Set(nodes.map((n) => n.imdb_id))
    const all = [...nodes, ...extras.filter((e) => !seen.has(e.imdb_id))]
    const index = new Map(all.map((n, i) => [n.imdb_id, i]))
    const n = nodes.length
    // Links: the house's own, plus each extra seat's links to its most similar seats.
    const links: [number, number][] = [...edges]
    all.slice(n).forEach((e, k) => {
      for (const j of (e as ExtraSeat).links ?? []) links.push([j, n + k])
    })
    const neighbors: number[][] = all.map(() => [])
    for (const [a, b] of links) {
      neighbors[a]?.push(b)
      neighbors[b]?.push(a)
    }

    // Seats arrive on the grid; bend the rows round the screen and turn each seat to face it.
    const flat = new Float32Array(all.length * 2)
    all.forEach(({ x, y }, i) => {
      flat[i * 2] = Math.round(x / grid) * grid
      flat[i * 2 + 1] = Math.round(y / grid) * grid
    })
    const plan = bounds(flat.subarray(0, n * 2))
    const mid = (plan.x0 + plan.x1) / 2
    const lift = (x: number) => CURVE * (x - mid) ** 2
    const world = new Float32Array(all.length * 2)
    const angle = new Float32Array(all.length)
    for (let i = 0; i < all.length; i++) {
      const x = flat[i * 2]
      const y = flat[i * 2 + 1]
      world[i * 2] = x
      world[i * 2 + 1] = y - lift(x)
      angle[i] = Math.atan(-2 * CURVE * (x - mid))
    }
    // Row guides: faint arcs along each section's rows, broken at aisles (and wherever
    // a row has a wide gap), so the aisles read as walkways between sections.
    const rowSeats = new Map<string, { r: number; xs: number[] }>()
    for (let i = 0; i < n; i++) {
      const r = Math.round((flat[i * 2 + 1] - plan.y0) / grid)
      const key = `${all[i].section}:${r}`
      const entry = rowSeats.get(key) ?? { r, xs: [] }
      entry.xs.push(flat[i * 2])
      rowSeats.set(key, entry)
    }
    const guides: { y: number; x0: number; x1: number }[] = []
    for (const { r, xs } of rowSeats.values()) {
      xs.sort((a, b) => a - b)
      let start = 0
      for (let k = 1; k <= xs.length; k++) {
        if (k < xs.length && xs[k] - xs[k - 1] <= ROW_BREAK * grid) continue
        if (k - start >= MIN_ROW_SEATS)
          guides.push({ y: plan.y0 + r * grid, x0: xs[start] - grid, x1: xs[k - 1] + grid })
        start = k
      }
    }
    // Seat indexes per section, for drawing each section's floor.
    const members: number[][] = sections.map(() => [])
    for (let i = 0; i < all.length; i++) members[all[i].section]?.push(i)
    // The screen: an arc in front of the first row, over the middle 70% of the house.
    const halfW = ((plan.x1 - plan.x0) / 2) * 0.7
    const screenY = (x: number) => plan.y0 - SCREEN_GAP - lift(x)
    const board = bounds(world.subarray(0, n * 2))
    board.y0 = Math.min(board.y0, screenY(mid + halfW) - 0.08)
    return {
      all,
      index,
      neighbors,
      world,
      angle,
      links,
      board,
      mid,
      lift,
      screen: { x0: mid - halfW, x1: mid + halfW, y: screenY },
      guides,
      members,
      bright: all.map((_, i) => i < n * BRIGHT_SHARE),
      xy: new Float32Array(all.length * 2), // on-screen positions, refreshed each frame
    }
  }, [grid, nodes, edges, sections, extras])

  // The draw loop reads the latest props and state through a ref, so it never restarts.
  const live = useRef({ props, hover, palette: dark ? DARK : LIGHT, reducedMotion, graph })
  useLayoutEffect(() => {
    live.current = { props, hover, palette: dark ? DARK : LIGHT, reducedMotion, graph }
  })

  const pointerType = useRef('mouse')

  /**
   * Camera, shared by the draw loop and the input handlers. (x, y, zoom) is drawn;
   * (tx, ty, tzoom) is where it's easing to. `manual` is set once someone zooms or
   * pans, so adding picks stops moving the view; a new blend frames its results again.
   */
  const view = useRef({
    x: 0,
    y: 0,
    zoom: 1,
    tx: 0,
    ty: 0,
    tzoom: 1,
    manual: false,
    fit: 1,
    width: 0,
    height: 0,
    /** Current seat width in px, for hit testing. */
    seat: MIN_SEAT,
  })
  const gesture = useRef({
    pointers: new Map<number, { x: number; y: number }>(),
    startX: 0,
    startY: 0,
    moved: false,
    pinch: 0,
  })

  /** Keep the view's center over the house. */
  function clampView() {
    const v = view.current
    const b = graph.board
    v.tx = Math.min(b.x1, Math.max(b.x0, v.tx))
    v.ty = Math.min(b.y1, Math.max(b.y0, v.ty))
  }

  /** Zoom by `factor` keeping the point under (px, py) (canvas px) in place. */
  function zoomAt(px: number, py: number, factor: number, immediate: boolean) {
    const v = view.current
    const wx = v.tx + (px - v.width / 2) / (v.fit * v.tzoom)
    const wy = v.ty + (py - v.height / 2) / (v.fit * v.tzoom)
    v.tzoom = Math.min(MAX_ZOOM, Math.max(1, v.tzoom * factor))
    v.tx = wx - (px - v.width / 2) / (v.fit * v.tzoom)
    v.ty = wy - (py - v.height / 2) / (v.fit * v.tzoom)
    v.manual = true
    clampView()
    if (immediate) Object.assign(v, { x: v.tx, y: v.ty, zoom: v.tzoom })
    setHover(null)
  }

  function panBy(dx: number, dy: number) {
    const v = view.current
    v.tx -= dx / (v.fit * v.zoom)
    v.ty -= dy / (v.fit * v.zoom)
    v.manual = true
    clampView()
    Object.assign(v, { x: v.tx, y: v.ty })
  }

  function zoomCenter(factor: number) {
    const v = view.current
    zoomAt(v.width / 2, v.height / 2, factor, false)
  }

  function resetView() {
    const v = view.current
    const b = graph.board
    Object.assign(v, { tx: (b.x0 + b.x1) / 2, ty: (b.y0 + b.y1) / 2, tzoom: 1, manual: true })
    setHover(null)
  }

  // Wheel / trackpad zoom. Attached by hand: React's wheel listener is passive, and
  // the page mustn't scroll while zooming the house.
  const zoomAtRef = useRef(zoomAt)
  useLayoutEffect(() => {
    zoomAtRef.current = zoomAt
  })
  useEffect(() => {
    const canvas = canvasRef.current!
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = canvas.getBoundingClientRect()
      // Trackpad pinch arrives as ctrl+wheel with small deltas; scale those up.
      const delta = e.ctrlKey ? e.deltaY * 8 : e.deltaY
      zoomAtRef.current(e.clientX - rect.left, e.clientY - rect.top, Math.exp(-delta * 0.0015), true)
    }
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', onWheel)
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current!
    const container = containerRef.current!
    const ctx = canvas.getContext('2d')!
    let width = 0
    let height = 0
    let frame = 0
    let linksKey = ''
    let linksStart = 0
    const { board } = live.current.graph
    const cam = view.current
    Object.assign(cam, { x: (board.x0 + board.x1) / 2, y: (board.y0 + board.y1) / 2 })
    Object.assign(cam, { tx: cam.x, ty: cam.y })
    let framedKey = ''
    let framedResults = ''
    let signals: Signal[] = []
    const posters = new Map<string, HTMLImageElement>()
    // Labels placed this frame, so later ones can dodge them.
    let placed: { x0: number; y0: number; x1: number; y1: number }[] = []

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      width = container.clientWidth
      height = container.clientHeight
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    const observer = new ResizeObserver(resize)
    observer.observe(container)
    resize()

    /** Title next to a seat, in the first spot (above, below, right, left) that doesn't
     *  overlap an earlier label. `force` draws it anyway when every spot is taken;
     *  `belowOnly` keeps it under its own seat (used over posters). */
    const label = (
      text: string,
      nx: number,
      ny: number,
      color: string,
      weight: number,
      size: number,
      force: boolean,
      gap = 9,
      belowOnly = false,
    ) => {
      const { palette } = live.current
      ctx.font = `${weight} ${size}px ${FONT}`
      ctx.letterSpacing = '0px'
      const w = ctx.measureText(text).width
      const below = { x: nx - w / 2, y: ny + gap }
      const spots = belowOnly
        ? [below]
        : [{ x: nx - w / 2, y: ny - gap - size }, below, { x: nx + gap, y: ny - size / 2 }, { x: nx - gap - w, y: ny - size / 2 }]
      const free = spots.find(
        (b) => !placed.some((r) => b.x < r.x1 && b.x + w > r.x0 && b.y < r.y1 && b.y + size > r.y0),
      )
      if (!free && !force) return
      const { x, y } = free ?? spots[0]
      // Wider margin sideways, so neighboring titles don't read as one.
      placed.push({ x0: x - 8, y0: y - 2, x1: x + w + 8, y1: y + size + 2 })
      ctx.textAlign = 'left'
      ctx.textBaseline = 'top'
      ctx.lineWidth = 4
      ctx.lineJoin = 'round'
      ctx.strokeStyle = palette.halo
      ctx.strokeText(text, x, y)
      ctx.fillStyle = color
      ctx.fillText(text, x, y)
    }

    const draw = (t: number) => {
      const { props: p, hover: h, palette, reducedMotion: still, graph: g } = live.current
      const { all, index, neighbors, world, angle, board, bright, xy } = g
      ctx.clearRect(0, 0, width, height)
      // Start every frame from clean drawing state, so no glow or fade leaks into seats.
      ctx.shadowBlur = 0
      ctx.globalAlpha = 1
      ctx.setLineDash([])

      const picks = p.pickIds.map((id) => index.get(id)).filter((i): i is number => i !== undefined)
      const results = p.resultIds.map((id) => index.get(id)).filter((i): i is number => i !== undefined)
      const pickSet = new Set(picks)
      const resultSet = new Set(results)

      // Camera: frame the picks and results when they change, unless the person has
      // taken over the view; a new blend always frames its results.
      const frameKey = `${picks.join()}|${results.join()}`
      if (frameKey !== framedKey) {
        if (results.length && results.join() !== framedResults) cam.manual = false
        framedKey = frameKey
        framedResults = results.join()
        if (!cam.manual) {
          const tg = cameraTarget(
            [...picks, ...results].map((i) => ({ x: world[i * 2], y: world[i * 2 + 1] })),
            board,
          )
          Object.assign(cam, { tx: tg.x, ty: tg.y, tzoom: tg.zoom })
        }
      }
      const ease = still ? 1 : cam.manual ? 0.2 : 0.045
      cam.x += (cam.tx - cam.x) * ease
      cam.y += (cam.ty - cam.y) * ease
      cam.zoom += (cam.tzoom - cam.zoom) * ease

      // Fit the house in the box, one scale for both axes.
      const fit = Math.min((width * 0.94) / (board.x1 - board.x0 || 1), (height * 0.9) / (board.y1 - board.y0 || 1))
      Object.assign(cam, { fit, width, height })
      const sc = fit * cam.zoom
      const cx = width / 2
      const cy = height / 2
      const SX = (wx: number) => cx + (wx - cam.x) * sc
      const SY = (wy: number) => cy + (wy - cam.y) * sc
      for (let i = 0; i < all.length; i++) {
        xy[i * 2] = SX(world[i * 2])
        xy[i * 2 + 1] = SY(world[i * 2 + 1])
      }
      const X = (i: number) => xy[i * 2]
      const Y = (i: number) => xy[i * 2 + 1]
      const inView = (i: number, m: number) => X(i) > -m && X(i) < width + m && Y(i) > -m && Y(i) < height + m

      // Seats grow with zoom (the grid gap sets the scale); posters fill the backs once they're big.
      const seatW = Math.min(MAX_SEAT, Math.max(MIN_SEAT, p.grid * sc * 0.8))
      const posterMode = seatW >= POSTER_SEAT
      // Zoomed in, seats get high backs so a poster fits.
      const seatH = seatW * (posterMode ? 1.55 : 1.05)
      const backShare = posterMode ? 0.82 : 0.74
      cam.seat = seatW

      const focus = p.focusId !== null ? index.get(p.focusId) : undefined
      const hot = h?.index ?? focus
      // Seats linked to a pick light up: the vibe spreading from your choices.
      const warm = new Set(picks.flatMap((i) => neighbors[i]))

      // --- Behind everything: the screen and its light.
      const scr = g.screen
      const screenPath = () => {
        ctx.beginPath()
        for (let k = 0; k <= 40; k++) {
          const x = scr.x0 + ((scr.x1 - scr.x0) * k) / 40
          if (k === 0) ctx.moveTo(SX(x), SY(scr.y(x)))
          else ctx.lineTo(SX(x), SY(scr.y(x)))
        }
      }
      const glow = ctx.createLinearGradient(0, SY(scr.y(g.mid)), 0, SY(scr.y(g.mid) + 0.45))
      glow.addColorStop(0, isDark(palette) ? 'rgba(254, 243, 199, 0.07)' : 'rgba(120, 113, 108, 0.07)')
      glow.addColorStop(1, 'rgba(0, 0, 0, 0)')
      ctx.fillStyle = glow
      screenPath()
      ctx.lineTo(SX(scr.x1 + 0.25), SY(scr.y(scr.x1) + 0.45))
      ctx.lineTo(SX(scr.x0 - 0.25), SY(scr.y(scr.x0) + 0.45))
      ctx.closePath()
      ctx.fill()
      ctx.strokeStyle = palette.screen
      ctx.globalAlpha = 0.55
      ctx.lineWidth = Math.max(2, 0.012 * sc)
      ctx.lineCap = 'round'
      screenPath()
      ctx.stroke()
      ctx.globalAlpha = 0.5
      ctx.fillStyle = palette.screen
      const screenText = Math.max(9, Math.min(16, 0.022 * sc))
      ctx.font = `600 ${screenText}px ${SIGN_FONT}`
      ctx.letterSpacing = `${screenText * 0.5}px`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'bottom'
      ctx.fillText('SCREEN', SX(g.mid), SY(scr.y(g.mid)) - screenText * 0.6)
      ctx.globalAlpha = 1
      ctx.lineCap = 'butt'

      // Section floors: one block per section under its seats; the gaps between
      // blocks are the aisles. Each section is one path filled once, so overlapping
      // patches don't stack up darker.
      {
        const patch = FLOOR_PATCH * p.grid * sc
        const r = Math.min(patch * 0.3, 6)
        ctx.fillStyle = palette.floor
        for (const seats of g.members) {
          ctx.beginPath()
          for (const i of seats) {
            if (!inView(i, patch)) continue
            ctx.roundRect(X(i) - patch / 2, Y(i) - patch / 2, patch, patch, r)
          }
          ctx.fill('nonzero')
        }
      }

      // Row guides: faint dotted arcs along each section's rows.
      ctx.strokeStyle = palette.row
      ctx.lineWidth = 1
      ctx.setLineDash([1, Math.max(3, p.grid * sc * 0.25)])
      ctx.beginPath()
      for (const gd of g.guides) {
        if (SY(gd.y - g.lift(gd.x0)) < -20 && SY(gd.y - g.lift(gd.x1)) < -20) continue
        if (SY(gd.y) > height + 20 && SY(gd.y - g.lift(gd.x0)) > height + 20) continue
        const steps = 16
        for (let k = 0; k <= steps; k++) {
          const x = gd.x0 + ((gd.x1 - gd.x0) * k) / steps
          if (k === 0) ctx.moveTo(SX(x), SY(gd.y - g.lift(x)))
          else ctx.lineTo(SX(x), SY(gd.y - g.lift(x)))
        }
      }
      ctx.stroke()
      ctx.setLineDash([])

      // --- The network: gentle curves between similar films.
      const curve = (a: number, b: number) => {
        const [qx, qy] = bow(X(a), Y(a), X(b), Y(b))
        ctx.moveTo(X(a), Y(a))
        ctx.quadraticCurveTo(qx, qy, X(b), Y(b))
      }
      const visible = (a: number, b: number) => inView(a, 200) || inView(b, 200)
      ctx.lineWidth = 1
      ctx.strokeStyle = palette.link
      ctx.beginPath()
      for (const [a, b] of g.links) if (visible(a, b)) curve(a, b)
      ctx.stroke()
      if (picks.length) {
        ctx.strokeStyle = palette.pick
        ctx.globalAlpha = 0.5
        ctx.lineWidth = 1.25
        ctx.beginPath()
        for (const i of picks) for (const j of neighbors[i]) curve(i, j)
        ctx.stroke()
        ctx.globalAlpha = 1
      }
      if (hot !== undefined) {
        ctx.strokeStyle = palette.linkHot
        ctx.lineWidth = 1.5
        ctx.beginPath()
        for (const j of neighbors[hot]) curve(hot, j)
        ctx.stroke()
      }
      ctx.lineWidth = 1

      // A small glowing dot running along a curve, with a short trail.
      const spark = (a: [number, number], b: [number, number], u: number, color: string, size: number) => {
        const [qx, qy] = bow(a[0], a[1], b[0], b[1])
        ctx.fillStyle = color
        ctx.shadowColor = color
        ctx.shadowBlur = 8
        for (let k = 0; k < 4; k++) {
          const uu = u - k * 0.035
          if (uu < 0 || uu > 1) continue
          const [x, y] = onCurve(a[0], a[1], qx, qy, b[0], b[1], uu)
          ctx.globalAlpha = 1 - k * 0.27
          ctx.beginPath()
          ctx.arc(x, y, size * (1 - k * 0.18), 0, Math.PI * 2)
          ctx.fill()
          // Glow on the head only; switched off below whether or not the head was drawn.
          ctx.shadowBlur = 0
        }
        ctx.shadowBlur = 0
        ctx.globalAlpha = 1
      }
      if (!still && g.links.length) {
        while (signals.length < AMBIENT_SIGNALS)
          signals.push({
            edge: Math.floor(Math.random() * g.links.length),
            start: t + Math.random() * 3000,
            reverse: Math.random() < 0.5,
          })
        signals = signals.filter((sg) => {
          const e = g.links[sg.edge]
          if (!e) return false
          const [a, b] = sg.reverse ? [e[1], e[0]] : e
          const len = Math.hypot(X(b) - X(a), Y(b) - Y(a)) || 1
          const u = ((t - sg.start) * SIGNAL_SPEED * Math.max(1, Math.sqrt(cam.zoom))) / len
          if (u > 1.15) return false
          if (u >= 0 && visible(a, b)) spark([X(a), Y(a)], [X(b), Y(b)], u, palette.light, 1.4)
          return true
        })
      }

      // --- Seats.
      let loads = 0
      /** The film's poster if loaded; starts loading it (a few per frame) if not. */
      const posterImage = (i: number): HTMLImageElement | null => {
        const url = all[i].poster_url
        if (!url) return null
        const img = posters.get(url)
        if (img) return img.complete && img.naturalWidth > 0 ? img : null
        if (loads++ >= POSTER_LOADS_PER_FRAME) return null
        const fresh = new Image()
        fresh.decoding = 'async'
        fresh.src = url.replace('/w342/', '/w92/')
        posters.set(url, fresh)
        return null
      }
      /**
       * One seat, seen from above like a booking map: a backrest (where the poster
       * goes when zoomed in) over a wider seat-front bar, turned to face the screen.
       */
      const seat = (i: number, fill: string, scale: number, outline: string | null) => {
        const w = seatW * scale
        const hgt = seatH * scale
        ctx.save()
        ctx.translate(X(i), Y(i))
        ctx.rotate(angle[i])
        const backH = hgt * backShare
        const r = Math.min(w * 0.22, 6)
        ctx.fillStyle = fill
        ctx.beginPath()
        ctx.roundRect(-w / 2, -hgt / 2, w, backH, [r, r, r * 0.4, r * 0.4])
        ctx.fill()
        if (posterMode) {
          const img = posterImage(i)
          if (img) {
            const inset = Math.max(1.5, w * 0.07)
            ctx.save()
            ctx.beginPath()
            ctx.roundRect(-w / 2 + inset, -hgt / 2 + inset, w - inset * 2, backH - inset * 2, Math.max(1, r - inset))
            ctx.clip()
            // Cover-crop the 2:3 poster into the seat back.
            const bw = w - inset * 2
            const bh = backH - inset * 2
            const scaleImg = Math.max(bw / img.naturalWidth, bh / img.naturalHeight)
            const dw = img.naturalWidth * scaleImg
            const dh = img.naturalHeight * scaleImg
            ctx.drawImage(img, -dw / 2, -hgt / 2 + inset + (bh - dh) / 2, dw, dh)
            ctx.restore()
          }
        }
        ctx.fillStyle = fill
        ctx.beginPath()
        const frontH = hgt * (1 - backShare) * 0.8
        ctx.roundRect(-w / 2 - w * 0.08, hgt / 2 - frontH, w * 1.16, frontH, Math.min(w * 0.08, 3))
        ctx.fill()
        if (outline) {
          ctx.strokeStyle = outline
          ctx.lineWidth = 1.5
          ctx.beginPath()
          ctx.roundRect(-w / 2 - 4, -hgt / 2 - 4, w + 8, hgt + 8, r + 3)
          ctx.stroke()
          ctx.lineWidth = 1
        }
        ctx.restore()
      }

      const small = seatW < 9
      for (let i = 0; i < all.length; i++) {
        if (pickSet.has(i) || resultSet.has(i) || !inView(i, seatW * 2)) continue
        const fill = warm.has(i) ? palette.pick : bright[i] ? palette.seatBright : palette.seat
        if (small) {
          // Far out, seats are dots of seat shape; skip the rotation work.
          ctx.fillStyle = fill
          ctx.globalAlpha = warm.has(i) ? 0.9 : 1
          ctx.beginPath()
          ctx.roundRect(X(i) - seatW / 2, Y(i) - seatH / 2, seatW, seatH * 0.74, 1.5)
          ctx.rect(X(i) - seatW * 0.58, Y(i) + seatH * 0.32, seatW * 1.16, seatH * 0.18)
          ctx.fill()
          ctx.globalAlpha = 1
        } else {
          seat(i, warm.has(i) ? palette.pick : fill, 1, null)
        }
      }

      // --- Pick → result links, drawn in after each blend, then carrying light.
      const key = results.length ? `${picks.join()}>${results.join()}` : ''
      if (key !== linksKey) {
        linksKey = key
        linksStart = t
      }
      let linkIndex = 0
      for (const r of results) {
        for (const k of picks) {
          const progress = still
            ? 1
            : easeOut(Math.min(1, Math.max(0, (t - linksStart - linkIndex * LINK_DELAY) / LINK_DURATION)))
          const n = linkIndex++
          if (progress <= 0) continue
          const a: [number, number] = [X(k), Y(k)]
          const b: [number, number] = [X(r), Y(r)]
          const [qx, qy] = bow(a[0], a[1], b[0], b[1])
          const grad = ctx.createLinearGradient(a[0], a[1], b[0], b[1])
          grad.addColorStop(0, palette.pick)
          grad.addColorStop(1, palette.result)
          ctx.strokeStyle = grad
          ctx.globalAlpha = p.stale ? 0.25 : 0.85
          ctx.lineWidth = 2
          ctx.beginPath()
          ctx.moveTo(a[0], a[1])
          for (let st = 1; st <= 30; st++) {
            const [x, y] = onCurve(a[0], a[1], qx, qy, b[0], b[1], Math.min(st / 30, progress))
            ctx.lineTo(x, y)
            if (st / 30 >= progress) break
          }
          ctx.stroke()
          ctx.globalAlpha = 1
          ctx.lineWidth = 1
          if (progress >= 1 && !still && !p.stale) {
            const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1
            const cycle = len / SIGNAL_SPEED + 700
            spark(a, b, (((t - linksStart + n * 170) % cycle) * SIGNAL_SPEED) / len, palette.light, 2)
          }
        }
      }
      const linksDone = still || t - linksStart > linkIndex * LINK_DELAY + LINK_DURATION

      // Your seats (picks) and recommended seats (results): bigger, glowing.
      const special = (i: number, color: string, pop: number, dim: boolean) => {
        ctx.globalAlpha = dim ? 0.4 : 1
        ctx.shadowColor = color
        ctx.shadowBlur = dim ? 0 : 14
        const scale = (posterMode ? 1.15 : Math.max(1.6, 9 / seatW)) + pop / 10
        seat(i, color, scale, null)
        ctx.shadowBlur = 0
        ctx.globalAlpha = 1
      }
      const blendPulse = p.blending && !still ? 2 + Math.sin(t / 140) * 2 : 0
      for (const i of picks) special(i, palette.pick, blendPulse, false)
      if (linksDone || p.stale)
        for (const i of results) {
          const since = t - linksStart - linkIndex * LINK_DELAY - LINK_DURATION
          const pop = still || p.stale ? 0 : Math.max(0, 4 * (1 - since / 600))
          special(i, palette.result, pop, p.stale)
        }

      // Hovered / focused seat: an outline round it.
      if (hot !== undefined) {
        const big = pickSet.has(hot) || resultSet.has(hot)
        const scale = big ? (posterMode ? 1.15 : Math.max(1.6, 9 / seatW)) : 1
        seat(hot, 'rgba(0, 0, 0, 0)', scale, pickSet.has(hot) ? palette.pick : resultSet.has(hot) ? palette.result : palette.label)
      }

      // --- Titles: picks and results always (they win the space), then the hovered
      // seat's neighbors where there's room, then (zoomed in) every seat in view.
      const half = Math.max(8, seatW * 0.7)
      placed = [...picks, ...results].map((i) => ({ x0: X(i) - half, y0: Y(i) - half, x1: X(i) + half, y1: Y(i) + half }))
      const gap = posterMode ? seatH * 0.6 + 4 : 9
      const bigGap = posterMode ? seatH * 0.7 + 4 : 11
      for (const i of picks) if (i !== h?.index) label(all[i].title, X(i), Y(i), palette.pick, 600, 11, true, bigGap, posterMode)
      if (linksDone || p.stale)
        for (const i of results)
          if (i !== h?.index) label(all[i].title, X(i), Y(i), palette.result, 600, 11, true, bigGap, posterMode)
      if (hot !== undefined)
        for (const j of neighbors[hot])
          if (!pickSet.has(j) && !resultSet.has(j)) label(all[j].title, X(j), Y(j), palette.label, 400, 10, false, gap, posterMode)
      if (cam.zoom >= LABEL_ZOOM) {
        ctx.globalAlpha = Math.min(1, (cam.zoom - LABEL_ZOOM) * 2 + 0.4) * 0.8
        let shown = 0
        for (let i = 0; i < all.length && shown < MAX_ZOOM_LABELS; i++) {
          if (pickSet.has(i) || resultSet.has(i) || i === hot || !inView(i, 40)) continue
          const before = placed.length
          label(all[i].title, X(i), Y(i), palette.label, 400, 10, false, gap, posterMode)
          if (placed.length > before) shown++
        }
        ctx.globalAlpha = 1
      }

      frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  function hitTest(clientX: number, clientY: number): Hover | null {
    const rect = canvasRef.current!.getBoundingClientRect()
    const x = clientX - rect.left
    const y = clientY - rect.top
    const { xy } = graph
    const seatW = view.current.seat
    let best = -1
    let bestDist = Infinity
    for (let i = 0; i < graph.all.length; i++) {
      const dx = xy[i * 2] - x
      const dy = xy[i * 2 + 1] - y
      const d = Math.hypot(dx, dy)
      const inside =
        seatW > HIT_RADIUS * 1.2 ? Math.abs(dx) <= seatW * 0.6 + 2 && Math.abs(dy) <= seatW * 0.55 + 2 : d < HIT_RADIUS
      if (inside && d < bestDist) {
        best = i
        bestDist = d
      }
    }
    if (best < 0) return null
    // The card sits above the seat.
    const top = xy[best * 2 + 1] - Math.max(0, seatW * 0.55 - 8)
    return { index: best, x: xy[best * 2], y: top, boxWidth: rect.width, pinned: false }
  }

  function toggle(i: number) {
    const { imdb_id, title, year, poster_url } = graph.all[i]
    onToggle({ imdb_id, title, year, poster_url })
  }

  const hovered = hover ? graph.all[hover.index] : null
  const hoveredPicked = hovered ? pickIds.includes(hovered.imdb_id) : false
  const hint = hoveredPicked ? 'Click to remove' : canAdd ? 'Click to add' : 'Remove a pick to add this'

  return (
    <div ref={containerRef} className="absolute inset-0">
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className={`absolute inset-0 h-full w-full touch-none ${
          dragging ? 'cursor-grabbing' : hover && !hover.pinned ? 'cursor-pointer' : 'cursor-grab'
        }`}
        onPointerDown={(e) => {
          pointerType.current = e.pointerType
          const g = gesture.current
          e.currentTarget.setPointerCapture(e.pointerId)
          g.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
          if (g.pointers.size === 1) Object.assign(g, { startX: e.clientX, startY: e.clientY, moved: false })
          if (g.pointers.size === 2) {
            const [a, b] = [...g.pointers.values()]
            g.pinch = Math.hypot(a.x - b.x, a.y - b.y)
          }
        }}
        onPointerMove={(e) => {
          const g = gesture.current
          const prev = g.pointers.get(e.pointerId)
          if (prev) {
            // Pressed: one pointer pans, two pinch-zoom.
            g.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
            if (g.pointers.size === 1) {
              if (!g.moved && Math.hypot(e.clientX - g.startX, e.clientY - g.startY) > DRAG_THRESHOLD) {
                g.moved = true
                setDragging(true)
                setHover(null)
              }
              if (g.moved) panBy(e.clientX - prev.x, e.clientY - prev.y)
            } else if (g.pointers.size === 2) {
              const [a, b] = [...g.pointers.values()]
              const dist = Math.hypot(a.x - b.x, a.y - b.y)
              const rect = e.currentTarget.getBoundingClientRect()
              if (g.pinch > 0) zoomAt((a.x + b.x) / 2 - rect.left, (a.y + b.y) / 2 - rect.top, dist / g.pinch, true)
              g.pinch = dist
              g.moved = true
            }
            return
          }
          if (e.pointerType !== 'mouse') return
          const hit = hitTest(e.clientX, e.clientY)
          setHover((prev) => (prev?.index === hit?.index ? prev : hit))
        }}
        onPointerUp={(e) => {
          gesture.current.pointers.delete(e.pointerId)
          gesture.current.pinch = 0
          setDragging(false)
        }}
        onPointerCancel={(e) => {
          gesture.current.pointers.delete(e.pointerId)
          gesture.current.pinch = 0
        }}
        onPointerLeave={(e) => {
          if (e.pointerType === 'mouse' && gesture.current.pointers.size === 0) setHover(null)
        }}
        onClick={(e) => {
          // A drag or pinch ends in a click event too; it isn't a selection.
          if (gesture.current.moved) {
            gesture.current.moved = false
            return
          }
          const hit = hitTest(e.clientX, e.clientY)
          if (pointerType.current === 'mouse') {
            if (hit && (canAdd || pickIds.includes(graph.all[hit.index].imdb_id))) toggle(hit.index)
          } else {
            // Touch has no hover: a tap opens the card, its button adds or removes.
            setHover(hit ? { ...hit, pinned: true } : null)
          }
        }}
        onDoubleClick={(e) => {
          // Double-click empty floor to zoom in there (seats toggle on single click).
          if (hitTest(e.clientX, e.clientY)) return
          const rect = e.currentTarget.getBoundingClientRect()
          zoomAt(e.clientX - rect.left, e.clientY - rect.top, 2, false)
        }}
      />

      <div className="absolute top-3 right-3 z-10 flex flex-col overflow-hidden rounded-md border border-stone-200 bg-white/90 shadow-sm backdrop-blur dark:border-stone-700 dark:bg-stone-900/90">
        <ZoomButton label="Zoom in" icon="+" onClick={() => zoomCenter(1.8)} />
        <ZoomButton label="Zoom out" icon="−" onClick={() => zoomCenter(1 / 1.8)} />
        <ZoomButton label="Show the whole house" icon="⤢" onClick={() => resetView()} />
      </div>

      {hover && hovered && (
        <div
          className={`absolute z-10 flex w-60 items-center gap-3 rounded-md border border-stone-200 bg-white/95 p-2 shadow-lg backdrop-blur dark:border-stone-700 dark:bg-stone-900/95 ${
            hover.pinned ? '' : 'pointer-events-none'
          }`}
          style={{
            left: Math.min(Math.max(hover.x - 120, 8), hover.boxWidth - 248),
            top: hover.y > 120 ? hover.y - 92 : hover.y + 18,
          }}
        >
          <Poster url={hovered.poster_url} title={hovered.title} size="w92" className="w-10 shrink-0 rounded-sm" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold" title={hovered.title}>
              {hovered.title}
            </p>
            <p className="font-mono text-xs text-stone-500">
              {/* The film's own genres: its section only names the area it sits in. */}
              {[hovered.year, hovered.genres.slice(0, 3).join(', ')].filter(Boolean).join(' · ')}
            </p>
            {hover.pinned ? (
              <button
                type="button"
                disabled={!hoveredPicked && !canAdd}
                onClick={() => {
                  toggle(hover.index)
                  setHover(null)
                }}
                className="mt-1 text-xs font-semibold text-amber-700 disabled:text-stone-400 dark:text-amber-400"
              >
                {hoveredPicked ? 'Remove from picks' : canAdd ? 'Add to picks' : 'Picks are full'}
              </button>
            ) : (
              <p className="mt-0.5 text-xs text-stone-500">{hint}</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
