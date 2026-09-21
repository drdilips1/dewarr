import { useState, type ReactNode } from "react";
import { GripVertical } from "lucide-react";

/** Native drag plus keyboard ordering; the same handle works with touch pointers. */
export default function Sortable({
  values,
  onChange,
  render,
  label,
  horizontal = false,
  itemLabel = (value: string) => value,
  valid = () => true,
  disabled = false,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  render: (value: string) => ReactNode;
  label: string;
  horizontal?: boolean;
  itemLabel?: (value: string) => string;
  disabled?: boolean;
  valid?: (values: string[]) => boolean;
}) {
  const [dragged, setDragged] = useState<string | null>(null);
  function move(from: string, to: string) {
    if (
      disabled ||
      from === to ||
      !values.includes(from) ||
      !values.includes(to)
    )
      return;
    const next = [...values];
    next.splice(next.indexOf(from), 1);
    next.splice(values.indexOf(to), 0, from);
    if (valid(next)) onChange(next);
  }
  return (
    <ol
      className={`sortable ${horizontal ? "sortable-horizontal" : ""}`}
      aria-label={label}
    >
      {values.map((value, index) => (
        <li
          key={value}
          data-sort-value={value}
          className={dragged === value ? "is-dragging" : ""}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            if (dragged) move(dragged, value);
            setDragged(null);
          }}
        >
          <button
            type="button"
            className="drag-handle"
            disabled={disabled}
            draggable={!disabled}
            aria-label={`Reorder ${itemLabel(value)} in ${label}`}
            title="Drag to reorder. Use arrow keys when focused."
            onDragStart={(event) => {
              setDragged(value);
              event.dataTransfer.setData("text/plain", value);
              event.dataTransfer.effectAllowed = "move";
            }}
            onDragEnd={() => setDragged(null)}
            onPointerDown={(event) => {
              if (event.pointerType !== "mouse") {
                event.currentTarget.setPointerCapture(event.pointerId);
                setDragged(value);
              }
            }}
            onPointerCancel={(event) => {
              // Native mouse drag cancels the pointer stream before drop.
              if (event.pointerType !== "mouse") setDragged(null);
            }}
            onPointerUp={(event) => {
              if (event.pointerType === "mouse") return;
              const target = document
                .elementFromPoint(event.clientX, event.clientY)
                ?.closest<HTMLElement>("[data-sort-value]");
              if (
                target?.parentElement === event.currentTarget.closest("ol") &&
                target.dataset.sortValue
              )
                move(value, target.dataset.sortValue);
              setDragged(null);
            }}
            onKeyDown={(event) => {
              const step = ["ArrowUp", "ArrowLeft"].includes(event.key)
                ? -1
                : ["ArrowDown", "ArrowRight"].includes(event.key)
                  ? 1
                  : 0;
              if (!step) return;
              event.preventDefault();
              if (values[index + step]) move(value, values[index + step]);
            }}
          >
            <GripVertical size={15} />
          </button>
          {render(value)}
        </li>
      ))}
    </ol>
  );
}
