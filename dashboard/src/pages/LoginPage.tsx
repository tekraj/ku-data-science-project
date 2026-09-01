import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiRequest } from "../lib/api";
import { FullScreenState } from "../components/FullScreenState";

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    apiRequest("/auth/me")
      .then(() => {
        if (active) navigate("/", { replace: true });
      })
      .catch(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, [navigate]);

  async function onSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await apiRequest("/auth/signin", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      navigate("/", { replace: true });
    } catch {
      setError("Invalid email or password.");
    } finally {
      setLoading(false);
    }
  }

  if (checking) {
    return <FullScreenState label="Checking session..." />;
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-4">
      <div className="absolute -left-24 -top-24 h-64 w-64 rounded-full bg-cyan-400/30 blur-3xl" />
      <div className="absolute -bottom-24 -right-24 h-72 w-72 rounded-full bg-blue-500/30 blur-3xl" />

      <form onSubmit={onSubmit} className="panel relative z-10 w-full max-w-md p-7 md:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Secure Login</p>
        <h1 className="mt-2 font-display text-3xl font-bold text-slate-100">Market Command Portal</h1>
        <p className="mt-2 text-sm text-slate-300">Access the protected NEPSE analytics dashboard and run telemetry charts.</p>

        <div className="mt-5 space-y-4">
          <div>
            <label className="mb-1 block text-sm text-slate-300">Email</label>
            <input
              className="field"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-slate-300">Password</label>
            <input
              className="field"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
        </div>

        {error && <div className="mt-4 rounded-xl border border-rose-500/40 bg-rose-950/50 px-3 py-2 text-sm text-rose-200">{error}</div>}

        <button type="submit" disabled={loading} className="btn-primary mt-5 w-full">
          {loading ? "Signing In..." : "Sign In"}
        </button>
      </form>
    </main>
  );
}
