import { cn } from './cn';

/**
 * The wordmark is drawn, not set. SPECTRA's letterforms are struck on a ruled
 * baseline with the aperture of each letter left open — a record stamped rather
 * than typed — so the product's display voice belongs to no installed font.
 */
export function Wordmark({ className, height = 20 }: { className?: string; height?: number }) {
  return (
    <svg
      viewBox="0 0 268 32"
      height={height}
      role="img"
      aria-label="SPECTRA"
      className={cn('block', className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={2.6}
      strokeLinecap="square"
      strokeLinejoin="miter"
    >
      {/* S */}
      <path d="M26 6H6v9h20v11H6" />
      {/* P */}
      <path d="M40 26V6h20v11H40" />
      {/* E */}
      <path d="M94 6H74v20h20M74 16h16" />
      {/* C */}
      <path d="M128 6h-20v20h20" />
      {/* T */}
      <path d="M142 6h20M152 6v20" />
      {/* R */}
      <path d="M176 26V6h20v10h-20M190 16l6 10" />
      {/* A */}
      <path d="M210 26l8-20 8 20M213 19h10" />
      {/* the struck rule that closes the mark */}
      <path d="M238 26h24" strokeWidth={2.6} />
      <path d="M238 6h24" strokeWidth={2.6} />
      <path d="M250 6v20" strokeWidth={2.6} />
    </svg>
  );
}

/** The compact mark used in the rail and the browser tab. */
export function WordmarkGlyph({ className, size = 22 }: { className?: string; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      role="img"
      aria-label="SPECTRA"
      className={cn('block', className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="square"
    >
      <rect x={2} y={2} width={20} height={20} />
      <path d="M17 7H8v4.5h8V17H7" />
    </svg>
  );
}
