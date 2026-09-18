import type { SVGProps } from 'react';

import { cn } from './cn';

/**
 * One drawn icon system. Every glyph is authored on a 16×16 grid with a 1.25px
 * square-capped stroke, so the set reads as one hand at any size. No unicode
 * glyph or emoji ever stands in for an icon in this product.
 */
export interface IconProps extends SVGProps<SVGSVGElement> {
  readonly size?: number;
}

function Icon({ size = 16, className, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.25}
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden="true"
      focusable="false"
      className={cn('shrink-0', className)}
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconDocument = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3.5 1.5h6l3 3v10h-9z" />
    <path d="M9.5 1.5v3h3" />
    <path d="M5.5 8h5M5.5 10.5h5M5.5 5.5h2" />
  </Icon>
);

export const IconImage = (p: IconProps) => (
  <Icon {...p}>
    <rect x={1.5} y={2.5} width={13} height={11} />
    <path d="M1.5 11l3.5-3.5 3 3 2.5-2.5 3 3" />
    <circle cx={5.5} cy={5.75} r={1} />
  </Icon>
);

export const IconVideo = (p: IconProps) => (
  <Icon {...p}>
    <rect x={1.5} y={3.5} width={9} height={9} />
    <path d="M10.5 7.5l4-2.5v6l-4-2.5z" />
  </Icon>
);

export const IconAudio = (p: IconProps) => (
  <Icon {...p}>
    <path d="M1.5 6.5v3M4.25 4v8M7 2v12M9.75 5v6M12.5 7v2M15 6.5v3" />
  </Icon>
);

export const IconDatabase = (p: IconProps) => (
  <Icon {...p}>
    <ellipse cx={8} cy={3.5} rx={5.5} ry={2} />
    <path d="M2.5 3.5v9c0 1.1 2.46 2 5.5 2s5.5-.9 5.5-2v-9" />
    <path d="M2.5 8c0 1.1 2.46 2 5.5 2s5.5-.9 5.5-2" />
  </Icon>
);

export const IconGraph = (p: IconProps) => (
  <Icon {...p}>
    <circle cx={3.5} cy={12.5} r={2} />
    <circle cx={12.5} cy={11.5} r={1.75} />
    <circle cx={8} cy={3.5} r={2} />
    <path d="M7.1 5.3L4.4 10.7M9.4 5.2l2.4 4.7M5.5 12.2l5.2-.5" />
  </Icon>
);

export const IconExternalSource = (p: IconProps) => (
  <Icon {...p}>
    <circle cx={8} cy={8} r={6.5} />
    <path d="M1.5 8h13M8 1.5c1.8 2 2.7 4.2 2.7 6.5S9.8 12.5 8 14.5C6.2 12.5 5.3 10.3 5.3 8S6.2 3.5 8 1.5z" />
  </Icon>
);

export const IconBrain = (p: IconProps) => (
  <Icon {...p}>
    <rect x={2.5} y={2.5} width={11} height={11} />
    <path d="M5.5 5.5h5v5h-5z" />
    <path d="M8 2.5v3M8 10.5v3M2.5 8h3M10.5 8h3" />
  </Icon>
);

export const IconVerifier = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 1.5l5.5 2v5c0 3-2.4 5.4-5.5 6.5C4.9 13.9 2.5 11.5 2.5 8.5v-5z" />
    <path d="M5.75 8.25l1.6 1.6 3-3.4" />
  </Icon>
);

export const IconDisproof = (p: IconProps) => (
  <Icon {...p}>
    <circle cx={8} cy={8} r={6.25} />
    <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" />
  </Icon>
);

export const IconEntity = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4.5 1.5c0 3 7 3 7 6s-7 3-7 6" />
    <path d="M11.5 1.5c0 3-7 3-7 6s7 3 7 6" />
    <path d="M5.25 4.5h5.5M5.25 11.5h5.5" />
  </Icon>
);

export const IconTimeline = (p: IconProps) => (
  <Icon {...p}>
    <path d="M2 13.5h12" />
    <path d="M4 13.5v-4M8 13.5v-8M12 13.5v-6" />
    <circle cx={4} cy={8.5} r={1} />
    <circle cx={8} cy={4.5} r={1} />
    <circle cx={12} cy={6.5} r={1} />
  </Icon>
);

export const IconSearch = (p: IconProps) => (
  <Icon {...p}>
    <circle cx={7} cy={7} r={4.75} />
    <path d="M10.5 10.5l4 4" />
  </Icon>
);

export const IconUpload = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 11V2.5M4.75 5.75L8 2.5l3.25 3.25" />
    <path d="M2.5 10v3.5h11V10" />
  </Icon>
);

export const IconPlay = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4.5 2.5l9 5.5-9 5.5z" />
  </Icon>
);

export const IconChevronRight = (p: IconProps) => (
  <Icon {...p}>
    <path d="M6 3l5 5-5 5" />
  </Icon>
);

export const IconChevronDown = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 6l5 5 5-5" />
  </Icon>
);

export const IconClose = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
  </Icon>
);

export const IconWarning = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 1.5l6.5 12h-13z" />
    <path d="M8 6v3.5" />
    <path d="M8 11.4v.6" strokeWidth={1.6} />
  </Icon>
);

export const IconCheck = (p: IconProps) => (
  <Icon {...p}>
    <path d="M2.5 8.5l3.5 3.5 7.5-8" />
  </Icon>
);

export const IconDash = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 8h10" />
  </Icon>
);

export const IconClock = (p: IconProps) => (
  <Icon {...p}>
    <circle cx={8} cy={8} r={6.25} />
    <path d="M8 4.25V8l2.75 1.75" />
  </Icon>
);

export const IconLinkOut = (p: IconProps) => (
  <Icon {...p}>
    <path d="M9.5 2.5h4v4" />
    <path d="M13.5 2.5l-6 6" />
    <path d="M12 9.5v4h-9.5v-9.5h4" />
  </Icon>
);

export const IconFilter = (p: IconProps) => (
  <Icon {...p}>
    <path d="M1.5 3h13l-5 5.5v5l-3-1.75v-3.25z" />
  </Icon>
);

export const IconGpu = (p: IconProps) => (
  <Icon {...p}>
    <rect x={1.5} y={4.5} width={13} height={8} />
    <rect x={4.5} y={7} width={4} height={3} />
    <path d="M4 4.5v-2M8 4.5v-2M12 4.5v-2M11 8h2.5M11 10h2.5" />
  </Icon>
);

export const IconAgent = (p: IconProps) => (
  <Icon {...p}>
    <rect x={3.5} y={5.5} width={9} height={7} />
    <path d="M8 5.5V3M6.5 1.5h3" />
    <path d="M6 8.25h.01M10 8.25h.01" strokeWidth={1.75} />
    <path d="M6.5 10.5h3" />
  </Icon>
);

export const IconSettings = (p: IconProps) => (
  <Icon {...p}>
    <path d="M2 4h12M2 8h12M2 12h12" />
    <circle cx={5.5} cy={4} r={1.5} fill="var(--leaf)" />
    <circle cx={10.5} cy={8} r={1.5} fill="var(--leaf)" />
    <circle cx={6.5} cy={12} r={1.5} fill="var(--leaf)" />
  </Icon>
);

export const IconDemo = (p: IconProps) => (
  <Icon {...p}>
    <rect x={1.5} y={2.5} width={13} height={9} />
    <path d="M5.5 13.5h5M8 11.5v2" />
    <path d="M6.5 5.5l3 1.5-3 1.5z" />
  </Icon>
);

export const IconLedger = (p: IconProps) => (
  <Icon {...p}>
    <rect x={2.5} y={1.5} width={11} height={13} />
    <path d="M5.5 1.5v13" />
    <path d="M7.25 4.5h4M7.25 7h4M7.25 9.5h4" />
  </Icon>
);

export const IconHome = (p: IconProps) => (
  <Icon {...p}>
    <path d="M1.5 7.5L8 2l6.5 5.5" />
    <path d="M3.5 8.5v6h9v-6" />
  </Icon>
);

export const IconTheme = (p: IconProps) => (
  <Icon {...p}>
    <circle cx={8} cy={8} r={5.5} />
    <path d="M8 2.5v11" />
    <path d="M8 2.5a5.5 5.5 0 010 11z" fill="currentColor" stroke="none" />
  </Icon>
);

export const IconRefresh = (p: IconProps) => (
  <Icon {...p}>
    <path d="M13.5 8a5.5 5.5 0 11-1.9-4.15" />
    <path d="M13.5 1.5v3h-3" />
  </Icon>
);

export const IconSql = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 4.5L1.5 8 5 11.5M11 4.5L14.5 8 11 11.5" />
    <path d="M9.25 3l-2.5 10" />
  </Icon>
);

export const IconEye = (p: IconProps) => (
  <Icon {...p}>
    <path d="M1 8s2.6-4.5 7-4.5S15 8 15 8s-2.6 4.5-7 4.5S1 8 1 8z" />
    <circle cx={8} cy={8} r={1.9} />
  </Icon>
);
