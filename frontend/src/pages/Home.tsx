import { Link } from 'react-router-dom'

const cards = [
  { to: '/blend', title: 'Blend movies', body: 'Pick up to 5 movies you love and get the 3 that best match all of them.' },
  { to: '/letterboxd', title: 'Use my Letterboxd', body: 'Connect your Letterboxd ratings and get picks based on your taste.' },
]

export default function Home() {
  return (
    <section className="space-y-8">
      <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Just pick a movie already.</h1>
      <div className="grid gap-4 sm:grid-cols-2">
        {cards.map((c) => (
          <Link
            key={c.to}
            to={c.to}
            className="rounded-xl border border-stone-200 p-6 transition hover:border-stone-400 dark:border-stone-800 dark:hover:border-stone-600"
          >
            <h2 className="text-xl font-semibold">{c.title}</h2>
            <p className="mt-2 text-stone-600 dark:text-stone-400">{c.body}</p>
          </Link>
        ))}
      </div>
    </section>
  )
}
