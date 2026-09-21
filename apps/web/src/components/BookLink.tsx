import { Link, type LinkProps } from "react-router-dom";

// Keep download buttons outside the navigation link while preserving a full-card target.
export default function BookLink({ children, className, ...props }: LinkProps) {
  return (
    <div className={`book-link ${className || ""}`}>
      <Link {...props} className="book-link-target" />
      {children}
    </div>
  );
}
