"use client";
import { useRef, useState } from "react";
import { createHunt } from "@/lib/actions";

// Big drop area with drag and drop; the file picker still works.
export default function DropForm({ flow }: { flow: "shopping" | "construction" }) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [name, setName] = useState("");
  const construction = flow === "construction";
  return (
    <form
      action={createHunt}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer.files;
        if (f.length && input.current) {
          input.current.files = f;
          setName(f[0].name);
        }
      }}
      style={{
        border: "3px dashed",
        borderColor: drag ? "green" : "grey",
        padding: "2em",
        textAlign: "center",
      }}
    >
      <input type="hidden" name="flow" value={flow} />
      <p>{drag ? "Drop it here" : "Drag a file here, or pick one below"}</p>
      <input
        className="input"
        type="file"
        name="file"
        accept="image/*,.pdf"
        required
        ref={input}
        onChange={(e) => setName(e.target.files?.[0]?.name ?? "")}
      />
      {name && <p className="muted">{name}</p>}
      {!construction && (
        <>
          <label>
            Size <span className="norm">(optional)</span>
            <input className="input" name="size" maxLength={10} />
          </label>
          <label>
            Budget ₹ <span className="norm">(optional)</span>
            <input className="input" name="budget" type="number" min={0} />
          </label>
        </>
      )}
      {construction && (
        <>
          <label>
            City
            <input className="input" name="city" maxLength={80} required />
          </label>
          <label>
            Floors
            <input className="input" name="floors" type="number" min={1} defaultValue={1} />
          </label>
          <label>
            Floor height (ft)
            <input className="input" name="floor_height_ft" type="number" min={8} defaultValue={10} />
          </label>
          <label>
            Finish
            <select className="input" name="finish" defaultValue="standard">
              <option value="basic">Basic</option>
              <option value="standard">Standard</option>
              <option value="premium">Premium</option>
            </select>
          </label>
          <label>
            Built-up sqft <span className="norm">(blank estimates from rooms × 1.2)</span>
            <input className="input" name="builtup_sqft" type="number" min={0} />
          </label>
        </>
      )}
      <button className="btn" type="submit">
        {construction ? "Check the plan" : "Start the hunt"}
      </button>
    </form>
  );
}
