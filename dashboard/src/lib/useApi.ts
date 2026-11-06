import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiRequest } from "./api";

// GET `path` whenever it changes (null = don't fetch), optionally re-polling
// every refreshMs. A 401 sends the user to /login like the other pages do.
// Keeps the previous data while a new request is in flight so charts don't
// blank out on every refresh.
export function useApi(path: string | null, refreshMs = 0) {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState("");

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return undefined;
    }
    let active = true;

    async function load() {
      setLoading(true);
      try {
        const result = await apiRequest(path);
        if (!active) return;
        setData(result);
        setError("");
      } catch (e) {
        if (!active) return;
        if (e.status === 401) {
          navigate("/login", { replace: true });
          return;
        }
        setError(`Unable to load ${path.split("?")[0]} (${e.status || "network error"}).`);
      } finally {
        if (active) setLoading(false);
      }
    }

    load();
    const id = refreshMs ? window.setInterval(load, refreshMs) : null;
    return () => {
      active = false;
      if (id) window.clearInterval(id);
    };
  }, [path, refreshMs, navigate]);

  return { data, loading, error };
}

export function useLogout() {
  const navigate = useNavigate();
  return async function onLogout() {
    try {
      await apiRequest("/auth/logout", { method: "POST" });
    } finally {
      navigate("/login", { replace: true });
    }
  };
}
