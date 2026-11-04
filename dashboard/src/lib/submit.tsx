"use client";
import { useFormStatus } from "react-dom";

// Submit button with a real pending state: slow agent work shows it is running.
export default function Submit({
  children,
  pending,
  className = "btn",
  disabled,
}: {
  children: React.ReactNode;
  pending: string;
  className?: string;
  disabled?: boolean;
}) {
  const s = useFormStatus();
  return (
    <button className={className} type="submit" disabled={disabled || s.pending} aria-busy={s.pending}>
      {s.pending ? pending : children}
    </button>
  );
}
