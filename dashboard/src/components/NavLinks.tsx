import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/market", label: "Market" },
  { to: "/orderbook", label: "Order Book" },
  { to: "/brokers", label: "Brokers" },
  { to: "/technicals", label: "Technicals" },
  { to: "/news", label: "News" },
  { to: "/logs", label: "Run Logs" },
];

export function NavLinks() {
  return (
    <>
      {LINKS.map((link) => (
        <NavLink
          key={link.to}
          to={link.to}
          end={link.end}
          className={({ isActive }) => (isActive ? "btn-ghost border-cyan-400/70 text-cyan-200" : "btn-ghost")}
        >
          {link.label}
        </NavLink>
      ))}
    </>
  );
}
