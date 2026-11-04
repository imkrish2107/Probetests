"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Props = { productName: string };

export default function TryOn({ productName }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [consent, setConsent] = useState(false);
  const [shot, setShot] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "working" | "error">("idle");
  const [msg, setMsg] = useState("");

  useEffect(() => () => stream?.getTracks().forEach((t) => t.stop()), [stream]);

  async function start() {
    setMsg("");
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 768 } },
        audio: false,
      });
      setStream(s);
      if (video.current) {
        video.current.srcObject = s;
        await video.current.play();
      }
    } catch {
      setState("error");
      setMsg("Camera blocked. Allow camera access, or use a browser over HTTPS.");
    }
  }

  function stop() {
    stream?.getTracks().forEach((t) => t.stop());
    setStream(null);
  }

  async function capture() {
    const v = video.current;
    if (!v) return;
    const c = document.createElement("canvas");
    const scale = Math.min(1, 768 / v.videoWidth);
    c.width = Math.round(v.videoWidth * scale);
    c.height = Math.round(v.videoHeight * scale);
    c.getContext("2d")!.drawImage(v, 0, 0, c.width, c.height);
    const blob = await new Promise<Blob | null>((res) => c.toBlob(res, "image/jpeg", 0.85));
    if (!blob) return;
    setShot(URL.createObjectURL(blob));
    setState("working");
    setMsg("Stitching your preview…");
    try {
      const { id } = await api.tryon(blob, productName);
      setPreview(api.tryonUrl(id));
      setState("idle");
      setMsg("");
    } catch (e) {
      setState("error");
      setMsg(e instanceof Error ? e.message : "Preview failed.");
    }
  }

  return (
    <div className="border-t rule pt-6 mt-8">
      <h2 className="font-display text-2xl">Fitting room</h2>
      <p className="text-sm opacity-80 mt-1">
        Live preview on yourself. Your photo is used only for this preview and deleted
        within an hour — never stored, never shared.
      </p>
      <label className="flex items-start gap-2 mt-3 text-sm">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          className="mt-1"
        />
        I consent to one AI preview of myself wearing this garment.
      </label>
      <div className="flex gap-3 mt-3 flex-wrap">
        {!stream ? (
          <button className="btn" onClick={start} disabled={!consent}>
            Start camera
          </button>
        ) : (
          <>
            <button className="btn btn-solid" onClick={capture}>
              Capture & preview
            </button>
            <button className="btn" onClick={stop}>
              Stop camera
            </button>
          </>
        )}
      </div>
      {state === "error" && msg && <p className="mt-2 text-sm text-oxblood">{msg}</p>}
      {state === "working" && <p className="mt-2 text-sm">{msg}</p>}
      <div className="grid grid-cols-2 gap-4 mt-4">
        <div>
          {stream && (
            <video ref={video} playsInline muted className="w-full border rule aspect-[3/4] object-cover" />
          )}
          {shot && !stream && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={shot} alt="Your captured photo" className="w-full border rule" />
          )}
          <p className="text-xs uppercase tracking-widest mt-1 opacity-70">You</p>
        </div>
        <div>
          {preview && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview} alt="AI try-on preview" className="w-full border rule fade-in" />
          )}
          <p className="text-xs uppercase tracking-widest mt-1 opacity-70">Preview. Fit and colour may vary.</p>
        </div>
      </div>
    </div>
  );
}
