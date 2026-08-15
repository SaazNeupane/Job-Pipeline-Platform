import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import FlowRail from "../components/FlowRail.jsx";
import { useAuth } from "../auth/AuthContext.jsx";

const ICON_PROPS = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" };

const SearchIcon = () => (
  <svg {...ICON_PROPS}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.5-4.5" /></svg>
);
const FilterIcon = () => (
  <svg {...ICON_PROPS}><path d="M4 5h16M7 12h10M10.5 19h3" /></svg>
);
const SwipeIcon = () => (
  <svg {...ICON_PROPS}><rect x="6" y="4" width="12" height="16" rx="2" /><path d="M2 12h3M19 12h3M4 9l-2 3 2 3M20 9l2 3-2 3" /></svg>
);
const TailorIcon = () => (
  <svg {...ICON_PROPS}><path d="M4 20l1-4 11-11 3 3-11 11-4 1z" /><path d="M13 6l3 3" /></svg>
);
const ApplyIcon = () => (
  <svg {...ICON_PROPS}><path d="M21 3L11 13" /><path d="M21 3l-7 18-4-8-8-4 19-6z" /></svg>
);

const PROCESS = [
  { key: "search", label: "Search real postings", icon: <SearchIcon /> },
  { key: "filter", label: "Filter to real fits", icon: <FilterIcon /> },
  { key: "swipe", label: "Swipe to pick favorites", icon: <SwipeIcon /> },
  { key: "tailor", label: "Tailor resume + letter", icon: <TailorIcon /> },
  { key: "apply", label: "Apply yourself", icon: <ApplyIcon /> },
];

const SETUP_STEPS = [
  {
    n: "01",
    title: "About you",
    body: "Your name, country, and a real address, typed in plain. It's geocoded automatically for any lane that uses a commute-radius filter, so there's no manual coordinate lookup.",
  },
  {
    n: "02",
    title: "Job types (lanes)",
    body: "A lane is a category of job to search for, with its own keywords, filters, and tailored resume. Pick ready-made presets, build your own, or both. Each lane can target a different country, remote/onsite preference, salary range, and set of sources.",
  },
  {
    n: "03",
    title: "Your resume",
    body: "Enter your real work history once, no matter how many lanes you picked. Tag each job, skill, and project to the lane(s) it's relevant to, so an entry tagged to one lane never bleeds into another's resume. Anything left untagged is treated as general background and shown everywhere.",
  },
  {
    n: "04",
    title: "API keys",
    body: "Your own free Adzuna key for job search, and a Gemini key for cover letters and light resume rewording. Both run under your own account and are never shared with anyone else using this.",
  },
  {
    n: "05",
    title: "Connect Google",
    body: "A real OAuth connection to your own Google account, so the pipeline can act as you: reading and writing one Google Sheet, sending mail from your Gmail, storing held resumes on your Drive. It never touches anyone else's account.",
  },
  {
    n: "06",
    title: "Review",
    body: "A last look at everything before it's saved. Continuing creates your own Google Sheet, where every result lives from then on: applications sent, postings held for review, a daily summary.",
  },
  {
    n: "07",
    title: "Done",
    body: "From here the daily run happens on its own, on our servers. Nothing to install, nothing to keep running on your own machine. Come back any time to swipe and check your dashboard.",
  },
];

function TerminalWindow({ children }) {
  return (
    <div className="terminal-window">
      <div className="terminal-titlebar">
        <span className="terminal-dot" />
        <span className="terminal-dot" />
        <span className="terminal-dot" />
        <span className="terminal-title">job-pipeline — zsh</span>
      </div>
      <div className="terminal-body">{children}</div>
    </div>
  );
}

export default function Home() {
  const { user, ready } = useAuth();
  const { hash } = useLocation();

  useEffect(() => {
    if (hash === "#guide") {
      document.getElementById("guide")?.scrollIntoView({ behavior: "smooth" });
    }
  }, [hash]);

  return (
    <>
      <div className="hero">
        <TerminalWindow>
          <p className="terminal-line"><span className="terminal-prompt">$</span> ./run_pipeline --daily</p>
          <h1 className="terminal-h1">Your job search, running itself<span className="terminal-cursor">_</span></h1>
          <p className="lede terminal-lede">
            It searches real postings every day and filters them down to ones worth your time. You swipe
            through to pick the jobs you actually want, and it tailors a resume and cover letter for each
            one you like. You apply yourself, from your own dashboard. Everything runs under your own
            accounts, and it never invents anything about you.
          </p>
          <div className="hero-actions">
            {ready && user ? (
              <Link className="button primary" to="/dashboard">Go to your dashboard</Link>
            ) : (
              <Link className="button primary" to="/signup">Get started</Link>
            )}
            <a className="button secondary" href="#guide">Read the guide first</a>
          </div>
        </TerminalWindow>
      </div>

      <div className="process-strip">
        <FlowRail horizontal steps={PROCESS.map((p) => ({ ...p, state: "static" }))} />
      </div>

      <div id="guide" className="guide-section">
        <p className="eyebrow">The full picture</p>
        <h2 className="guide-heading">How this works</h2>
        <p className="lede">
          Every step below also has its own instructions when you get there. This is just everything
          in one place, worth a read before you start.
        </p>

        <div className="card">
          <h3 style={{ marginTop: 0 }}>What it actually does</h3>
          <p style={{ marginBottom: 0 }}>
            Every day, this searches real job postings (Adzuna, Greenhouse, hiring.cafe) and filters
            them down to real matches for the lanes you set up. Those land in a swipe queue: go through
            them one at a time, right for "I'd apply to this," left for "no." Right-swipe a posting and
            it tailors your resume and writes a cover letter for it, then hands you both from your
            dashboard so you can go apply yourself. Nothing here uses anyone else's data or account but
            your own: your own Google account, your own resume, your own applications going out under
            your own name.
          </p>
        </div>

        <ol className="guide-steps">
          {SETUP_STEPS.map((step) => (
            <li key={step.n} className="guide-step">
              <span className="guide-step-num">{step.n}</span>
              <div>
                <h3 className="guide-step-title">{step.title}</h3>
                <p className="guide-step-body">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>

        <h3>Ongoing: swiping and the dashboard</h3>
        <p>
          Once you're set up, come back any time. Your dashboard links to your swipe queue: swipe
          through new postings as they arrive, and each right swipe generates a resume, a cover
          letter, and a Drive link, then drops it into your dashboard to apply with. The dashboard
          also shows everything already applied to and a log of recent runs. "Mark as Applied" is
          for once you've actually submitted something yourself; "Dismiss" sets a posting aside for
          good.
        </p>

        <div className="card">
          <h3 style={{ marginTop: 0 }}>A few important limits, on purpose</h3>
          <ul style={{ marginBottom: 0 }}>
            <li>Nothing gets submitted for you. You decide what's worth applying to by swiping, and you're the one who hits submit on the actual form.</li>
            <li>It only ever uses information you actually gave it. It won't invent a skill, a number, or a job you didn't have.</li>
            <li>It only surfaces real, live postings found through the search sources above, nothing scraped from a site that doesn't allow it.</li>
          </ul>
        </div>
      </div>
    </>
  );
}
