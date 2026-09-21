import { Navigate, useParams, useSearchParams } from "react-router-dom";

// Preserve old links without exposing the retired list-management screen.
export default function Lists({ canEdit }: { canEdit: boolean }) {
  const { id } = useParams();
  const [params] = useSearchParams();
  return (
    <Navigate
      replace
      to={
        canEdit && id && params.has("settings")
          ? `/settings?list=${encodeURIComponent(id)}#reading`
          : "/discover?view=yours"
      }
    />
  );
}
