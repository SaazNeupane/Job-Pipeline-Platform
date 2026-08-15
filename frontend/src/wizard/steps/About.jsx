import { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { api } from "../../api.js";

export default function About() {
  const { draft, refreshDraft } = useOutletContext();
  const a = draft.applicant || {};
  const [form, setForm] = useState({
    first_name: a.first_name || "", last_name: a.last_name || "", country: a.country || "Canada",
    address: a.address || "", latitude: a.latitude ?? "", longitude: a.longitude ?? "",
  });
  const [manualCoords, setManualCoords] = useState(Boolean(a.latitude) && !a.address);
  const [geocoding, setGeocoding] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setError("");

    const applicant = { ...form };
    if (!manualCoords && form.address.trim()) {
      setGeocoding(true);
      try {
        const { latitude, longitude } = await api.geocode(form.address.trim());
        applicant.latitude = latitude;
        applicant.longitude = longitude;
      } catch (err) {
        setGeocoding(false);
        setError(err.message);
        setManualCoords(true);
        return;
      }
      setGeocoding(false);
    }

    if (applicant.latitude !== "") applicant.latitude = parseFloat(applicant.latitude); else delete applicant.latitude;
    if (applicant.longitude !== "") applicant.longitude = parseFloat(applicant.longitude); else delete applicant.longitude;
    try {
      await api.patchDraft({ applicant });
      await refreshDraft();
      navigate("/setup/lanes");
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <>
      <h1>About you</h1>
      <p>Your name, and an address if a lane's commute-radius filter needs coordinates to work.</p>
      {error && <p className="error-banner">{error}</p>}
      <form onSubmit={submit}>
        <fieldset>
          <legend>Your name</legend>
          <div className="grid2">
            <label>First name<input value={form.first_name} onChange={set("first_name")} required /></label>
            <label>Last name<input value={form.last_name} onChange={set("last_name")} required /></label>
          </div>
          <label>Country<input value={form.country} onChange={set("country")} required /></label>
        </fieldset>

        <fieldset>
          <legend>Address (optional, only needed for a commute-radius lane)</legend>
          {!manualCoords ? (
            <>
              <label>Address<input value={form.address} onChange={set("address")} placeholder="e.g. 123 Main St, Toronto, ON" /></label>
              <p className="hint">
                Only needed if you pick a lane with a commute-radius filter. Looked up automatically when you continue —
                nothing to copy or paste.
              </p>
              <button type="button" className="ghost" onClick={() => setManualCoords(true)}>
                Enter coordinates directly instead
              </button>
            </>
          ) : (
            <>
              <div className="grid2">
                <label>Latitude<input value={form.latitude} onChange={set("latitude")} placeholder="e.g. 43.7315" /></label>
                <label>Longitude<input value={form.longitude} onChange={set("longitude")} placeholder="e.g. -79.7624" /></label>
              </div>
              <button type="button" className="ghost" onClick={() => setManualCoords(false)}>
                Use an address instead
              </button>
            </>
          )}
        </fieldset>

        <div className="wizard-actions">
          <button type="submit" className="primary" disabled={geocoding}>{geocoding ? "Looking up address…" : "Continue"}</button>
        </div>
      </form>
    </>
  );
}
