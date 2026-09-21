import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
export default function BookDialog({
  title,
  close,
  children,
  className = "",
}: {
  className?: string;
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = ref.current!;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      element.close();
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`book-dialog ${className}`}
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          const rect = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < rect.left ||
            event.clientX > rect.right ||
            event.clientY < rect.top ||
            event.clientY > rect.bottom
          )
            close();
        }
      }}
    >
      <header className="book-dialog-heading">
        <span>{title}</span>
        <button
          type="button"
          aria-label={`Close ${title.toLowerCase()}`}
          onClick={close}
        >
          <X size={18} />
        </button>
      </header>
      <div className="book-dialog-content">{children}</div>
    </dialog>
  );
}
