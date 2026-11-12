import { Link, Route, Routes, useLocation } from 'react-router-dom'
import Blender from './pages/Blender'
import Home from './pages/Home'
import LetterboxdConnect from './pages/LetterboxdConnect'
import LetterboxdSuggestions from './pages/LetterboxdSuggestions'
import NotFound from './pages/NotFound'

export default function App() {
  // The Blender's theater fills the screen under the header; other pages stay a readable column.
  const fullBleed = useLocation().pathname === '/blend'
  const width = fullBleed ? 'max-w-[96rem]' : 'max-w-5xl'
  return (
    <div className="flex min-h-screen flex-col">
      {/* Fixed height: the Blender sizes its stage to the screen minus this header. */}
      <header className="flex h-14 shrink-0 items-center border-b border-stone-200 px-4 dark:border-stone-800">
        <nav className={`mx-auto flex w-full ${width} items-center gap-6`}>
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

      <main className={fullBleed ? 'w-full flex-1' : `mx-auto w-full ${width} flex-1 px-4 py-8`}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/blend" element={<Blender />} />
          <Route path="/letterboxd" element={<LetterboxdConnect />} />
          <Route path="/letterboxd/:username" element={<LetterboxdSuggestions />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>

      <footer className="border-t border-stone-200 px-4 py-4 text-xs text-stone-500 dark:border-stone-800">
        <p className={`mx-auto ${width}`}>
          Information courtesy of IMDb (https://www.imdb.com), used with permission. This product uses the TMDB API
          but is not endorsed or certified by TMDB.
        </p>
      </footer>
    </div>
  )
}
