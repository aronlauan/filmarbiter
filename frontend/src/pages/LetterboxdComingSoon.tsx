import { Link } from 'react-router-dom'

/** Shown at /letterboxd (and any old /letterboxd/:username link) while the feature is off. */
export default function LetterboxdComingSoon() {
  return (
    <section className="space-y-4">
      <h1 className="text-3xl font-bold tracking-tight">Letterboxd picks: coming soon…</h1>
      <p className="text-stone-600 dark:text-stone-400">
        Soon you'll be able to get picks based on how you've rated films on Letterboxd. In the meantime, try the{' '}
        <Link to="/blend" className="underline">
          Movie Blender
        </Link>
        : pick a few movies you like and get the ones that match them all.
      </p>
    </section>
  )
}
