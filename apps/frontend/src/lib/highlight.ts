const OPEN_MARK = '«';
const CLOSE_MARK = '»';

export interface SnippetSegment {
  readonly text: string;
  readonly matched: boolean;
}

/**
 * SPECTRA marks retrieval matches inside a snippet with `«…»`. Splitting here
 * rather than in a component keeps the markers out of the DOM and makes the
 * behaviour testable: an unbalanced marker never swallows the rest of the
 * snippet, it just renders as ordinary text.
 */
export function parseHighlightedSnippet(snippet: string): SnippetSegment[] {
  if (!snippet) return [];
  const segments: SnippetSegment[] = [];
  let cursor = 0;

  while (cursor < snippet.length) {
    const openAt = snippet.indexOf(OPEN_MARK, cursor);
    if (openAt === -1) break;

    const closeAt = snippet.indexOf(CLOSE_MARK, openAt + OPEN_MARK.length);
    if (closeAt === -1) break;

    if (openAt > cursor) {
      segments.push({ text: snippet.slice(cursor, openAt), matched: false });
    }
    const matchedText = snippet.slice(openAt + OPEN_MARK.length, closeAt);
    if (matchedText) segments.push({ text: matchedText, matched: true });
    cursor = closeAt + CLOSE_MARK.length;
  }

  if (cursor < snippet.length) {
    segments.push({ text: snippet.slice(cursor), matched: false });
  }
  return segments;
}

/** The snippet with its markers removed — for `title`, `aria-label` and export. */
export function stripHighlightMarks(snippet: string): string {
  return snippet.split(OPEN_MARK).join('').split(CLOSE_MARK).join('');
}
