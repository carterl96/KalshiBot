// Auto-reconnecting WebSocket client for the engine live stream.

import { ENGINE_WS } from "./api";

export type StreamMessage = {
  type: "state" | "market" | "trade" | "decision" | "log";
  data: any;
};

type Handler = (msg: StreamMessage) => void;

export class EngineStream {
  private ws: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private statusHandlers = new Set<(connected: boolean) => void>();
  private closed = false;
  private backoff = 1000;

  connect() {
    this.closed = false;
    this.open();
  }

  private open() {
    try {
      this.ws = new WebSocket(`${ENGINE_WS}/api/stream`);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      this.backoff = 1000;
      this.statusHandlers.forEach((h) => h(true));
    };
    this.ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as StreamMessage;
        this.handlers.forEach((h) => h(msg));
      } catch {
        /* ignore malformed */
      }
    };
    this.ws.onclose = () => {
      this.statusHandlers.forEach((h) => h(false));
      if (!this.closed) this.scheduleReconnect();
    };
    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private scheduleReconnect() {
    setTimeout(() => {
      if (!this.closed) this.open();
    }, this.backoff);
    this.backoff = Math.min(this.backoff * 2, 15000);
  }

  onMessage(h: Handler) {
    this.handlers.add(h);
    return () => this.handlers.delete(h);
  }
  onStatus(h: (connected: boolean) => void) {
    this.statusHandlers.add(h);
    return () => this.statusHandlers.delete(h);
  }

  close() {
    this.closed = true;
    this.ws?.close();
  }
}
