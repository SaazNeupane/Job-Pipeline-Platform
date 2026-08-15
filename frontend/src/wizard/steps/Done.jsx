import { Link, useOutletContext } from "react-router-dom";

export default function Done() {
  const { user } = useOutletContext();
  return (
    <>
      <h1>You're set up, {user}!</h1>
      <div className="card">
        <p>The daily run happens automatically every morning. To trigger one manually right now:</p>
        <pre className="code-block">gh workflow run daily.yml --repo &lt;owner&gt;/&lt;repo&gt;</pre>
        <p style={{ marginBottom: 0 }}>
          Once a run finds new postings, swipe through them from your <Link to={`/dashboard/${user}`}>dashboard</Link> to pick which ones to apply to.
        </p>
      </div>
    </>
  );
}
