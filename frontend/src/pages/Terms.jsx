export default function Terms() {
  return (
    <div className="legal-page">
      <h1>Terms of Service</h1>
      <p className="hint">Last updated 2026-08-18.</p>

      <p>
        Crond is a small, invite-only project, not a funded company. These terms are short on
        purpose — the goal is an honest description of what you're agreeing to, not a wall of
        boilerplate.
      </p>

      <h2>What this is</h2>
      <p>
        A job-search assistant: it searches job boards, filters matches against your
        preferences, generates tailored resumes/cover letters, and (optionally) sends cold
        outreach emails and daily summary reports on your behalf using your own connected
        Google account and your own supplied API keys.
      </p>

      <h2>No warranty</h2>
      <p>
        Provided as-is, with no guarantee of uptime, accuracy, or availability. Job matches,
        generated resume/cover-letter content, and cold-email outreach are AI-assisted —
        review everything before it goes out under your name. This app is not responsible for
        the outcome of any job application, email sent, or account action taken through it.
      </p>

      <h2>Your responsibility</h2>
      <ul>
        <li>You're responsible for the accuracy of your own resume/profile data.</li>
        <li>You're responsible for reviewing generated content before it's sent or submitted anywhere.</li>
        <li>You're responsible for how you configure cold-email volume — it sends through your own Gmail account and affects your own account's standing with Google.</li>
        <li>Invite codes are for people you trust to use this reasonably — don't share your account.</li>
      </ul>

      <h2>Account and data</h2>
      <p>
        See the <a href="/privacy">Privacy Policy</a> for what's collected and how. You can
        request account deletion at any time (contact below) and can revoke Google access
        independently from your Google Account settings.
      </p>

      <h2>Termination</h2>
      <p>
        Access may be suspended or revoked for abuse (of this app, of Google's APIs, of job
        boards, or of contacts found via cold email) or if this project is discontinued. This
        is a small, actively-developed project — features and availability can change.
      </p>

      <h2>Changes</h2>
      <p>Updated in place if anything material changes, with the date above kept current.</p>

      <h2>Contact</h2>
      <p>Saaz Neupane — <a href="mailto:saazneu789@gmail.com">saazneu789@gmail.com</a></p>
    </div>
  );
}
