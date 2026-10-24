# EnvPlatform scroll animation

Scroll-scrubbed hero: the page scrolls, the 158-frame clip plays forward and backward,
and four short text beats fade in and out. Frames are cross-faded and the playhead is
eased, so it stays smooth even when the mouse wheel jumps.

## Use in your React app (Vite or CRA)
1. Copy `public/frames/` into your app's `public/` folder.
2. Copy `src/components/ScrollHero.jsx` and `ScrollHero.css` into your app.
3. Use it on any page, for example the landing or login page:
   `import ScrollHero from "./components/ScrollHero"; ... <ScrollHero />`
   - If your app is not served from `/`, pass `frameSrc={(i) => \`/base/frames/frame-${String(i+1).padStart(3,"0")}.webp\`}`.
   - `scrollScreens` sets the scroll length (default 6 screens). `beats` replaces the text.
   - `focusX` (0 to 1) picks which part of the frame stays visible on narrow screens.

## Try it without React
Run `python3 -m http.server` in this folder and open http://localhost:8000/demo.html
(use a server, not a double-click, so the frames load reliably).

## Notes
- Frames are 1280x720 WebP, about 9.7 MB in total. Put the app behind a CDN host
  (Cloudflare Pages, Vercel, Netlify) so they are cached; Render's free tier is slow for 158 files.
- Reduced-motion users get no easing, only direct scrubbing.
