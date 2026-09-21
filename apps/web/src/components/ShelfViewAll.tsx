import { ArrowRight } from "lucide-react";
import { useDisplayPreferences } from "../displayPreferences";
import { Link } from "react-router-dom";

export default function ShelfViewAll({ to }: { to: string }) {
  const display = useDisplayPreferences();
  return (
    <li>
      <Link className="book-card shelf-view-all" to={to}>
        <div className={`book-cover cover-${display.defaultShape}`}>
          <ArrowRight size={28} aria-hidden="true" />
          <span>View all</span>
        </div>
        <h3>Explore the full list</h3>
      </Link>
    </li>
  );
}
