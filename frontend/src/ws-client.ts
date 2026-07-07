import { WSCommand, WSEvent } from './types';

export class WSClient {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private listeners: Map<string, Set<(payload: any, event: WSEvent) => void>> = new Map();
  private intentionalClose = false;

  constructor(url?: string) {
    this.url = url || `ws://${window.location.hostname}:8765/ws`;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;
    this.intentionalClose = false;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.reconnectAttempt = 0;
        this.dispatch('open', {});
      };

      this.ws.onmessage = (event: MessageEvent) => {
        this.handleMessage(event);
      };

      this.ws.onclose = () => {
        this.dispatch('close', {});
        if (!this.intentionalClose) {
          this.reconnect();
        }
      };

      this.ws.onerror = () => {
        // onclose will fire after onerror
      };
    } catch {
      this.reconnect();
    }
  }

  disconnect(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  send(command: WSCommand): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(command));
    }
  }

  on(eventType: string, handler: (payload: any, event: WSEvent) => void): () => void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set());
    }
    this.listeners.get(eventType)!.add(handler);
    return () => this.off(eventType, handler);
  }

  off(eventType: string, handler: (payload: any, event: WSEvent) => void): void {
    this.listeners.get(eventType)?.delete(handler);
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private handleMessage(event: MessageEvent): void {
    try {
      const wsEvent: WSEvent = JSON.parse(event.data);
      this.dispatch(wsEvent.type, wsEvent.payload, wsEvent);
    } catch (err) {
      console.error('[WSClient] Failed to parse message:', err);
    }
  }

  private dispatch(eventType: string, payload: any, wsEvent?: WSEvent): void {
    const handlers = this.listeners.get(eventType);
    if (handlers) {
      for (const handler of handlers) {
        try {
          handler(payload, wsEvent || { type: eventType, payload, session_id: '' });
        } catch (err) {
          console.error(`[WSClient] Handler error for "${eventType}":`, err);
        }
      }
    }
  }

  private reconnect(): void {
    if (this.intentionalClose) return;

    const delays = [1000, 2000, 4000, 5000];
    const delay = delays[Math.min(this.reconnectAttempt, delays.length - 1)];
    this.reconnectAttempt++;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
}
