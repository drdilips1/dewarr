import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type PointerEvent,
} from "react";
import { GripVertical } from "lucide-react";

/** Pointer capture keeps the lifted shelf attached to the cursor across live reorders. */
export default function DiscoverShelfOrder({
  values,
  onChange,
  render,
  itemLabel,
  disabled,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  render: (id: string) => ReactNode;
  itemLabel: (id: string) => string;
  disabled: boolean;
}) {
  const list = useRef<HTMLOListElement>(null);
  const gesture = useRef<{
    id: string;
    y: number;
    startY: number;
    offset: number;
    original: string[];
    active: boolean;
  } | null>(null);
  const current = useRef({ values, onChange });
  current.current = { values, onChange };
  const [dragged, setDragged] = useState<string | null>(null);

  function position() {
    const drag = gesture.current;
    if (!drag?.active || !list.current) return;
    const rows = Array.from(list.current.children) as HTMLElement[];
    const row = rows.find((el) => el.dataset.sortValue === drag.id);
    if (!row) return;
    row.style.transform = "";
    row.style.transform = `translateY(${drag.y - drag.offset - row.getBoundingClientRect().top}px)`;
    const { values: order, onChange: change } = current.current;
    const from = order.indexOf(drag.id);
    let to = from;
    rows.forEach((el, index) => {
      if (index === from) return;
      const rect = el.getBoundingClientRect();
      const center = rect.top + rect.height / 2;
      if (index > from && drag.y > center) to = Math.max(to, index);
      if (index < from && drag.y < center) to = Math.min(to, index);
    });
    if (to !== from) {
      const next = [...order];
      next.splice(from, 1);
      next.splice(to, 0, drag.id);
      current.current.values = next;
      change(next);
    }
  }
  useLayoutEffect(() => {
    position();
  }, [values, dragged]);
  useEffect(() => {
    if (!dragged) return;
    let frame: number;
    function scroll() {
      const drag = gesture.current;
      const dialog = list.current?.closest("dialog");
      if (drag && dialog) {
        const bounds = dialog.getBoundingClientRect();
        const top = bounds.top + 90,
          bottom = bounds.bottom - 95;
        const delta = drag.y < top ? -10 : drag.y > bottom ? 10 : 0;
        if (delta) {
          dialog.scrollTop += delta;
          position();
        }
      }
      frame = requestAnimationFrame(scroll);
    }
    frame = requestAnimationFrame(scroll);
    return () => cancelAnimationFrame(frame);
  }, [dragged]);

  function finish(cancel = false) {
    const drag = gesture.current;
    gesture.current = null;
    for (const el of Array.from(list.current?.children || []) as HTMLElement[])
      el.style.transform = "";
    setDragged(null);
    if (cancel && drag?.active) current.current.onChange(drag.original);
  }
  function start(event: PointerEvent<HTMLLIElement>, id: string) {
    if (disabled || event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest("input, a, select, textarea, button:not(.drag-handle)"))
      return;
    const rect = event.currentTarget.getBoundingClientRect();
    gesture.current = {
      id,
      y: event.clientY,
      startY: event.clientY,
      offset: event.clientY - rect.top,
      original: [...values],
      active: false,
    };
    list.current!.setPointerCapture(event.pointerId);
    event.preventDefault();
  }
  return (
    <ol
      ref={list}
      className="sortable discover-shelf-order"
      aria-label="Discover shelves"
      onPointerMove={(event) => {
        const drag = gesture.current;
        if (!drag) return;
        drag.y = event.clientY;
        if (!drag.active && Math.abs(drag.y - drag.startY) >= 4) {
          drag.active = true;
          setDragged(drag.id);
        }
        position();
      }}
      onPointerUp={() => finish()}
      onPointerCancel={() => finish(true)}
      onLostPointerCapture={() => {
        if (gesture.current) finish(true);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && gesture.current) {
          event.preventDefault();
          event.stopPropagation();
          finish(true);
        }
      }}
    >
      {values.map((id, index) => (
        <li
          key={id}
          data-sort-value={id}
          className={dragged === id ? "is-dragging" : ""}
          onPointerDown={(event) => start(event, id)}
        >
          <button
            type="button"
            className="drag-handle"
            disabled={disabled}
            aria-label={`Reorder ${itemLabel(id)} in Discover shelves`}
            title="Drag this row, or use the arrow keys."
            onKeyDown={(event) => {
              const step =
                event.key === "ArrowUp"
                  ? -1
                  : event.key === "ArrowDown"
                    ? 1
                    : 0;
              if (!step) return;
              event.preventDefault();
              if (index + step < 0 || index + step >= values.length) return;
              const next = [...values];
              [next[index], next[index + step]] = [
                next[index + step],
                next[index],
              ];
              onChange(next);
            }}
          >
            <GripVertical size={16} />
          </button>
          {render(id)}
        </li>
      ))}
    </ol>
  );
}
