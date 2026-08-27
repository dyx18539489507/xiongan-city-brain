import {useCallback, useEffect, useRef, useState} from "react";
import {
  applyPairedDigitalTwinMessage,
  emptyPairedDigitalTwinState,
  parsePairedDigitalTwinMessage,
} from "./ComparisonDigitalTwinStore";
import {DigitalTwinProtocolError} from "./DigitalTwinStore";
import type {DigitalTwinConnection} from "./digitalTwinTypes";
import type {
  PairedDigitalTwinState,
  PairedDigitalTwinStream,
} from "./comparisonDigitalTwinTypes";

type SocketCallbacks = {
  onConnection: (connection: DigitalTwinConnection) => void;
  onState: (state: PairedDigitalTwinState) => void;
  onIssue: (issue: string | null) => void;
};

export function comparisonSocketUrl(location: Location = window.location): string {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/ws/v1/digital-twin/comparison`;
}

export class ComparisonDigitalTwinSocket {
  private socket: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private reconnectAttempt = 0;
  private stopped = false;
  private state = emptyPairedDigitalTwinState;

  constructor(
    private readonly url: string,
    private readonly callbacks: SocketCallbacks,
  ) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.socket?.close(1000, "paired digital-twin client stopped");
    this.socket = null;
  }

  reset(): void {
    this.state = emptyPairedDigitalTwinState;
    this.callbacks.onState(emptyPairedDigitalTwinState);
    this.callbacks.onIssue(null);
  }

  private connect(): void {
    if (this.stopped) return;
    this.callbacks.onConnection(this.reconnectAttempt ? "resyncing" : "connecting");
    const socket = new WebSocket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      this.callbacks.onIssue(null);
      this.callbacks.onConnection("resyncing");
    };
    socket.onmessage = (event) => {
      try {
        if (typeof event.data !== "string") {
          throw new DigitalTwinProtocolError("paired server returned non-JSON data");
        }
        const message = parsePairedDigitalTwinMessage(JSON.parse(event.data) as unknown);
        this.state = applyPairedDigitalTwinMessage(this.state, message);
        this.callbacks.onState(this.state);
        if (message.type === "comparison-init") {
          this.reconnectAttempt = 0;
          this.callbacks.onConnection("online");
        }
      } catch (error: unknown) {
        this.callbacks.onIssue(error instanceof Error ? error.message : String(error));
        this.callbacks.onConnection("resyncing");
        socket.close(4000, "paired protocol resync required");
      }
    };
    socket.onerror = () => this.callbacks.onIssue("实时对照连接失败，正在重连");
    socket.onclose = () => {
      if (this.socket === socket) this.socket = null;
      if (!this.stopped) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    this.callbacks.onConnection("offline");
    const delay = Math.min(5_000, 1_000 * 2 ** Math.min(this.reconnectAttempt, 3));
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
}

export function usePairedDigitalTwinStream(enabled = true): PairedDigitalTwinStream {
  const [connection, setConnection] = useState<DigitalTwinConnection>("connecting");
  const [state, setState] = useState<PairedDigitalTwinState>(emptyPairedDigitalTwinState);
  const [issue, setIssue] = useState<string | null>(null);
  const clientRef = useRef<ComparisonDigitalTwinSocket | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const client = new ComparisonDigitalTwinSocket(comparisonSocketUrl(), {
      onConnection: setConnection,
      onState: setState,
      onIssue: setIssue,
    });
    clientRef.current = client;
    client.start();
    return () => {
      if (clientRef.current === client) clientRef.current = null;
      client.stop();
    };
  }, [enabled]);

  const reset = useCallback(() => {
    clientRef.current?.reset();
    setState(emptyPairedDigitalTwinState);
    setIssue(null);
  }, []);

  return {connection, state, issue, reset};
}
