import { useState } from "react";
import { Routes, Route, Link, useLocation } from "react-router-dom";
import Logo from "./components/Logo.jsx";
import ToastHost from "./components/ToastHost.jsx";
import Home from "./pages/Home.jsx";
import Guide from "./pages/Guide.jsx";
import Dashboard from "./dashboard/Dashboard.jsx";
import Swipe from "./pages/Swipe.jsx";
import ColdEmail from "./pages/ColdEmail.jsx";
import WizardLayout from "./wizard/WizardLayout.jsx";
import Start from "./wizard/steps/Start.jsx";
import About from "./wizard/steps/About.jsx";
import Lanes from "./wizard/steps/Lanes.jsx";
import Resume from "./wizard/steps/Resume.jsx";
import Keys from "./wizard/steps/Keys.jsx";
import Google from "./wizard/steps/Google.jsx";
import Review from "./wizard/steps/Review.jsx";
import Push from "./wizard/steps/Push.jsx";
import Done from "./wizard/steps/Done.jsx";
import { api } from "./api.js";

function ExitButton() {
  const [closed, setClosed] = useState(false);

  async function exit() {
    if (!window.confirm("Stop the Job Pipeline app? You'll need to reopen it from the desktop shortcut.")) return;
    try {
      await api.shutdown();
    } catch {
      // the process may drop the connection before the response finishes
      // sending -- treat that as success too, it's the expected shutdown path
    }
    setClosed(true);
  }

  if (closed) {
    return (
      <div className="topbar-closed-overlay">
        <p>Job Pipeline has stopped. You can close this tab.</p>
      </div>
    );
  }

  return <button type="button" className="topbar-link topbar-exit" onClick={exit}>Exit</button>;
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
          <ExitButton />
        </div>
      </header>
      <main className={`container${isDashboard ? " wide" : ""}`}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/guide" element={<Guide />} />
          <Route path="/setup/start" element={<Start />} />
          <Route path="/setup/:user" element={<WizardLayout />}>
            <Route path="about" element={<About />} />
            <Route path="lanes" element={<Lanes />} />
            <Route path="resume" element={<Resume />} />
            <Route path="keys" element={<Keys />} />
            <Route path="google" element={<Google />} />
            <Route path="review" element={<Review />} />
            <Route path="push" element={<Push />} />
            <Route path="done" element={<Done />} />
          </Route>
          <Route path="/dashboard/:user" element={<Dashboard />} />
          <Route path="/swipe/:user" element={<Swipe />} />
          <Route path="/cold-email/:user" element={<ColdEmail />} />
        </Routes>
      </main>
    </>
  );
}
