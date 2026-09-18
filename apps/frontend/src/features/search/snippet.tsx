import { cn } from '@/components/cn';
import { parseHighlightedSnippet, stripHighlightMarks } from '@/lib/highlight';

/**
 * The API marks retrieval matches with `«…»`. They render as struck highlights
 * in the modality's own territory ink, so a reader can see *why* a passage was
 * returned without reading the whole chunk.
 */
export function Snippet({
  text,
  className,
  clamp,
}: {
  text: string;
  className?: string;
  clamp?: number;
}) {
  const segments = parseHighlightedSnippet(text);
  if (segments.length === 0) return null;

  return (
    <p
      className={cn('text-body text-ink', className)}
      style={clamp ? { display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: clamp, overflow: 'hidden' } : undefined}
      title={stripHighlightMarks(text)}
    >
      {segments.map((segment, index) =>
        segment.matched ? (
          <mark
            key={index}
            className="bg-caution-weak px-[1px] font-semibold text-ink decoration-clone"
          >
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </p>
  );
}
