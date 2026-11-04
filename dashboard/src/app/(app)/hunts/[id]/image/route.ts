import { sessionToken } from "@/lib/api";

// Streams a concept image (?n=1..5) with the server session.
export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const n = new URL(req.url).searchParams.get("n") ?? "1";
  const { BACKEND_URL, BACKEND_API_KEY } = process.env;
  const res = await fetch(`${BACKEND_URL}/api/hunts/${id}/image?n=${n}`, {
    headers: {
      "X-API-Key": BACKEND_API_KEY ?? "",
      Authorization: `Bearer ${await sessionToken()}`,
    },
    cache: "no-store",
  });
  if (!res.ok) return new Response("not found", { status: 404 });
  return new Response(res.body, {
    headers: { "Content-Type": "image/jpeg", "Content-Disposition": "inline" },
  });
}
