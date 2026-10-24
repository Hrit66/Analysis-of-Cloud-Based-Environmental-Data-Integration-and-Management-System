import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  ArrowRight, Wind, Droplets, Thermometer, CloudRain, AlertTriangle, FileText,
  UploadCloud, Sparkles, LineChart, TrendingUp, Building2, ShieldCheck, Bell, CheckCircle2,
} from 'lucide-react';
import ScrollHero from '../components/landing/ScrollHero';
import logo from '../assets/vr.png';
import './Landing.css';

const BEATS = [
  {
    from: 0.16, to: 0.36, label: 'Upload',
    title: 'Drop in raw environmental data.',
    text: 'CSV, Excel or JSON — messy headers, mixed units and missing values included.',
  },
  {
    from: 0.40, to: 0.58, label: 'Clean',
    title: 'Cleaned, with every change on record.',
    text: 'Duplicates removed, columns renamed and blanks filled — each one counted in a data-quality report.',
  },
  {
    from: 0.62, to: 0.80, label: 'Analyse',
    title: 'Scored against standard indices.',
    text: 'AQI, WQI, rainfall and temperature trends, with anomaly flags you can inspect row by row.',
  },
  {
    from: 0.84, to: 1, label: 'Forecast',
    title: 'Forecast with an honest baseline.',
    text: 'Every model is checked against persistence — and skipped when it cannot beat it.',
  },
];

const FEATURES = [
  { icon: Wind, title: 'Air Quality (AQI)', text: 'Pollutant-level breakdowns, category bands and hourly-to-seasonal trends.' },
  { icon: Droplets, title: 'Water Quality (WQI)', text: 'pH, turbidity, dissolved oxygen and more, rolled into a single index you can track.' },
  { icon: Thermometer, title: 'Temperature', text: 'Local and regional temperature patterns compared against historical baselines.' },
  { icon: CloudRain, title: 'Rainfall outlook', text: 'Probability-based rain outlook, wet-day seasonality and drought indicators.' },
  { icon: AlertTriangle, title: 'Anomaly detection', text: 'Statistical flags for readings that break the pattern, with context to judge them.' },
  { icon: FileText, title: 'Reports', text: 'Export PDF and Excel reports with charts, quality notes and forecast caveats.' },
];

const STEPS = [
  { icon: UploadCloud, title: 'Upload', text: 'Bring any station export or spreadsheet. Column types and units are detected automatically.' },
  { icon: Sparkles, title: 'Clean', text: 'Duplicates, outliers and gaps are handled, and the data-quality report records what changed.' },
  { icon: LineChart, title: 'Analyse', text: 'Dashboards per index, trends over time and anomalies ranked by how unusual they are.' },
  { icon: TrendingUp, title: 'Forecast', text: 'Short-range forecasts benchmarked against persistence so you know when to trust them.' },
];

const TEAM_POINTS = [
  { icon: Building2, text: 'Organisation workspaces with admin, analyst and viewer roles.' },
  { icon: ShieldCheck, text: 'Verified email sign-up, invite links and optional two-factor authentication.' },
  { icon: Bell, text: 'Notifications when a dataset finishes processing or an anomaly is flagged.' },
];

const QUALITY_ROWS = [
  ['Rows received', '48,212'],
  ['Duplicates removed', '1,306'],
  ['Columns renamed', '7'],
  ['Values imputed', '2,948'],
  ['Unit conversions', '3'],
];

const reveal = {
  initial: { opacity: 0, y: 28 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, margin: '-80px' },
  transition: { duration: 0.7, ease: [0.16, 1, 0.3, 1] },
};

const Landing = () => {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <div className="landing">
      <header className={`ld-nav ${scrolled ? 'is-scrolled' : ''}`}>
        <div className="ld-nav__inner">
          <Link to="/" className="ld-brand">
            <img src={logo} alt="" className="h-9 w-9 object-contain" />
            <span>EnvPlatform</span>
          </Link>
          <nav className="ld-nav__links">
            <a href="#features">Features</a>
            <a href="#workflow">How it works</a>
            <a href="#teams">Teams</a>
          </nav>
          <div className="flex items-center gap-2">
            <Link to="/login" className="ld-btn ld-btn--ghost">Sign in</Link>
            <Link to="/signup" className="ld-btn ld-btn--primary">
              Get started <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </header>

      <ScrollHero beats={BEATS} scrollScreens={7} focusX={0.64} introUntil={0.09}>
        <span className="ld-eyebrow">Cloud-based environmental analytics</span>
        <h1 className="ld-hero-title">
          From raw readings to decisions <span className="ld-gradient-text">you can defend.</span>
        </h1>
        <p className="ld-hero-text">
          EnvPlatform integrates air, water and climate data, cleans it, scores it against
          standard indices and forecasts what comes next — with every step on record.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link to="/signup" className="ld-btn ld-btn--primary ld-btn--lg">
            Create a free account <ArrowRight className="h-4 w-4" />
          </Link>
          <Link to="/login" className="ld-btn ld-btn--outline ld-btn--lg">Sign in</Link>
        </div>
        <div className="ld-hero-meta">
          <span>CSV · Excel · JSON</span>
          <span>AQI · WQI · Rain · Temp</span>
          <span>PDF &amp; Excel reports</span>
        </div>
      </ScrollHero>

      <main className="ld-body">
        <section id="features" className="ld-section">
          <motion.div {...reveal} className="ld-section__head">
            <span className="ld-eyebrow">What you get</span>
            <h2>One workspace for every environmental signal.</h2>
            <p>Each index has its own dashboard, but they share the same cleaned data, the same anomaly rules and the same reports.</p>
          </motion.div>
          <div className="ld-grid ld-grid--3">
            {FEATURES.map(({ icon: Icon, title, text }, i) => (
              <motion.article
                key={title}
                {...reveal}
                transition={{ ...reveal.transition, delay: (i % 3) * 0.08 }}
                className="ld-card"
              >
                <div className="ld-card__icon"><Icon className="h-5 w-5" /></div>
                <h3>{title}</h3>
                <p>{text}</p>
              </motion.article>
            ))}
          </div>
        </section>

        <section id="workflow" className="ld-section">
          <motion.div {...reveal} className="ld-section__head">
            <span className="ld-eyebrow">How it works</span>
            <h2>Four steps, nothing hidden.</h2>
            <p>The same pipeline runs for every upload, and each stage leaves a record you can review.</p>
          </motion.div>
          <div className="ld-steps">
            {STEPS.map(({ icon: Icon, title, text }, i) => (
              <motion.div
                key={title}
                {...reveal}
                transition={{ ...reveal.transition, delay: i * 0.1 }}
                className="ld-step"
              >
                <div className="ld-step__top">
                  <span className="ld-step__num">{String(i + 1).padStart(2, '0')}</span>
                  <Icon className="h-5 w-5 text-cyan-300" />
                </div>
                <h3>{title}</h3>
                <p>{text}</p>
              </motion.div>
            ))}
          </div>
        </section>

        <section id="teams" className="ld-section">
          <div className="ld-split">
            <motion.div {...reveal}>
              <span className="ld-eyebrow">Built for teams</span>
              <h2>Share one source of truth across your organisation.</h2>
              <p className="ld-lead">
                Invite colleagues, give them the right level of access and keep every dataset,
                report and alert in one place.
              </p>
              <ul className="ld-points">
                {TEAM_POINTS.map(({ icon: Icon, text }) => (
                  <li key={text}>
                    <span className="ld-points__icon"><Icon className="h-4 w-4" /></span>
                    <span>{text}</span>
                  </li>
                ))}
              </ul>
              <Link to="/organization/apply" className="ld-link">
                Register your organisation <ArrowRight className="h-4 w-4" />
              </Link>
            </motion.div>

            <motion.div {...reveal} transition={{ ...reveal.transition, delay: 0.12 }} className="ld-report">
              <div className="ld-report__head">
                <span className="ld-report__dot" />
                <span>Data-quality report</span>
                <em>example</em>
              </div>
              <ul>
                {QUALITY_ROWS.map(([label, value]) => (
                  <li key={label}>
                    <span>{label}</span>
                    <b>{value}</b>
                  </li>
                ))}
              </ul>
              <div className="ld-report__foot">
                <CheckCircle2 className="h-4 w-4 text-emerald-300" />
                <span>Forecast enabled — beats persistence baseline by 18%</span>
              </div>
            </motion.div>
          </div>
        </section>

        <section className="ld-section ld-section--cta">
          <motion.div {...reveal} className="ld-cta">
            <span className="ld-eyebrow">Get started</span>
            <h2>Bring your first dataset.</h2>
            <p>Create an account, upload a file and see your first dashboard in minutes.</p>
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              <Link to="/signup" className="ld-btn ld-btn--primary ld-btn--lg">
                Create a free account <ArrowRight className="h-4 w-4" />
              </Link>
              <Link to="/login" className="ld-btn ld-btn--outline ld-btn--lg">Sign in</Link>
            </div>
          </motion.div>
        </section>
      </main>

      <footer className="ld-footer">
        <div className="ld-footer__inner">
          <Link to="/" className="ld-brand">
            <img src={logo} alt="" className="h-7 w-7 object-contain" />
            <span>EnvPlatform</span>
          </Link>
          <nav>
            <Link to="/login">Sign in</Link>
            <Link to="/signup">Create account</Link>
            <Link to="/organization/apply">Organisations</Link>
          </nav>
          <span className="ld-footer__copy">© {new Date().getFullYear()} EnvPlatform</span>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
