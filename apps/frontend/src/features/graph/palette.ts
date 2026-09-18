/**
 * Node colour is territory, drawn from the same eleven tokens the rest of the
 * console uses. A label always lands on the same hue, so a node keeps its colour
 * between the investigation panel and the graph division.
 */
const LABEL_TOKENS: readonly string[] = [
  '--mod-document',
  '--mod-image',
  '--mod-video',
  '--mod-audio',
  '--mod-database',
  '--mod-graph',
  '--mod-external',
  '--seal',
  '--caution',
  '--held',
  '--stamp',
];

const FIXED_LABELS: Record<string, string> = {
  Document: '--mod-document',
  Image: '--mod-image',
  Video: '--mod-video',
  Audio: '--mod-audio',
  Record: '--mod-database',
  Table: '--mod-database',
  Chunk: '--mod-external',
  Asset: '--mod-external',
  Source: '--mod-external',
  Entity: '--mod-graph',
  Person: '--held',
  Customer: '--held',
  Transaction: '--caution',
  Incident: '--stamp',
  Service: '--seal',
  Event: '--mod-video',
};

function hash(value: string): number {
  let result = 0;
  for (let index = 0; index < value.length; index += 1) {
    result = (result * 31 + value.charCodeAt(index)) >>> 0;
  }
  return result;
}

export function tokenForLabel(label: string): string {
  const fixed = FIXED_LABELS[label];
  if (fixed) return fixed;
  return LABEL_TOKENS[hash(label) % LABEL_TOKENS.length] ?? '--mod-external';
}

export interface GraphTheme {
  readonly ink: string;
  readonly inkSoft: string;
  readonly rule: string;
  readonly leaf: string;
  readonly board: string;
  readonly focus: string;
  readonly labelColour: (label: string) => string;
}

/** Canvas cannot read custom properties, so the theme is sampled from the DOM. */
export function readGraphTheme(element: HTMLElement): GraphTheme {
  const styles = getComputedStyle(element);
  const read = (token: string) => styles.getPropertyValue(token).trim() || '#888888';
  const cache = new Map<string, string>();

  return {
    ink: read('--ink-0'),
    inkSoft: read('--ink-2'),
    rule: read('--rule-strong'),
    leaf: read('--leaf'),
    board: read('--board'),
    focus: read('--focus'),
    labelColour: (label: string) => {
      const cached = cache.get(label);
      if (cached) return cached;
      const colour = read(tokenForLabel(label));
      cache.set(label, colour);
      return colour;
    },
  };
}
