import { BookOpen } from "lucide-react";

const hardcoverLogo = new URL("../assets/hardcover-logo.png", import.meta.url)
  .href;

export default function BookSourceIcon({ source }: { source: string }) {
  return (
    <span className="book-source-icon" title={`View on ${source}`}>
      <span className="sr-only">View on {source}</span>
      {source === "Goodreads" ? (
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
          <text
            x="12"
            y="17"
            textAnchor="middle"
            fill="currentColor"
            fontFamily="Georgia, serif"
            fontSize="23"
          >
            g
          </text>
        </svg>
      ) : source === "Hardcover" ? (
        <img
          src={hardcoverLogo}
          alt=""
          width="17"
          height="17"
          style={{ objectFit: "contain" }}
          aria-hidden="true"
        />
      ) : (
        <BookOpen size={22} aria-hidden="true" />
      )}
    </span>
  );
}
