"use client";
import { useEffect, useRef, useState } from "react";
import { createHunt } from "@/lib/actions";
import Submit from "@/lib/submit";

// Large drop area; clicking anywhere on it opens the file picker.
export default function DropForm({ flow }: { flow: "shopping" | "construction" }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const construction = flow === "construction";

  useEffect(() => {
    if (!file || !file.type.startsWith("image/")) {
      setPreview("");
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  return (
    <form action={createHunt}>
      <input type="hidden" name="flow" value={flow} />
      <label
        className={`drop ${over ? "over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const f = e.dataTransfer.files;
          if (f.length && input.current) {
            input.current.files = f;
            setFile(f[0]);
          }
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {preview && <img src={preview} alt="Selected file preview" />}
        <strong>
          {file
            ? file.name
            : over
              ? "Drop it here"
              : construction
                ? "Drop your floor plan"
                : "Drop a photo of what you want"}
        </strong>
        <span>
          {construction ? "Photo or PDF" : "JPEG, PNG or WebP"}, up to 8 MB ·{" "}
          <span className="pick">{file ? "choose another" : "or choose a file"}</span>
        </span>
        <input
          type="file"
          name="file"
          accept={construction ? "image/jpeg,image/png,image/webp,.pdf,application/pdf" : "image/jpeg,image/png,image/webp"}
          required
          ref={input}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>
      {!construction && (
        <div className="fields">
          <label>
            Size <span className="norm">optional</span>
            <input className="input" name="size" maxLength={10} placeholder="M" />
          </label>
          <label>
            Budget ₹ <span className="norm">optional</span>
            <input className="input" name="budget" type="number" min={0} placeholder="1500" />
          </label>
        </div>
      )}
      {construction && (
        <>
          <div className="fields">
            <label>
              City
              <input className="input" name="city" maxLength={80} required placeholder="Kochi" />
            </label>
            <label>
              Floors
              <input className="input" name="floors" type="number" min={1} defaultValue={1} />
            </label>
            <label>
              Floor height, ft
              <input className="input" name="floor_height_ft" type="number" min={8} defaultValue={10} />
            </label>
          </div>
          <div className="fields">
            <label>
              Finish
              <select className="input" name="finish" defaultValue="standard">
                <option value="basic">Basic</option>
                <option value="standard">Standard</option>
                <option value="premium">Premium</option>
              </select>
            </label>
            <label>
              Built-up area, sq ft <span className="norm">optional</span>
              <input className="input" name="builtup_sqft" type="number" min={0} placeholder="From rooms × 1.2" />
            </label>
          </div>
        </>
      )}
      <Submit pending={construction ? "Uploading the plan…" : "Uploading the photo…"}>
        {construction ? "Read the plan" : "Send the agents"}
      </Submit>
    </form>
  );
}
