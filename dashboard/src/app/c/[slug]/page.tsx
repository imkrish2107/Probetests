import { get } from "@/lib/ui";

// Public "Call us" page. No login; QR code arrives with the qrcode dep.
export default async function CallPage({ params }: { params: { slug: string } }) {
  const { data: biz } = await get(`/api/public/businesses/${params.slug}`);
  if (!biz) {
    return (
      <main>
        <div className="card">
          <p>Unknown business.</p>
        </div>
      </main>
    );
  }
  return (
    <main>
      <div className="card">
        <h1>{biz.name}</h1>
        {biz.call_link ? (
          <p>
            <a className="btn" href={biz.call_link}>
              Call us on WhatsApp
            </a>
          </p>
        ) : (
          <p>Calling isn&apos;t set up yet.</p>
        )}
      </div>
    </main>
  );
}
