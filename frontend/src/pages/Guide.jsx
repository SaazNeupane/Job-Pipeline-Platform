export default function Guide() {
  return (
    <>
      <h1>How this works</h1>
      <p className="lede">Read this once before you start. Every step below also has its own inline instructions when you get there; this page is just the full picture in one place.</p>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>What it actually does</h2>
        <p style={{ marginBottom: 0 }}>
          Every day, this searches real job postings (Adzuna, Greenhouse, hiring.cafe) and filters them
          down to real matches for the lanes you set up. Those land in a swipe queue: you go through
          them one at a time, right for "I'd apply to this," left for "no." Right swipe a posting and it
          tailors your resume and writes a cover letter for it, then hands you both from your dashboard
          so you can go apply yourself. Nothing here uses anyone else's data or account but your own:
          your own Google account, your own resume, your own applications going out under your own name.
        </p>
      </div>

      <h2>1. Before you open this wizard</h2>
      <p>You need Python and Git installed, and your own copy of this code. Check <code>README.md</code> in the folder you were given for the exact commands. In short: install Python 3.12+ and Git, get the code (clone or "Use this template" on GitHub), then run the launcher (<code>run_webapp.bat</code> on Windows, or <code>python -m webapp.app</code>) to open this wizard.</p>

      <h2>2. About you</h2>
      <p>Your name, country, and (optionally) address. Some application forms ask for a full mailing address; most don't. If you pick a lane with a commute-radius filter, you'll also need your coordinates. Google Maps gives you these with one right-click.</p>

      <h2>3. Job types (lanes)</h2>
      <p>A "lane" is a category of job to search for, with its own keywords, filters, and its own tailored resume. Pick one of the ready-made presets, build your own from scratch, or both. You can pick as many lanes as you want, and every lane can target a different country, remote/onsite preference, salary range, and set of sources.</p>

      <h2>4. Your resume</h2>
      <p>Enter your real work history once, no matter how many lanes you picked. For each job, skill category, and project, tick which lane(s) it's relevant to. An entry only tagged to one lane will never show up on another lane's resume: no experience bleeding across lanes. Anything left untagged is treated as general background and shown everywhere.</p>
      <p className="hint">Nothing here gets invented later. The pipeline only ever reorders, lightly rewords, and trims what you actually enter; it never adds new facts or numbers.</p>

      <h2>5. API keys</h2>
      <ul>
        <li><strong>Adzuna</strong>: job search. Sign up at <a href="https://developer.adzuna.com/" target="_blank" rel="noopener">developer.adzuna.com</a>.</li>
        <li><strong>Gemini</strong>: writes your cover letters and lightly rewords resume bullets to match each posting's language. Get a free key at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com/apikey</a>.</li>
      </ul>

      <h2>6. Connect your Google account</h2>
      <p>This is the fiddliest step, and it's fiddly because Google requires it, not because this app does. You're creating a small, private "app" in your own Google Cloud account that only you can use, so this pipeline can act as you: reading and writing one Google Sheet, sending mail from your Gmail, and storing held resumes on your Drive. Full instructions are on that step of the wizard when you get there.</p>

      <h2>7. Review &amp; create your Sheet</h2>
      <p>A quick look at everything before it's saved. Continuing also creates your own Google Sheet. This is where every result lives: applications sent, ones held for your review, and a daily summary. Bookmark it, or just use this app's dashboard instead.</p>

      <h2>8. Push to GitHub</h2>
      <p>The daily run happens on GitHub's servers (GitHub Actions), not your own computer, so it can run every morning even if your laptop is off. This step sends your keys and profile to your own copy of the repo as GitHub "secrets" so the scheduled run can use them. If you have GitHub's <code>gh</code> command-line tool installed, the wizard can do this for you with one click; otherwise it shows you the exact commands to run yourself.</p>

      <h2>9. Ongoing: swiping and the dashboard</h2>
      <p>Once you're set up, come back to this app any time. The home page links to your dashboard, and there's a link from there to your swipe queue. Swipe through new postings as they come in; each right swipe generates a resume, a cover letter, and a Drive link, and drops it into your dashboard for you to apply with. The dashboard also shows everything already applied to and a log of recent runs. "Mark as Applied" is for once you've actually submitted something yourself; "Dismiss" removes a posting you don't want to pursue, for good.</p>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>A few important limits, on purpose</h2>
        <ul style={{ marginBottom: 0 }}>
          <li>Nothing gets submitted for you. You decide what's worth applying to by swiping, and you're the one who hits submit on the actual form.</li>
          <li>It only ever uses information you actually gave it. It won't invent a skill, a number, or a job you didn't have.</li>
          <li>It only applies to real, live postings it found through the search sources above, nothing scraped from sites that don't allow it.</li>
        </ul>
      </div>
    </>
  );
}
