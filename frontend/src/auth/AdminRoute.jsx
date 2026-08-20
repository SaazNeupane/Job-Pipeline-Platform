import { Navigate } from "react-router-dom";
import Loading from "../components/Loading.jsx";
import { useAuth } from "./AuthContext.jsx";

// Same shape as ProtectedRoute, plus the is_admin check /api/me returns. A non-admin
// logged-in user is bounced to the dashboard rather than login, since they're not
// unauthenticated, just not allowed here.
export default function AdminRoute({ children }) {
  const { user, ready } = useAuth();
  if (!ready) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.is_admin) return <Navigate to="/dashboard" replace />;
  return children;
}
