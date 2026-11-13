/** Feature switches, set at build time. Everything is on unless turned off.
 *
 * Letterboxd is off in production (VITE_LETTERBOXD_ENABLED=false in render.yaml):
 * Letterboxd blocks requests from Render's servers, so the pages show "Coming soon"
 * instead. The backend has the matching LETTERBOXD_ENABLED setting. */
export const LETTERBOXD_ENABLED = import.meta.env.VITE_LETTERBOXD_ENABLED !== 'false'
