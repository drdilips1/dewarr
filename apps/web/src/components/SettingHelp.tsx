import {
  useEffect,
  useLayoutEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Info } from "lucide-react";

/** Optional help stays available to pointer, keyboard and touch users. */
export default function SettingHelp({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [left, setLeft] = useState(0);
  useLayoutEffect(() => {
    if (!open) return;
    const align = () => {
      const x = root.current?.getBoundingClientRect().left || 0;
      const width = Math.min(280, window.innerWidth * 0.65);
      setLeft(Math.max(8, Math.min(x, window.innerWidth - width - 8)) - x);
    };
    align();
    window.addEventListener("resize", align);
    return () => window.removeEventListener("resize", align);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) {
        setOpen(false);
        setPinned(false);
      }
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  return (
    <span
      ref={root}
      className="setting-help"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => {
        if (!pinned) setOpen(false);
      }}
    >
      <button
        type="button"
        className="help-button"
        aria-label={`About ${label}`}
        aria-expanded={open}
        aria-controls={id}
        aria-describedby={open ? id : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          if (!pinned) setOpen(false);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setOpen(false);
            setPinned(false);
          }
        }}
        onClick={() => {
          setPinned(!pinned);
          setOpen(!pinned);
        }}
      >
        <Info size={15} />
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="setting-help-content"
          style={{ left }}
        >
          {children}
        </span>
      )}
    </span>
  );
}
