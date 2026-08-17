import { useState } from "react";

// Shared show/hide toggle for password inputs (Login + Signup). Plain
// button, not <label> wrapping -- has to sit visually inside the input box,
// and the app's global label:not(...) selector (app.css) styles every
// <label> as an eyebrow-style field label, wrong for a small icon button.
export default function PasswordField({ label, value, onChange, ...inputProps }) {
  const [visible, setVisible] = useState(false);
  return (
    <label>
      {label}
      <div className="password-field">
        <input
          type={visible ? "text" : "password"}
          value={value}
          onChange={onChange}
          {...inputProps}
        />
        <button
          type="button"
          className="password-toggle"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          tabIndex={-1}
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
    </label>
  );
}
