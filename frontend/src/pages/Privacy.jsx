export default function Privacy() {
  return (
    <div className="legal-page">
      <h1>Privacy Policy</h1>
      <p className="hint">Last updated 2026-08-18.</p>

      <p>
        Crond is a small, invite-only project built and operated by one person (Saaz Neupane).
        This isn't corporate legal boilerplate. It's a plain description of what data this
        app touches and why, since it acts on your behalf against real accounts (Google,
        job boards) and that deserves an honest account of what's happening.
      </p>

      <h2>What's collected</h2>
      <ul>
        <li>Account: your email and a hashed password (never the password itself).</li>
        <li>
          Profile: whatever you enter in the setup wizard, including name, address (geocoded to
          coordinates for commute-radius filtering), resume content, job search preferences.
        </li>
        <li>
          API keys you supply (Gemini, Adzuna): encrypted at rest, never logged or shown back
          to you in plain text after entry.
        </li>
        <li>
          Google OAuth: if you connect Google, a refresh token is stored encrypted at rest.
          It's used only to act on your behalf for the scopes below, never sold, never shared.
        </li>
        <li>
          Job search results and application history: stored in this app's database and
          mirrored (best-effort) into a Google Sheet in your own Google account.
        </li>
      </ul>

      <h2>Google scopes, and what each is actually used for</h2>
      <ul>
        <li><strong>Sheets</strong>: writes a copy of your job-search results into a spreadsheet in your own Drive.</li>
        <li><strong>Gmail send</strong>: sends cold outreach emails and daily summary reports from your own Gmail account, only when you've enabled that.</li>
        <li><strong>Gmail read</strong>: checks for bounce/reply notifications on emails this app sent, so it can avoid re-contacting the same person.</li>
        <li><strong>Drive (file-scoped)</strong>: stores generated resume PDFs it creates for you, in a folder it creates, not your whole Drive.</li>
      </ul>
      <p>
        You can revoke access at any time from your Google Account's
        {" "}<a href="https://myaccount.google.com/permissions" target="_blank" rel="noreferrer">connected apps settings</a>.
      </p>

      <h2>Cold email, honestly</h2>
      <p>
        If you enable cold outreach, this app sends emails to hiring contacts it finds,
        <em> from your own Gmail account</em>, using your account's own sending reputation.
        This app does not control how recipients or Google's spam systems react to that
        volume. Use your own judgment about the daily cap you set.
      </p>

      <h2>Third parties this app talks to</h2>
      <p>
        Google (OAuth/Sheets/Gmail/Drive), Adzuna and job board APIs (Greenhouse/Lever/Ashby,
        search only, no account needed), Google's Gemini API (resume/cover-letter/email
        generation, using your own key), and Brevo (transactional email for signup
        verification and password resets). Hosting is Render (application) and Supabase
        (Postgres database). None of these are sold your data; they're processors this app's
        own functionality depends on.
      </p>

      <h2>Data retention and deletion</h2>
      <p>
        Your data stays until you ask for it to be deleted. Email the contact below and it
        will be removed from this app's database. Anything already mirrored into your own
        Google Sheet or Drive is yours to delete directly, independent of this app.
      </p>

      <h2>Changes</h2>
      <p>This is a small, evolving project. This page will be updated in place if anything material changes, with the date above kept current.</p>

      <h2>Contact</h2>
      <p>Saaz Neupane, <a href="mailto:saazneu789@gmail.com">saazneu789@gmail.com</a></p>
    </div>
  );
}
