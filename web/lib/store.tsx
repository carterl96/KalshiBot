"use client";

// App-wide providers: auth token + live engine state from the WebSocket.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  EngineState,
  Health,
  api,
  clearToken,
  getToken,
  setToken,
} from "./api";
import { EngineStream, StreamMessage } from "./ws";

// ---- Auth ----
interface AuthCtx {
  token: string | null;
  ready: boolean;
  login: (password: string) => Promise<void>;
  logout: () => void;
}
const AuthContext = createContext<AuthCtx>({
  token: null,
  ready: false,
  login: async () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTok] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const router = useRouter();

  useEffect(() => {
    setTok(getToken());
    setReady(true);
  }, []);

  const login = useCallback(async (password: string) => {
    const { token } = await api.login(password);
    setToken(token);
    setTok(token);
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setTok(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ token, ready, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
export const useAuth = () => useContext(AuthContext);

// ---- Live engine state ----
interface EngineCtx {
  connected: boolean;
  health: Health | null;
  state: EngineState | null;
  refresh: () => void;
}
const EngineContext = createContext<EngineCtx>({
  connected: false,
  health: null,
  state: null,
  refresh: () => {},
});

export function EngineProvider({ children }: { children: React.ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [state, setState] = useState<EngineState | null>(null);
  const streamRef = useRef<EngineStream | null>(null);

  const refresh = useCallback(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.state().then(setState).catch(() => setState(null));
  }, []);

  useEffect(() => {
    refresh();
    const poll = setInterval(refresh, 10000);
    const stream = new EngineStream();
    streamRef.current = stream;
    const offMsg = stream.onMessage((msg: StreamMessage) => {
      if (msg.type === "state") setState(msg.data as EngineState);
    });
    const offStatus = stream.onStatus(setConnected);
    stream.connect();
    return () => {
      clearInterval(poll);
      offMsg();
      offStatus();
      stream.close();
    };
  }, [refresh]);

  const value = useMemo(
    () => ({ connected, health, state, refresh }),
    [connected, health, state, refresh]
  );
  return (
    <EngineContext.Provider value={value}>{children}</EngineContext.Provider>
  );
}
export const useEngine = () => useContext(EngineContext);

// Subscribe to raw stream messages (for trade/decision feeds).
export function useStream(handler: (msg: StreamMessage) => void) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const stream = new EngineStream();
    const off = stream.onMessage((m) => ref.current(m));
    stream.connect();
    return () => {
      off();
      stream.close();
    };
  }, []);
}
