"use client";
// Polls the hunt page while it is running. No fake progress: the server
// re-renders real hunt_steps each refresh.
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function Refresh({ active }: { active: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(t);
  }, [active, router]);
  return null;
}
