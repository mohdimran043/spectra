'use client';

import { useEffect, useRef, useState } from 'react';

import { cn } from '@/components/cn';
import { formatTimecode, formatTimecodeRange } from '@/lib/format';

/**
 * A video opened from a citation starts at the cited second, not at zero. The
 * source carries a media fragment so a cold load lands in the right place, and
 * the ref seeks again once metadata arrives for the case where the server
 * ignores the fragment.
 */
export function SeekedVideo({
  src,
  startSeconds,
  endSeconds,
  poster,
}: {
  src: string;
  startSeconds: number | null | undefined;
  endSeconds?: number | null;
  poster?: string;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  const start = startSeconds ?? 0;

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const seek = () => {
      if (Number.isFinite(start) && start > 0) element.currentTime = start;
    };
    element.addEventListener('loadedmetadata', seek);
    return () => element.removeEventListener('loadedmetadata', seek);
  }, [start, src]);

  return (
    <div className="flex flex-col gap-1.5">
      <video
        ref={ref}
        controls
        preload="metadata"
        poster={poster}
        src={`${src}#t=${Math.max(0, Math.floor(start))}`}
        onError={() =>
          setError(
            'The video could not be loaded. The asset route must support Range requests for seeking.',
          )
        }
        className="w-full border border-rule bg-board-sunk"
      >
        <track kind="captions" />
      </video>
      <p className="font-mono text-micro tabular text-ink-2">
        cited at {formatTimecodeRange(startSeconds, endSeconds ?? null)}
      </p>
      {error && <p className="text-mark text-stamp">{error}</p>}
    </div>
  );
}

export function SeekedAudio({
  src,
  startSeconds,
  endSeconds,
  speaker,
}: {
  src: string;
  startSeconds: number | null | undefined;
  endSeconds?: number | null;
  speaker?: string | null;
}) {
  const ref = useRef<HTMLAudioElement>(null);
  const [error, setError] = useState<string | null>(null);
  const start = startSeconds ?? 0;

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const seek = () => {
      if (Number.isFinite(start) && start > 0) element.currentTime = start;
    };
    element.addEventListener('loadedmetadata', seek);
    return () => element.removeEventListener('loadedmetadata', seek);
  }, [start, src]);

  return (
    <div className="flex flex-col gap-1.5">
      <audio
        ref={ref}
        controls
        preload="metadata"
        src={`${src}#t=${Math.max(0, Math.floor(start))}`}
        onError={() => setError('The audio could not be loaded from the asset route.')}
        className="w-full"
      />
      <p className="font-mono text-micro tabular text-ink-2">
        segment {formatTimecodeRange(startSeconds, endSeconds ?? null)}
        {speaker ? ` · ${speaker}` : ''}
      </p>
      {error && <p className="text-mark text-stamp">{error}</p>}
    </div>
  );
}

const TICK_COUNT = 64;

/**
 * A segment rail, not a waveform: SPECTRA does not ship amplitude data, so the
 * rail shows where the cited segment sits inside the clip and nothing it cannot
 * know. Drawing an invented waveform here would be a decorative chart.
 */
export function SegmentRail({
  startSeconds,
  endSeconds,
  durationSeconds,
  className,
}: {
  startSeconds: number | null | undefined;
  endSeconds: number | null | undefined;
  durationSeconds?: number | null;
  className?: string;
}) {
  const start = startSeconds ?? 0;
  const end = endSeconds ?? start;
  const span = durationSeconds && durationSeconds > 0 ? durationSeconds : Math.max(end * 1.25, 1);
  const left = Math.max(0, Math.min(1, start / span));
  const width = Math.max(0.012, Math.min(1 - left, (end - start) / span));

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <div
        className="relative flex h-6 items-end gap-[2px] border border-rule bg-board-sunk px-1 py-1"
        role="img"
        aria-label={`Cited segment ${formatTimecodeRange(startSeconds, endSeconds)}${
          durationSeconds ? ` of ${formatTimecode(durationSeconds)}` : ''
        }`}
      >
        {Array.from({ length: TICK_COUNT }, (_, index) => {
          const position = index / TICK_COUNT;
          const inSegment = position >= left && position <= left + width;
          return (
            <span
              key={index}
              className={cn('block flex-1', inSegment ? 'bg-mod-audio' : 'bg-rule')}
              style={{ height: inSegment ? '100%' : '35%' }}
            />
          );
        })}
      </div>
      <div className="flex justify-between font-mono text-micro tabular text-ink-2">
        <span>{formatTimecode(startSeconds)}</span>
        <span>{formatTimecode(endSeconds)}</span>
      </div>
    </div>
  );
}
