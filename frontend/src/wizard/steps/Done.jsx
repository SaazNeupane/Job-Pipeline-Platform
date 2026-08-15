import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";

export default function Done() {
  const { user } = useAuth();
  return (
    <>
      <h1>You're set up{user ? `, ${user.email}` : ""}!</h1>
      <div className="card">
        <p style={{ marginBottom: 0 }}>
          The daily run happens automatically. Once one finds new postings, swipe through them from your{" "}
          <Link to="/dashboard">dashboard</Link> to pick which ones to apply to.
        </p>
      </div>
    </>
  );
}
