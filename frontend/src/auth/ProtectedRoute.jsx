import { Navigate } from "react-router-dom";
import Loading from "../components/Loading.jsx";
import { useAuth } from "./AuthContext.jsx";

export default function ProtectedRoute({ children }) {
  const { user, ready } = useAuth();
  if (!ready) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}
