const codes =
  "en es fr de it pt nl da sv no fi is pl cs sk hu ro bg el uk ru tr ar he fa hi bn ta te ur id ms vi th ko ja zh sw af sq am hy az eu be bs ca et fil gl ka gu hr kk km kn ky lo lt lv mk ml mn mr my ne pa si sl sr so uz zu".split(
    " ",
  );
const displayNames = new Intl.DisplayNames(["en"], { type: "language" });
const names = new Map(
  codes.map((code) => {
    const name = displayNames.of(code) || code;
    return [name.toLowerCase(), name];
  }),
);
export function languageName(code?: string | null) {
  if (!code) return "";
  const value = code.trim();
  const named = names.get(value.toLowerCase());
  if (named) return named;
  try {
    return displayNames.of(value.replaceAll("_", "-")) || value;
  } catch {
    return code;
  }
}
export default function LanguageSelect({
  value,
  onChange,
  allowAny = false,
}: {
  value: string;
  onChange: (value: string) => void;
  allowAny?: boolean;
}) {
  const options = [...new Set([...codes, ...(value ? [value] : [])])].sort(
    (a, b) => languageName(a).localeCompare(languageName(b)),
  );
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      required={!allowAny}
    >
      {allowAny && <option value="">Any language</option>}
      {options.map((code) => (
        <option key={code} value={code}>
          {languageName(code)}
        </option>
      ))}
    </select>
  );
}
