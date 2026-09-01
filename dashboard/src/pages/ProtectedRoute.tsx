import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { apiRequest } from "../lib/api";
import { FullScreenState } from "../components/FullScreenState";

export function ProtectedRoute() {
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);
  const location = useLocation();

  useEffect(() => {
    let active = true;

    apiRequest("/auth/me")
      .then(() => {
        if (!active) return;
        setAllowed(true);
      })
      .catch(() => {
        if (!active) return;
        setAllowed(false);
      })
      .finally(() => {
        if (active) setChecking(false);
      });

    return () => {
      active = false;
    };
  }, []);

  if (checking) return <FullScreenState label="Validating session..." />;
  if (!allowed) return <Navigate to="/login" state={{ from: location.pathname }} replace />;

  return <Outlet />;
}
