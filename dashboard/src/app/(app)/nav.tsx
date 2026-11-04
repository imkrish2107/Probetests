"use client";
import { usePathname } from "next/navigation";

const GROUPS = [
  {
    label: "Sourcing",
    links: [
      { href: "/hunts", text: "Hunts" },
      { href: "/orders", text: "Orders" },
      { href: "/sellers", text: "Vendors" },
    ],
  },
  {
    label: "Voice agent",
    links: [
      { href: "/", text: "Calls" },
      { href: "/contacts", text: "Contacts" },
      { href: "/tasks", text: "Tasks" },
    ],
  },
  { label: "Account", links: [{ href: "/setup", text: "Setup" }] },
];

export default function Nav() {
  const path = usePathname();
  const active = (href: string) =>
    href === "/" ? path === "/" || path.startsWith("/calls") : path.startsWith(href);
  return (
    <nav aria-label="Main">
      {GROUPS.map((g) => (
        <div className="nav-group" key={g.label}>
          <span>{g.label}</span>
          {g.links.map((l) => (
            <a key={l.href} href={l.href} aria-current={active(l.href) ? "page" : undefined}>
              {l.text}
            </a>
          ))}
        </div>
      ))}
    </nav>
  );
}
