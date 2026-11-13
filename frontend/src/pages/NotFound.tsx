import { Link } from 'react-router-dom'
import { LETTERBOXD_ENABLED } from '../features'

export default function NotFound() {
  return (
    <section className="space-y-4">
      <h1 className="text-3xl font-bold tracking-tight">Page not found</h1>
      <p className="text-stone-600 dark:text-stone-400">
        There's nothing here. Try the{' '}
        <Link to="/blend" className="underline">
          Movie Blender
        </Link>
        {LETTERBOXD_ENABLED && (
          <>
            {' '}
            or{' '}
            <Link to="/letterboxd" className="underline">
              your Letterboxd picks
            </Link>
          </>
        )}
        .
      </p>
    </section>
  )
}
