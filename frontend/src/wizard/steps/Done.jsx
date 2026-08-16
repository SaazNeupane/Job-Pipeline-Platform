import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";

export default function Done() {
  const { user } = useAuth();
  return (
    <>
      <h1>You're set up{user ? `, ${user.email}` : ""}!</h1>
      <div className="card">
        <p>
          The daily run happens automatically. Once one finds new postings, swipe through them from your{" "}
          <Link to="/dashboard">dashboard</Link> to pick which ones to apply to.
        </p>
        <p className="hint" style={{ marginBottom: 0 }}>Each lane queues a capped number of new postings a day, so the swipe queue never floods. You're still the one who applies.</p>
      </div>
    </>
  );
}
