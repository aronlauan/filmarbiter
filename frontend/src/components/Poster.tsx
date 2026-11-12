interface Props {
  url: string | null
  title: string
  className?: string
  /** Alt text. Empty by default: posters always sit next to the visible title,
   *  so describing them would make screen readers announce the title twice. */
  alt?: string
  /** TMDB image width to request; the API returns w342 URLs. */
  size?: 'w92' | 'w185' | 'w342'
}

/** TMDB poster with a neutral placeholder when there's no image. */
export default function Poster({ url, title, className = '', alt = '', size = 'w342' }: Props) {
  if (!url) {
    return (
      <div
        className={`flex aspect-[2/3] items-center justify-center bg-stone-200 p-2 text-center text-xs text-stone-500 dark:bg-stone-800 dark:text-stone-400 ${className}`}
        aria-hidden="true"
      >
        {title}
      </div>
    )
  }
  return (
    <img
      src={url.replace('/w342/', `/${size}/`)}
      alt={alt}
      loading="lazy"
      className={`aspect-[2/3] bg-stone-200 object-cover dark:bg-stone-800 ${className}`}
    />
  )
}
