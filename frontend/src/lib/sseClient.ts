import type { ResultResponse } from '../types/index.ts';

export const SSEEventType = {
  STAGE: 'stage',
  REFERENCE: 'reference',
  CLAIM: 'claim',
  RESULT: 'result',
  DONE: 'done',
  ERROR: 'error',
  CONNECTED: 'connected',
  STATUS: 'status',
  STAGE_STARTED: 'stage_started',
  STAGE_COMPLETED: 'stage_completed',
} as const;
export type SSEEventType = (typeof SSEEventType)[keyof typeof SSEEventType];

export interface SSEParsedMessage {
  id?: string;
  event: string;
  eventType: string;
  stage?: string;
  documentId?: string;
  message?: string;
  payload?: any;
  timestamp?: string;
  raw: any;
}

export interface SSEClientCallbacks {
  onOpen?: () => void;
  onConnected?: (data: { documentId?: string; message?: string }) => void;
  onStage?: (stageOrData: any, status?: any, detail?: any) => void;
  onReference?: (data: any) => void;
  onClaim?: (data: any) => void;
  onResult?: (result: ResultResponse) => void;
  onDone?: (data?: any) => void;
  onError?: (data: any) => void;
  onStatusChange?: (status: 'connecting' | 'connected' | 'reconnecting' | 'idle' | 'closed') => void;
  onMessage?: (msg: SSEParsedMessage) => void;
  onRawMessage?: (msg: SSEParsedMessage) => void;
}

export interface SSEClientOptions {
  url: string;
  callbacks?: SSEClientCallbacks;
  initialLastEventId?: string | null;
  onOpen?: () => void;
  onStatusChange?: (status: 'connecting' | 'connected' | 'reconnecting' | 'idle' | 'closed') => void;
  onMessage?: (msg: SSEParsedMessage) => void;
  onRawMessage?: (msg: SSEParsedMessage) => void;
  onStage?: (stageOrData: any, status?: any, detail?: any) => void;
  onReference?: (refData: any) => void;
  onClaim?: (claimData: any) => void;
  onResult?: (resultData: any) => void;
  onDone?: (payload?: any) => void;
  onError?: (errData: any) => void;
}

/**
 * Safely parses an incoming SSE event payload from an EventSource event or raw text.
 * Never throws on malformed JSON.
 */
export function parseSSEMessage(
  rawInput: string | { data: string; lastEventId?: string; type?: string }
): SSEParsedMessage | null {
  if (!rawInput) {
    return null;
  }

  let rawData = '';
  let eventType = '';
  let lastEventId: string | undefined = undefined;

  if (typeof rawInput === 'string') {
    const trimmed = rawInput.trim();
    if (!trimmed) return null;

    // Check if input is multi-line SSE format (e.g., "event: stage\ndata: {...}")
    const lines = trimmed.split(/\r?\n/);
    const dataLines: string[] = [];

    for (const line of lines) {
      if (line.startsWith('id:')) {
        lastEventId = line.substring(3).trim();
      } else if (line.startsWith('event:')) {
        eventType = line.substring(6).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.substring(5).trim());
      }
    }

    if (dataLines.length > 0) {
      rawData = dataLines.join('\n');
    } else {
      rawData = trimmed;
    }
  } else {
    if (typeof rawInput.data !== 'string') return null;
    rawData = rawInput.data.trim();
    if (!rawData) return null;
    lastEventId = rawInput.lastEventId;
    eventType = rawInput.type && rawInput.type !== 'message' ? rawInput.type : '';
  }

  let parsedData: any = null;
  try {
    parsedData = JSON.parse(rawData);
  } catch {
    // Malformed JSON safely captured as plain text message
    const resolvedType = (eventType || 'message').toLowerCase();
    return {
      id: lastEventId || undefined,
      event: resolvedType,
      eventType: resolvedType,
      message: rawData,
      raw: rawData,
    };
  }

  const finalType = (
    eventType ||
    parsedData.event ||
    parsedData.event_type ||
    'message'
  ).toLowerCase();

  return {
    id: lastEventId || parsedData.id || undefined,
    event: finalType,
    eventType: finalType,
    stage: parsedData.stage || undefined,
    documentId: parsedData.document_id || parsedData.documentId || undefined,
    message: parsedData.message || undefined,
    payload: parsedData.payload || parsedData,
    timestamp: parsedData.created_at || parsedData.timestamp || undefined,
    raw: parsedData,
  };
}

/**
 * Deduplicator to prevent duplicate event processing across reconnections and replayed streams.
 */
export class EventDeduplicator {
  private seenKeys: Set<string>;
  private maxEntries: number;

  constructor(maxEntries = 500) {
    this.seenKeys = new Set();
    this.maxEntries = maxEntries;
  }

  public getFingerprint(msg: any): string {
    if (!msg) return '';
    if (msg.id) {
      return `id:${msg.id}`;
    }
    const stageStr = msg.stage || '';
    const eventStr = msg.event || msg.eventType || '';
    const msgStr = msg.message || '';
    const payloadKey = msg.payload?.id || msg.payload?.claim_id || msg.payload?.raw || '';
    return `${eventStr}_${stageStr}_${payloadKey}_${msgStr}`;
  }

  public isDuplicate(msg: any): boolean {
    const key = this.getFingerprint(msg);
    return this.seenKeys.has(key);
  }

  public markSeen(msg: any): boolean {
    const key = this.getFingerprint(msg);
    if (this.seenKeys.has(key)) {
      return false; // Already seen
    }
    if (this.seenKeys.size >= this.maxEntries) {
      const first = this.seenKeys.values().next().value;
      if (first) this.seenKeys.delete(first);
    }
    this.seenKeys.add(key);
    return true; // Newly added
  }

  public clear(): void {
    this.seenKeys.clear();
  }
}

/**
 * Production-ready SSE client for CiteVerify verification streams.
 * Supports auto-reconnect, Last-Event-ID replay, deduplication, and granular events.
 */
export class CiteVerifySSEClient {
  private url: string;
  private callbacks: SSEClientCallbacks;
  private deduplicator: EventDeduplicator;
  private eventSource: EventSource | null = null;
  private lastEventId: string | null = null;
  private status: 'connecting' | 'connected' | 'reconnecting' | 'idle' | 'closed' = 'connecting';
  private isExplicitlyClosed = false;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 8;
  private reconnectTimeout: any = null;

  constructor(
    urlOrOptions: string | SSEClientOptions,
    callbacks: SSEClientCallbacks = {},
    initialLastEventId: string | null = null
  ) {
    if (typeof urlOrOptions === 'string') {
      this.url = urlOrOptions;
      this.callbacks = callbacks;
      this.lastEventId = initialLastEventId;
    } else {
      this.url = urlOrOptions.url;
      this.callbacks = {
        ...urlOrOptions.callbacks,
        onOpen: urlOrOptions.onOpen || urlOrOptions.callbacks?.onOpen,
        onStatusChange: urlOrOptions.onStatusChange || urlOrOptions.callbacks?.onStatusChange,
        onMessage: urlOrOptions.onMessage || urlOrOptions.callbacks?.onMessage,
        onRawMessage: urlOrOptions.onRawMessage || urlOrOptions.callbacks?.onRawMessage,
        onStage: urlOrOptions.onStage || urlOrOptions.callbacks?.onStage,
        onReference: urlOrOptions.onReference || urlOrOptions.callbacks?.onReference,
        onClaim: urlOrOptions.onClaim || urlOrOptions.callbacks?.onClaim,
        onResult: urlOrOptions.onResult || urlOrOptions.callbacks?.onResult,
        onDone: urlOrOptions.onDone || urlOrOptions.callbacks?.onDone,
        onError: urlOrOptions.onError || urlOrOptions.callbacks?.onError,
      };
      this.lastEventId = urlOrOptions.initialLastEventId || null;
    }
    this.deduplicator = new EventDeduplicator();
  }

  public getStatus(): 'connecting' | 'connected' | 'reconnecting' | 'idle' | 'closed' {
    return this.status;
  }

  public getLastEventId(): string | null {
    return this.lastEventId;
  }

  public getDeduplicator(): EventDeduplicator {
    return this.deduplicator;
  }

  public connect(): void {
    if (this.isExplicitlyClosed) return;

    this.status = this.reconnectAttempts > 0 ? 'reconnecting' : 'connecting';
    this.callbacks.onStatusChange?.(this.status);

    // If running in non-browser environment without EventSource, gracefully no-op
    if (typeof EventSource === 'undefined') {
      return;
    }

    // Build URL with Last-Event-ID query parameter for servers that do not evaluate EventSource headers
    let connectUrl = this.url;
    if (this.lastEventId) {
      const separator = connectUrl.includes('?') ? '&' : '?';
      connectUrl = `${connectUrl}${separator}last_event_id=${encodeURIComponent(this.lastEventId)}`;
    }

    try {
      this.eventSource = new EventSource(connectUrl);

      this.eventSource.onopen = () => {
        this.reconnectAttempts = 0;
        this.status = 'connected';
        this.callbacks.onOpen?.();
        this.callbacks.onStatusChange?.('connected');
      };

      const handleRawEvent = (e: MessageEvent) => {
        const parsed = parseSSEMessage({
          data: e.data,
          lastEventId: e.lastEventId || this.lastEventId || undefined,
          type: e.type,
        });

        if (!parsed) return;

        if (parsed.id) {
          this.lastEventId = parsed.id;
        }

        // Deduplication guard
        if (!this.deduplicator.markSeen(parsed)) {
          return;
        }

        this.callbacks.onMessage?.(parsed);
        this.callbacks.onRawMessage?.(parsed);
        this.dispatchParsedMessage(parsed);
      };

      // Register default message handler
      this.eventSource.onmessage = handleRawEvent;

      // Register named listeners for granular events
      const eventNames = [
        'stage',
        'reference',
        'claim',
        'result',
        'done',
        'error',
        'status',
        'connected',
        'stage_started',
        'stage_completed',
      ];
      for (const name of eventNames) {
        this.eventSource.addEventListener(name, (e: any) => handleRawEvent(e));
      }

      this.eventSource.onerror = () => {
        if (this.isExplicitlyClosed) return;

        if (this.eventSource?.readyState === EventSource.CLOSED) {
          this.status = 'closed';
          this.callbacks.onStatusChange?.('closed');
          this.scheduleReconnect();
        } else {
          this.status = 'reconnecting';
          this.callbacks.onStatusChange?.('reconnecting');
        }
      };
    } catch (err: any) {
      this.callbacks.onError?.({
        message: `Failed to initialize EventSource connection: ${err.message || ''}`,
      });
      this.scheduleReconnect();
    }
  }

  private dispatchParsedMessage(msg: SSEParsedMessage): void {
    const type = msg.event || msg.eventType;

    switch (type) {
      case 'connected':
        this.callbacks.onConnected?.({
          documentId: msg.documentId,
          message: msg.message,
        });
        break;

      case 'status':
        if (msg.stage === 'idle') {
          this.status = 'idle';
          this.callbacks.onStatusChange?.('idle');
        }
        break;

      case 'stage':
      case 'stage_started':
      case 'stage_completed':
        if (msg.stage) {
          const isDone =
            type === 'stage_completed' ||
            msg.payload?.status === 'done' ||
            msg.payload?.status === 'completed';
          const isErr = msg.payload?.status === 'error';
          const stageStatus = isDone ? 'done' : isErr ? 'error' : 'active';
          const detail = msg.message || msg.payload?.message;

          // Support both callback shapes: (stage, status, detail) and ({ stage, status, message })
          if (this.callbacks.onStage) {
            this.callbacks.onStage(msg.stage, stageStatus, detail);
          }
        }
        break;

      case 'reference':
        this.callbacks.onReference?.(msg.payload || msg);
        break;

      case 'claim':
        this.callbacks.onClaim?.(msg.payload || msg);
        break;

      case 'result':
        if (msg.payload && msg.payload.verdict) {
          this.callbacks.onResult?.(msg.payload as ResultResponse);
        }
        break;

      case 'done':
      case 'pipeline_completed':
        this.callbacks.onDone?.(msg.payload || {
          documentId: msg.documentId,
          message: msg.message || 'Verification pipeline completed successfully.',
        });
        break;

      case 'error':
        this.callbacks.onError?.(msg.payload || {
          stage: msg.stage,
          message: msg.message || 'Pipeline stage failed.',
        });
        break;

      default:
        break;
    }
  }

  private scheduleReconnect(): void {
    if (this.isExplicitlyClosed || this.reconnectAttempts >= this.maxReconnectAttempts) {
      return;
    }

    this.reconnectAttempts++;
    // Exponential backoff with ceiling: 1s, 2s, 4s, 8s, up to 15s max
    const backoffMs = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 15000);

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
    }

    this.reconnectTimeout = setTimeout(() => {
      if (!this.isExplicitlyClosed) {
        if (this.eventSource) {
          this.eventSource.close();
          this.eventSource = null;
        }
        this.connect();
      }
    }, backoffMs);
  }

  public close(): void {
    this.isExplicitlyClosed = true;
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    this.status = 'closed';
    this.callbacks.onStatusChange?.('closed');
  }
}
