import React, { useEffect, useRef, useState } from 'react';
import './ScrollHero.css';

// Frames live in public/frames/frame-001.webp ... frame-158.webp (1920x1080 WebP).
const defaultSrc = (i) => `/frames/frame-${String(i + 1).padStart(3, '0')}.webp`;

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const pad = (n) => String(n).padStart(2, '0');

/**
 * Scroll-scrubbed hero. The section is `scrollScreens` viewports tall; while it is pinned the
 * frame sequence is scrubbed on a canvas, the intro (children) fades out and the `beats`
 * fade in and out at their [from, to] positions along the 0..1 scroll progress.
 */
export default function ScrollHero({
  frameCount = 158,
  frameSrc = defaultSrc,
  beats = [],
  scrollScreens = 7,
  focusX = 0.62,
  introUntil = 0.1,
  children,
}) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const barRef = useRef(null);
  const hintRef = useRef(null);
  const introRef = useRef(null);
  const beatEls = useRef([]);
  const dotEls = useRef([]);
  const latest = useRef({ frameSrc, beats, introUntil });
  const [loaded, setLoaded] = useState(0);

  useEffect(() => {
    latest.current = { frameSrc, beats, introUntil };
  });

  useEffect(() => {
    const wrap = wrapRef.current;
    const cv = canvasRef.current;
    const ctx = cv.getContext('2d', { alpha: false });
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const frames = new Array(frameCount).fill(null);
    let cur = 0;
    let target = 0;
    let raf = 0;
    let last = performance.now();
    let key = -1;
    let alive = true;
    let done = 0;

    const size = () => {
      const d = Math.min(window.devicePixelRatio || 1, 2);
      cv.width = Math.round(cv.clientWidth * d);
      cv.height = Math.round(cv.clientHeight * d);
      // A resize resets the context state, so re-apply high quality resampling.
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      key = -1;
    };

    // Nearest loaded frame, so scrubbing works while frames are still arriving.
    const get = (i) => {
      for (let j = i; j >= 0; j -= 1) if (frames[j]) return frames[j];
      for (let j = i; j < frameCount; j += 1) if (frames[j]) return frames[j];
      return null;
    };

    const paint = (img, alpha) => {
      if (!img) return;
      const s = Math.max(cv.width / img.naturalWidth, cv.height / img.naturalHeight);
      const w = img.naturalWidth * s;
      const h = img.naturalHeight * s;
      ctx.globalAlpha = alpha;
      ctx.drawImage(
        img,
        Math.round((cv.width - w) * focusX),
        Math.round((cv.height - h) / 2),
        Math.round(w),
        Math.round(h),
      );
    };

    // Cross-fade between neighbouring frames for sub-frame smoothness.
    const draw = (p) => {
      const i = Math.floor(p);
      const f = p - i;
      ctx.globalAlpha = 1;
      ctx.fillStyle = '#06100f';
      ctx.fillRect(0, 0, cv.width, cv.height);
      paint(get(i), 1);
      if (f > 0.02 && i + 1 < frameCount) paint(get(i + 1), f);
      ctx.globalAlpha = 1;
    };

    const onScroll = () => {
      const r = wrap.getBoundingClientRect();
      target = clamp(-r.top / Math.max(1, r.height - window.innerHeight)) * (frameCount - 1);
    };

    const tick = (t) => {
      const dt = Math.min((t - last) / 1000, 0.05);
      last = t;
      cur += (target - cur) * (reduce ? 1 : 1 - Math.exp(-dt * 9));
      if (Math.abs(target - cur) < 0.001) cur = target;
      const k = Math.round(cur * 100);
      if (k !== key) {
        key = k;
        draw(cur);
      }

      const q = cur / (frameCount - 1);
      const { beats: bts, introUntil: until } = latest.current;

      if (introRef.current) {
        const o = 1 - clamp((q - until) / 0.05);
        introRef.current.style.opacity = o;
        introRef.current.style.transform = `translateY(${(1 - o) * -24}px)`;
        introRef.current.style.pointerEvents = o > 0.5 ? 'auto' : 'none';
      }

      let active = -1;
      bts.forEach((b, n) => {
        const el = beatEls.current[n];
        const e = 0.04;
        const o = clamp((q - b.from) / e) * (b.to >= 1 ? 1 : clamp((b.to - q) / e));
        if (o > 0.5) active = n;
        if (!el) return;
        el.style.opacity = o;
        el.style.transform = `translateY(${(1 - o) * 18}px)`;
      });
      dotEls.current.forEach((el, n) => el && el.classList.toggle('is-active', n === active));

      if (barRef.current) barRef.current.style.transform = `scaleX(${q})`;
      if (hintRef.current) hintRef.current.style.opacity = 1 - clamp(q / 0.03);
      raf = requestAnimationFrame(tick);
    };

    // Load every 8th frame first, then 4th, 2nd, rest: the whole timeline works early.
    const order = [];
    const seen = new Set();
    [8, 4, 2, 1].forEach((st) => {
      for (let i = 0; i < frameCount; i += st) {
        if (!seen.has(i)) {
          seen.add(i);
          order.push(i);
        }
      }
    });
    let next = 0;
    const worker = async () => {
      while (alive && next < order.length) {
        const i = order[next];
        next += 1;
        const img = new Image();
        img.decoding = 'async';
        img.src = latest.current.frameSrc(i);
        try {
          await img.decode();
        } catch {
          continue; // skip a frame that fails to load
        }
        frames[i] = img;
        key = -1;
        done += 1;
        if (done % 6 === 0) setLoaded(done);
      }
    };
    Promise.all(Array.from({ length: 6 }, () => worker())).then(() => alive && setLoaded(frameCount));

    size();
    onScroll();
    cur = target;
    raf = requestAnimationFrame(tick);
    window.addEventListener('scroll', onScroll, { passive: true });
    const onResize = () => {
      size();
      onScroll();
    };
    window.addEventListener('resize', onResize);
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onResize);
    };
  }, [frameCount, focusX]);

  const pct = Math.round((loaded / frameCount) * 100);

  return (
    <section
      className="sh"
      ref={wrapRef}
      style={{ height: `${scrollScreens * 100}vh` }}
      aria-label="How EnvPlatform works"
    >
      <div className="sh__stick">
        <canvas
          ref={canvasRef}
          role="img"
          aria-label="Camera moving toward floating data panels in a rainy green city"
        />
        <div className="sh__scrim" />
        <div className="sh__vignette" />
        <div className="sh__grain" />

        <div className="sh__intro" ref={introRef}>
          {children}
        </div>

        {beats.map((b, n) => (
          <div className="sh__beat" key={b.title} ref={(el) => { beatEls.current[n] = el; }}>
            <span className="sh__beat-label">
              <b>{pad(n + 1)}</b>
              <i />
              {b.label}
            </span>
            <h2>{b.title}</h2>
            <p>{b.text}</p>
          </div>
        ))}

        <div className="sh__hint" ref={hintRef}>
          <span>Scroll to explore</span>
          <i />
        </div>

        <div className="sh__steps" aria-hidden="true">
          {beats.map((b, n) => (
            <span key={b.title} ref={(el) => { dotEls.current[n] = el; }}>
              <em>{pad(n + 1)}</em>
              {b.label}
            </span>
          ))}
        </div>

        <div className="sh__bar"><i ref={barRef} /></div>

        <div className={`sh__load ${loaded >= frameCount ? 'is-done' : ''}`} aria-live="polite">
          <i style={{ width: `${pct}%` }} />
          <span>{loaded >= frameCount ? 'Scene ready' : `Loading scene ${pct}%`}</span>
        </div>
      </div>
    </section>
  );
}
