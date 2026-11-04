import { sessionToken } from "@/lib/api";

// Streams the BOQ CSV (engineer warning is the first row) with the session.
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const { BACKEND_URL, BACKEND_API_KEY } = process.env;
  const res = await fetch(`${BACKEND_URL}/api/hunts/${id}/boq.csv`, {
    headers: {
      "X-API-Key": BACKEND_API_KEY ?? "",
      Authorization: `Bearer ${await sessionToken()}`,
    },
    cache: "no-store",
  });
  if (!res.ok) return new Response("not found", { status: 404 });
  return new Response(res.body, {
    headers: { "Content-Type": "text/csv", "Content-Disposition": `attachment; filename="boq-${id}.csv"` },
  });
}
