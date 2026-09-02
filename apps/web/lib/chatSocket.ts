// Единый WebSocket для чата на всё приложение (layout), чтобы уведомления о
// новых сообщениях (в т.ч. о назначении на ремонт) приходили на любую страницу.
// Подписчики: layout (бейдж+звук) и страница чата (показ сообщений).

type Handler = (event: any) => void;

let ws: WebSocket | null = null;
let currentToken: string | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
const subs = new Set<Handler>();

export function subscribeChat(fn: Handler): () => void {
  subs.add(fn);
  return () => {
    subs.delete(fn);
  };
}

function dispatch(event: any) {
  subs.forEach((fn) => {
    try {
      fn(event);
    } catch {
      /* ignore */
    }
  });
}

function baseUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return process.env.NEXT_PUBLIC_WS_URL || `${scheme}://${window.location.host}`;
}

export function connectChat(token: string) {
  if (!token) return;
  // Уже подключены с этим токеном.
  if (ws && currentToken === token && ws.readyState === WebSocket.OPEN) return;
  if (ws) {
    try {
      ws.close();
    } catch {
      /* ignore */
    }
    ws = null;
  }
  currentToken = token;
  const sock = new WebSocket(`${baseUrl()}/ws?token=${encodeURIComponent(token)}`);
  ws = sock;
  sock.onmessage = (ev) => {
    try {
      dispatch(JSON.parse(ev.data));
    } catch {
      /* ignore */
    }
  };
  sock.onclose = () => {
    if (sock !== ws) return;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      if (currentToken && document.visibilityState !== "hidden") connectChat(currentToken);
    }, 3000);
  };
}

export function disconnectChat() {
  currentToken = null;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  if (ws) {
    ws.onclose = null;
    try {
      ws.close();
    } catch {
      /* ignore */
    }
    ws = null;
  }
}
