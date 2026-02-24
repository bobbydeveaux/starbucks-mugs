interface SearchBoxProps {
  value: string;
  onChange: (query: string) => void;
  placeholder?: string;
}

export function SearchBox({ value, onChange, placeholder = 'Search drinks…' }: SearchBoxProps) {
  return (
    <div className="relative">
      <label htmlFor="search-box" className="sr-only">
        Search drinks
      </label>
      <input
        id="search-box"
        type="search"
        placeholder={placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="border rounded-full px-4 py-1.5 text-sm w-56 focus:outline-none focus:ring-2 focus:ring-gray-900 pr-8"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          className="absolute inset-y-0 right-2 flex items-center text-gray-400 hover:text-gray-600"
          aria-label="Clear search"
        >
          ×
        </button>
      )}
    </div>
  );
}

export default SearchBox;
