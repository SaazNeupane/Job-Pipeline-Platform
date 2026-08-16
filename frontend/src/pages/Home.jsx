import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import FlowRail from "../components/FlowRail.jsx";
import { ApplyIcon, FilterIcon, SearchIcon, SwipeIcon, TailorIcon } from "../components/icons.jsx";
import { useAuth } from "../auth/AuthContext.jsx";
import { useInViewport } from "../hooks/useInViewport.js";
import { useTypewriter } from "../hooks/useTypewriter.js";

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
    body: "A real OAuth connection to your own Google account, so the pipeline can act as you: reading and writing one Google Sheet, sending mail from your Gmail and checking that same inbox for a bounce or a reply, storing held resumes on your Drive. It never touches anyone else's account.",
  },
  {
    n: "06",
    title: "Review",
    body: "A last look at everything before it's saved. Continuing creates your own Google Sheet, a readable mirror of everything that happens from then on: applications sent, postings held for review, a daily summary. Your account's own database is what actually drives the app; the Sheet is just a copy you can open and read.",
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
        <span className="terminal-title">crond — zsh</span>
      </div>
      <div className="terminal-body">{children}</div>
    </div>
  );
}

export default function Home() {
  const { user, ready } = useAuth();
  const { hash } = useLocation();
  const { shown: promptShown, done: promptDone } = useTypewriter("./run_pipeline --daily", 32);
  const [stage, setStage] = useState(0); // 0 = typing, 1 = headline, 2 = lede, 3 = actions
  const [processRef, processInView] = useInViewport(0.3);
  const [guideRef, guideInView] = useInViewport(0.15);

  useEffect(() => {
    if (hash === "#guide") {
      document.getElementById("guide")?.scrollIntoView({ behavior: "smooth" });
    }
  }, [hash]);

  useEffect(() => {
    if (!promptDone) return;
    const timers = [
      setTimeout(() => setStage(1), 150),
      setTimeout(() => setStage(2), 550),
      setTimeout(() => setStage(3), 900),
    ];
    return () => timers.forEach(clearTimeout);
  }, [promptDone]);

  return (
    <>
      <div className="hero">
        <TerminalWindow>
          <p className="terminal-line">
            <span className="terminal-prompt">$</span> {promptShown}
            {!promptDone && <span className="terminal-cursor">_</span>}
          </p>
          <h1 className={`terminal-h1 reveal${stage >= 1 ? " reveal-in" : ""}`}>
            Your job search, running itself{stage >= 1 && <span className="terminal-cursor">_</span>}
          </h1>
          <p className={`lede terminal-lede reveal${stage >= 2 ? " reveal-in" : ""}`}>
            It searches real postings every day and filters them down to ones worth your time. You swipe
            through to pick the jobs you actually want, and it tailors a resume and cover letter for each
            one you like. You apply yourself, from your own dashboard. Everything runs under your own
            accounts, and it never invents anything about you.
          </p>
          <div className={`hero-actions reveal${stage >= 3 ? " reveal-in" : ""}`}>
            {ready && user ? (
              <Link className="button primary" to="/dashboard">Go to your dashboard</Link>
            ) : (
              <Link className="button primary" to="/signup">Get started</Link>
            )}
            <a className="button secondary" href="#guide">Read the guide first</a>
          </div>
        </TerminalWindow>
      </div>

      <div ref={processRef} className={`process-strip${processInView ? " in-view" : ""}`}>
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
            Every day, this searches real job postings (Adzuna, Greenhouse, Lever, Ashby, hiring.cafe)
            and filters them down to real matches for the lanes you set up. Those land in a swipe
            queue: go through them one at a time, right for "I'd apply to this," left for "no."
            Right-swipe a posting and it tailors your resume and writes a cover letter for it, then
            hands you both from your dashboard so you can go apply yourself. A separate cold email
            pipeline runs alongside this one and does send on its own; see below for what that means.
            Nothing here uses anyone else's data or account but your own: your own Google account, your
            own resume, your own applications going out under your own name.
          </p>
        </div>

        <ol ref={guideRef} className={`guide-steps${guideInView ? " in-view" : ""}`}>
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

        <h3>Cold email, the one thing that sends on its own</h3>
        <p>
          Separately from the swipe queue, this also searches Adzuna and hiring.cafe for postings that
          list a real, published contact email, never a guessed one like careers@company.com. When it
          finds one, it writes a short email for it and sends that email from your Gmail without
          waiting for you to review it first. It starts at a low daily cap, raises that cap after a
          couple of weeks, and holds it back down if too many of those emails start bouncing. Every
          email it sends, along with any reply or bounce, shows up on the cold email page.
        </p>

        <div className="card">
          <h3 style={{ marginTop: 0 }}>A few important limits, on purpose</h3>
          <ul style={{ marginBottom: 0 }}>
            <li>Nothing gets submitted for you on the job-application side. You decide what's worth applying to by swiping, and you're the one who hits submit on the actual form. Cold email, described above, is the one exception, and it only ever emails a real address it found published, never one it guessed.</li>
            <li>It only ever uses information you actually gave it. It won't invent a skill, a number, or a job you didn't have.</li>
            <li>It only surfaces real, live postings found through the search sources above, nothing scraped from a site that doesn't allow it.</li>
          </ul>
        </div>
      </div>
    </>
  );
}
