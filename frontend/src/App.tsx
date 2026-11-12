import { Link, Route, Routes } from 'react-router-dom'
import Blender from './pages/Blender'
import Home from './pages/Home'
import LetterboxdConnect from './pages/LetterboxdConnect'
import LetterboxdSuggestions from './pages/LetterboxdSuggestions'
import NotFound from './pages/NotFound'

export default function App() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-stone-200 px-4 py-3 dark:border-stone-800">
        <nav className="mx-auto flex max-w-5xl items-center gap-6">
          <Link to="/" className="text-lg font-semibold tracking-tight">
            filmarbiter
          </Link>
          <Link to="/blend" className="text-sm text-stone-600 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100">
            Blender
          </Link>
          <Link to="/letterboxd" className="text-sm text-stone-600 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100">
            Letterboxd
          </Link>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/blend" element={<Blender />} />
          <Route path="/letterboxd" element={<LetterboxdConnect />} />
          <Route path="/letterboxd/:username" element={<LetterboxdSuggestions />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>

      <footer className="border-t border-stone-200 px-4 py-4 text-xs text-stone-500 dark:border-stone-800">
        <p className="mx-auto max-w-5xl">
          Information courtesy of IMDb (https://www.imdb.com), used with permission. This product uses the TMDB API
          but is not endorsed or certified by TMDB.
        </p>
      </footer>
    </div>
  )
}
