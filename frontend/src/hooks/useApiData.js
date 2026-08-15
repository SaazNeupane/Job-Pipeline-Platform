import { useCallback, useEffect, useState } from "react";

// Shared `fetchFn().then(setData).catch(e => setError(e.message))` shape --
// repeated across 7 components before this was extracted. `fetchFn` gets a
// stable identity via `deps` (same rules as useCallback/useEffect deps), and
// `reload` is exposed so callers that re-fetch after a mutation (Dashboard's
// promote/dismiss, WizardLayout's refreshDraft passed through Outlet
// context) don't need their own extra effect.
export function useApiData(fetchFn, deps) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [errorCode, setErrorCode] = useState("");

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reload = useCallback(() => fetchFn().then((d) => { setError(""); setErrorCode(""); setData(d); }).catch((e) => { setError(e.message); setErrorCode(e.code || ""); }), deps);

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, error, errorCode, setData, setError, reload };
}
