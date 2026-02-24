interface SearchBoxProps {
  /** Current search query string. */
  query: string;
  /** Called on every keystroke with the updated query. */
  onQueryChange: (query: string) => void;
}

/**
 * SearchBox renders a controlled text input that triggers instant client-side
 * filtering of the drink catalog on each keystroke.
 *
 * The input is accessible via a visually-hidden label and supports the
 * browser's native search clear button via `type="search"`.
 */
export function SearchBox({ query, onQueryChange }: SearchBoxProps) {
  return (
    <div className="relative">
      <label htmlFor="drink-search" className="sr-only">
        Search drinks
      </label>
      <input
        id="drink-search"
        type="search"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        placeholder="Search drinks…"
        aria-label="Search drinks"
        className="w-56 rounded-full border border-gray-300 bg-white px-4 py-1.5 text-sm placeholder-gray-400 focus:border-starbucks focus:outline-none focus:ring-2 focus:ring-starbucks focus:ring-offset-1"
      />
    </div>
  );
}

export default SearchBox;
