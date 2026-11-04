import { redirect } from "next/navigation";
import { api, sessionToken } from "@/lib/api";

// Redirects to the wa.me invite for a listing (no number is ever shown
// to a non-opted-in vendor by us; the user sends it from their WhatsApp).
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string; listing: string }> },
) {
  const { id, listing } = await params;
  try {
    const data = await api(
      `/api/listings/${listing}/invite`,
      undefined,
      await sessionToken(),
    );
    if (data?.invite_from_whatsapp) redirect(data.invite_from_whatsapp);
  } catch {
    // fall through to the hunt page
  }
  redirect(`/hunts/${id}`);
}
