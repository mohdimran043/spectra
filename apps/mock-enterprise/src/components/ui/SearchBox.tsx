interface SearchBoxProps {
  defaultValue?: string;
  label?: string;
}

/** Plain GET form - no client-side JavaScript required. */
export function SearchBox({ defaultValue = '', label = 'Search records' }: SearchBoxProps) {
  return (
    <form action="/search" method="get" role="search" className="flex flex-wrap items-end gap-2">
      <div className="flex-1 min-w-[220px]">
        <label htmlFor="record-search" className="field-label block">
          {label}
        </label>
        <input
          id="record-search"
          name="q"
          type="search"
          defaultValue={defaultValue}
          maxLength={64}
          placeholder="Identifier, name, service or failure reason"
          className="mt-1 w-full border border-line px-2 py-1.5 text-[13px] text-ink placeholder:text-ink-faint"
        />
      </div>
      <button
        type="submit"
        className="border border-chrome bg-chrome px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-white hover:bg-ink"
      >
        Search
      </button>
    </form>
  );
}
