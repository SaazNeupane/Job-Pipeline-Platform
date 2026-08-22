import { useEffect, useState } from "react";
import { Routes, Route, Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api.js";
import Logo from "./components/Logo.jsx";
import { MenuIcon, CloseIcon } from "./components/icons.jsx";
import ToastHost from "./components/ToastHost.jsx";
import { showToast } from "./toast.js";
import Home from "./pages/Home.jsx";
import Login from "./pages/Login.jsx";
import Signup from "./pages/Signup.jsx";
import ForgotPassword from "./pages/ForgotPassword.jsx";
import ResetPassword from "./pages/ResetPassword.jsx";
import Privacy from "./pages/Privacy.jsx";
import Terms from "./pages/Terms.jsx";
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
import Admin from "./pages/Admin.jsx";
import { useAuth } from "./auth/AuthContext.jsx";
import ProtectedRoute from "./auth/ProtectedRoute.jsx";
import AdminRoute from "./auth/AdminRoute.jsx";

function NavLink({ to, children, onNavigate }) {
  const { pathname } = useLocation();
  const active = pathname === to || pathname.startsWith(`${to}/`);
  return (
    <Link to={to} className={`topbar-link${active ? " topbar-link-active" : ""}`} onClick={onNavigate}>
      {children}
    </Link>
  );
}

function AccountLink({ onNavigate }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user) {
    return <NavLink to="/login" onNavigate={onNavigate}>Log in</NavLink>;
  }
  return (
    <>
      <NavLink to="/dashboard" onNavigate={onNavigate}>Dashboard</NavLink>
      <NavLink to="/swipe" onNavigate={onNavigate}>Swipe</NavLink>
      <NavLink to="/cold-email" onNavigate={onNavigate}>Cold email</NavLink>
      {user.is_admin && <NavLink to="/admin" onNavigate={onNavigate}>Admin</NavLink>}
      <button
        type="button" className="topbar-link topbar-exit"
        onClick={() => { onNavigate?.(); logout(); navigate("/"); }}
      >
        Log out
      </button>
    </>
  );
}

function VerifyEmailBanner() {
  const { user } = useAuth();
  const [sent, setSent] = useState(false);

  if (!user || user.email_verified) return null;

  async function resend() {
    try {
      await api.resendVerification();
      setSent(true);
    } catch {
      // api.js's handle() already toasted the reason
    }
  }

  return (
    <div className="banner info verify-banner">
      <p>
        Verify your email to keep your account secure. {sent ? "Sent, check your inbox." : (
          <button type="button" className="ghost" onClick={resend}>Resend verification email</button>
        )}
      </p>
    </div>
  );
}

export default function App() {
  const { user } = useAuth();
  const location = useLocation();
  const pathname = location.pathname;
  const isDashboard = pathname.startsWith("/dashboard") || pathname.startsWith("/swipe") || pathname.startsWith("/cold-email") || pathname.startsWith("/admin");
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const verify = params.get("verify");
    if (!verify) return;
    if (verify === "success") showToast("Email verified.", "pine");
    else if (verify === "expired") showToast("That verification link expired or was already used.");
    params.delete("verify");
    const rest = params.toString();
    window.history.replaceState({}, "", location.pathname + (rest ? `?${rest}` : ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search]);

  return (
    <>
      <ToastHost />
      <header className="topbar">
        <Link to="/" className="brand">
          <Logo />
          Crond
          {user?.plan === "paid" && <span className="badge pine topbar-plan-badge">Pro</span>}
        </Link>
        <button
          type="button"
          className="topbar-menu-toggle"
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? <CloseIcon /> : <MenuIcon />}
        </button>
        <div className={`topbar-right${menuOpen ? " topbar-right-open" : ""}`}>
          <AccountLink onNavigate={() => setMenuOpen(false)} />
        </div>
      </header>
      <main className={`container${isDashboard ? " wide" : ""}`}>
        <VerifyEmailBanner />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/guide" element={<Navigate to="/#guide" replace />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/terms" element={<Terms />} />
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
          <Route path="/admin" element={<AdminRoute><Admin /></AdminRoute>} />
        </Routes>
      </main>
      <footer className="site-footer">
        <Link to="/" className="footer-brand">
          <Logo size={20} />
          <span>Crond</span>
          <span className="footer-tagline">Your job search, running itself.</span>
        </Link>
        <div className="footer-links">
          <Link to="/terms" className="topbar-link">Terms</Link>
          <Link to="/privacy" className="topbar-link">Privacy</Link>
        </div>
      </footer>
    </>
  );
}
