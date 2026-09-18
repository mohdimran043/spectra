/** Shown on a detail page opened from a SPECTRA evidence deep link. */
export function SpectraBanner({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <p
      className="mb-4 border-l-4 border-blue-700 bg-blue-50 px-3 py-2 text-blue-900"
      data-testid="spectra-banner"
    >
      <span className="font-semibold">Opened from SPECTRA</span> — this record was reached
      from an investigation evidence link.
    </p>
  );
}
