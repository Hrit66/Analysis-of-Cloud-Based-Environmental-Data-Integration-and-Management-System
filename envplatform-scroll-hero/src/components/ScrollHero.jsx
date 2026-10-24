import { useEffect, useRef, useState } from "react";
import "./ScrollHero.css";

// Frames live in public/frames/frame-001.webp ... frame-158.webp
const defaultSrc = (i) => `/frames/frame-${String(i + 1).padStart(3, "0")}.webp`;

export const DEFAULT_BEATS = [
  { from: 0, to: 0.22, title: "Upload raw environmental data.",
    text: "CSV, Excel or JSON, with messy headers, mixed units and missing values." },
  { from: 0.28, to: 0.5, title: "Cleaned, with every change listed.",
    text: "Duplicates, renamed columns and blanked values are counted in a data-quality report." },
  { from: 0.56, to: 0.78, title: "Analysed against standard indices.",
    text: "AQI, WQI, rainfall and temperature trends, plus anomaly flags you can inspect." },
  { from: 0.84, to: 1, title: "Forecast with an honest baseline.",
    text: "Every forecast is compared with persistence, and skipped when it cannot beat it." },
];

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));

export default function ScrollHero({
  frameCount = 158, frameSrc = defaultSrc, beats = DEFAULT_BEATS,
  scrollScreens = 6, focusX = 0.62,
}) {
  const wrapRef = useRef(null), canvasRef = useRef(null), barRef = useRef(null), hintRef = useRef(null);
  const beatEls = useRef([]);
  const props = useRef({ frameSrc, beats });
  props.current = { frameSrc, beats };            // latest props without restarting the effect
  const [loaded, setLoaded] = useState(0);

  useEffect(() => {
    const wrap = wrapRef.current, cv = canvasRef.current, ctx = cv.getContext("2d");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const frames = new Array(frameCount).fill(null);
    let cur = 0, target = 0, raf = 0, last = performance.now(), key = -1, alive = true, done = 0;

    const size = () => {
      const d = Math.min(window.devicePixelRatio || 1, 2);
      cv.width = Math.round(cv.clientWidth * d); cv.height = Math.round(cv.clientHeight * d); key = -1;
    };
    const get = (i) => {            // nearest loaded frame, so scrubbing works while loading
      for (let j = i; j >= 0; j--) if (frames[j]) return frames[j];
      for (let j = i; j < frameCount; j++) if (frames[j]) return frames[j];
      return null;
    };
    const paint = (img, alpha) => {
      if (!img) return;
      const s = Math.max(cv.width / img.naturalWidth, cv.height / img.naturalHeight);
      const w = img.naturalWidth * s, h = img.naturalHeight * s;
      ctx.globalAlpha = alpha;
      ctx.drawImage(img, (cv.width - w) * focusX, (cv.height - h) / 2, w, h);
    };
    const draw = (p) => {           // cross-fade between neighbours for sub-frame smoothness
      const i = Math.floor(p), f = p - i;
      paint(get(i), 1);
      if (f > 0.02 && i + 1 < frameCount) paint(get(i + 1), f);
      ctx.globalAlpha = 1;
    };
    const onScroll = () => {
      const r = wrap.getBoundingClientRect();
      target = clamp(-r.top / Math.max(1, r.height - window.innerHeight)) * (frameCount - 1);
    };
    const tick = (t) => {
      const dt = Math.min((t - last) / 1000, 0.05); last = t;
      cur += (target - cur) * (reduce ? 1 : 1 - Math.exp(-dt * 9));
      if (Math.abs(target - cur) < 0.001) cur = target;
      const k = Math.round(cur * 100);
      if (k !== key) { key = k; draw(cur); }
      const q = cur / (frameCount - 1);
      props.current.beats.forEach((b, n) => {
        const el = beatEls.current[n]; if (!el) return;
        const e = 0.04;
        const o = (b.from <= 0 ? 1 : clamp((q - b.from) / e)) * (b.to >= 1 ? 1 : clamp((b.to - q) / e));
        el.style.opacity = o; el.style.transform = `translateY(${(1 - o) * 14}px)`;
      });
      if (barRef.current) barRef.current.style.transform = `scaleY(${q})`;
      if (hintRef.current) hintRef.current.style.opacity = 1 - clamp(q / 0.03);
      raf = requestAnimationFrame(tick);
    };

    // Load every 8th frame first, then 4th, 2nd, rest: the whole timeline works early.
    const order = [], seen = new Set();
    [8, 4, 2, 1].forEach((st) => { for (let i = 0; i < frameCount; i += st) if (!seen.has(i)) { seen.add(i); order.push(i); } });
    let next = 0;
    const worker = async () => {
      while (alive && next < order.length) {
        const i = order[next++], img = new Image();
        img.src = props.current.frameSrc(i);
        try { await img.decode(); } catch { continue; }   // skip a frame that fails to load
        frames[i] = img; key = -1;
        if (++done % 6 === 0) setLoaded(done);
      }
    };
    Promise.all(Array.from({ length: 6 }, () => worker())).then(() => alive && setLoaded(frameCount));

    size(); onScroll(); cur = target; raf = requestAnimationFrame(tick);
    window.addEventListener("scroll", onScroll, { passive: true });
    const onResize = () => { size(); onScroll(); };
    window.addEventListener("resize", onResize);
    return () => {
      alive = false; cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onResize);
    };
  }, [frameCount, focusX]);

  return (
    <section className="sh" ref={wrapRef} style={{ height: `${scrollScreens * 100}vh` }} aria-label="How EnvPlatform works">
      <div className="sh__stick">
        <canvas ref={canvasRef} role="img" aria-label="Camera moving toward floating data panels in a rainy green city" />
        <div className="sh__scrim" />
        {beats.map((b, n) => (
          <div className="sh__beat" key={n} ref={(el) => (beatEls.current[n] = el)}>
            <h2>{b.title}</h2><p>{b.text}</p>
          </div>
        ))}
        <div className="sh__hint" ref={hintRef}>Scroll to explore</div>
        <div className="sh__bar"><i ref={barRef} /></div>
        {loaded < frameCount && <div className="sh__load">Loading {Math.round((loaded / frameCount) * 100)}%</div>}
      </div>
    </section>
  );
}
