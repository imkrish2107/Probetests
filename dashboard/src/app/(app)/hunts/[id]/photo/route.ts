import { sessionToken } from "@/lib/api";

// Streams the hunt photo/plan with the server session (no token in HTML).
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const { BACKEND_URL, BACKEND_API_KEY } = process.env;
  const res = await fetch(`${BACKEND_URL}/api/hunts/${id}/photo`, {
    headers: {
      "X-API-Key": BACKEND_API_KEY ?? "",
      Authorization: `Bearer ${await sessionToken()}`,
    },
    cache: "no-store",
  });
  if (!res.ok) return new Response("not found", { status: 404 });
  const buf = Buffer.from(await res.arrayBuffer());
  const media = buf.subarray(0, 4).toString() === "%PDF" ? "application/pdf" : "image/jpeg";
  return new Response(buf, {
    headers: { "Content-Type": media, "Content-Disposition": "inline" },
  });
}
