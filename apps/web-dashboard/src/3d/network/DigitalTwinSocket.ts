import {useCallback, useEffect, useRef, useState} from "react";
import {
  applyDigitalTwinMessage,
  DigitalTwinProtocolError,
  emptyDigitalTwinState,
  parseDigitalTwinMessage,
} from "./DigitalTwinStore";
import type {
  DigitalTwinConnection,
  DigitalTwinState,
  DigitalTwinStream,
} from "./digitalTwinTypes";

type SocketCallbacks = {
  onConnection: (connection: DigitalTwinConnection) => void;
  onState: (state: DigitalTwinState) => void;
  onIssue: (issue: string | null) => void;
};

export function digitalTwinSocketUrl(location: Location = window.location): string {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/ws/v1/digital-twin`;
}

export class DigitalTwinSocket {
  private socket: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private reconnectAttempt = 0;
  private stopped = false;
  private state = emptyDigitalTwinState;

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
    this.socket?.close(1000, "digital-twin client stopped");
    this.socket = null;
  }

  reset(): void {
    this.state = emptyDigitalTwinState;
    this.callbacks.onState(emptyDigitalTwinState);
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
          throw new DigitalTwinProtocolError("digital-twin server returned non-JSON data");
        }
        const message = parseDigitalTwinMessage(JSON.parse(event.data) as unknown);
        this.state = applyDigitalTwinMessage(this.state, message);
        this.callbacks.onState(this.state);
        if (message.type === "init") {
          this.reconnectAttempt = 0;
          this.callbacks.onConnection("online");
        }
      } catch (error: unknown) {
        const issue = error instanceof Error ? error.message : String(error);
        this.callbacks.onIssue(issue);
        this.callbacks.onConnection("resyncing");
        socket.close(4000, "protocol resync required");
      }
    };
    socket.onerror = () => {
      this.callbacks.onIssue("实体流连接失败，正在重连");
    };
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

export function useDigitalTwinStream(enabled = true): DigitalTwinStream {
  const [connection, setConnection] = useState<DigitalTwinConnection>("connecting");
  const [state, setState] = useState<DigitalTwinState>(emptyDigitalTwinState);
  const [issue, setIssue] = useState<string | null>(null);
  const clientRef = useRef<DigitalTwinSocket | null>(null);

  useEffect(() => {
    if (!enabled) return;
    setConnection("connecting");
    setIssue(null);
    const client = new DigitalTwinSocket(digitalTwinSocketUrl(), {
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
    setState(emptyDigitalTwinState);
    setIssue(null);
  }, []);

  return {connection, state, issue, reset};
}
