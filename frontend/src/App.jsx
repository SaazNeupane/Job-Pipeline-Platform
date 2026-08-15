import { Routes, Route, Link, useLocation, useNavigate } from "react-router-dom";
import Logo from "./components/Logo.jsx";
import ToastHost from "./components/ToastHost.jsx";
import Home from "./pages/Home.jsx";
import Guide from "./pages/Guide.jsx";
import Login from "./pages/Login.jsx";
import Signup from "./pages/Signup.jsx";
import Dashboard from "./dashboard/Dashboard.jsx";
import Swipe from "./pages/Swipe.jsx";
import ColdEmail from "./pages/ColdEmail.jsx";
import WizardLayout from "./wizard/WizardLayout.jsx";
import About from "./wizard/steps/About.jsx";
import Lanes from "./wizard/steps/Lanes.jsx";
import Resume from "./wizard/steps/Resume.jsx";
import Keys from "./wizard/steps/Keys.jsx";
import Google from "./wizard/steps/Google.jsx";
import Review from "./wizard/steps/Review.jsx";
import Done from "./wizard/steps/Done.jsx";
import { useAuth } from "./auth/AuthContext.jsx";
import ProtectedRoute from "./auth/ProtectedRoute.jsx";

function AccountLink() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user) {
    return <Link to="/login" className="topbar-link">Log in</Link>;
  }
  return (
    <button
      type="button" className="topbar-link topbar-exit"
      onClick={() => { logout(); navigate("/"); }}
    >
      Log out
    </button>
  );
}

export default function App() {
  const pathname = useLocation().pathname;
  const isDashboard = pathname.startsWith("/dashboard") || pathname.startsWith("/swipe") || pathname.startsWith("/cold-email");
  return (
    <>
      <ToastHost />
      <header className="topbar">
        <Link to="/" className="brand">
          <Logo />
          Job Pipeline
        </Link>
        <div className="topbar-right">
          <Link to="/guide" className="topbar-link">Guide</Link>
          <AccountLink />
        </div>
      </header>
      <main className={`container${isDashboard ? " wide" : ""}`}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/guide" element={<Guide />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/setup" element={<ProtectedRoute><WizardLayout /></ProtectedRoute>}>
            <Route path="about" element={<About />} />
            <Route path="lanes" element={<Lanes />} />
            <Route path="resume" element={<Resume />} />
            <Route path="keys" element={<Keys />} />
            <Route path="google" element={<Google />} />
            <Route path="review" element={<Review />} />
            <Route path="done" element={<Done />} />
          </Route>
          <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/swipe" element={<ProtectedRoute><Swipe /></ProtectedRoute>} />
          <Route path="/cold-email" element={<ProtectedRoute><ColdEmail /></ProtectedRoute>} />
        </Routes>
      </main>
    </>
  );
}
