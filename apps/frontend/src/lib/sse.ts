export interface ServerSentEvent {
  readonly event: string;
  readonly data: string;
  readonly id: string | null;
}

export interface EventStreamHandlers {
  readonly onEvent: (event: ServerSentEvent) => void;
  /** Fired for `: keep-alive` comments so the caller can prove the link is live. */
  readonly onHeartbeat?: () => void;
  readonly onOpen?: () => void;
}

const FIELD_SEPARATOR = ':';

/**
 * A minimal SSE reader built on `fetch`.
 *
 * `EventSource` cannot set request headers, and SPECTRA authorises every request
 * with `X-Spectra-Role` / `X-Spectra-User` — an investigation stream opened
 * without them would be a different user's stream. This reader also lets the
 * caller resume with `Last-Event-ID`, which `EventSource` only does on its own
 * terms.
 */
export async function readEventStream(
  url: string,
  {
    headers,
    signal,
    lastEventId,
    handlers,
  }: {
    headers: Record<string, string>;
    signal: AbortSignal;
    lastEventId?: string | null;
    handlers: EventStreamHandlers;
  },
): Promise<void> {
  const requestHeaders: Record<string, string> = {
    ...headers,
    Accept: 'text/event-stream',
    'Cache-Control': 'no-cache',
  };
  if (lastEventId) requestHeaders['Last-Event-ID'] = lastEventId;

  const response = await fetch(url, { headers: requestHeaders, signal, cache: 'no-store' });

  if (!response.ok) {
    throw new Error(`The event stream returned HTTP ${response.status} ${response.statusText}`);
  }
  if (!response.body) {
    throw new Error('The event stream returned no body. Streaming is unavailable in this runtime.');
  }

  handlers.onOpen?.();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventName = 'message';
  let dataLines: string[] = [];
  let eventId: string | null = null;

  const dispatch = () => {
    if (dataLines.length === 0) {
      eventName = 'message';
      eventId = null;
      return;
    }
    handlers.onEvent({ event: eventName, data: dataLines.join('\n'), id: eventId });
    eventName = 'message';
    dataLines = [];
    eventId = null;
  };

  const consumeLine = (line: string) => {
    if (line === '') {
      dispatch();
      return;
    }
    if (line.startsWith(FIELD_SEPARATOR)) {
      handlers.onHeartbeat?.();
      return;
    }
    const separatorAt = line.indexOf(FIELD_SEPARATOR);
    const field = separatorAt === -1 ? line : line.slice(0, separatorAt);
    const rawValue = separatorAt === -1 ? '' : line.slice(separatorAt + 1);
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue;

    if (field === 'event') eventName = value;
    else if (field === 'data') dataLines.push(value);
    else if (field === 'id') eventId = value;
    /* `retry` is accepted and ignored: reconnection timing is owned by the hook. */
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let newlineAt = buffer.indexOf('\n');
      while (newlineAt !== -1) {
        const line = buffer.slice(0, newlineAt).replace(/\r$/, '');
        buffer = buffer.slice(newlineAt + 1);
        consumeLine(line);
        newlineAt = buffer.indexOf('\n');
      }
    }
    if (buffer.length > 0) consumeLine(buffer.replace(/\r$/, ''));
    dispatch();
  } finally {
    reader.releaseLock();
  }
}
