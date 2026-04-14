import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ChatMessage } from "../types/chat";

// =============================================================================
// TYPES
// =============================================================================

interface ServitorResult {
  status: "OPTIMAL" | "REVIEW" | "CRITICAL";
  confidence: number | null;
  mortality_estimate: number | null;
  risk_category: string | null;
  deficiency: string | null;
  amendment: string | null;
  recommended_action: string | null;
  audio_data?: string;
  audio_format?: string;
}

interface UseChatOptions {
  initialMessages?: ChatMessage[];
  onAssistantMessageComplete?: (message: ChatMessage) => void | Promise<void>;
  onServitorResult?: (result: ServitorResult) => void;
  // Now receives requestId so App.tsx queue can send playback_complete at the right time
  onVerityAudio?: (audioData: string, requestId: string) => void;
  onServitorAudio?: (audioData: string, requestId: string) => void;
}

interface UseChatResult {
  messages: ChatMessage[];
  availableModels: string[];
  selectedModel: string;
  isStreaming: boolean;
  errorMessage: string | null;
  isConnected: boolean;
  servitorPending: boolean;
  servitorResult: ServitorResult | null;
  currentRequestId: string | null;
  setSelectedModel: (model: string) => void;
  sendMessage: (text: string) => Promise<void>;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  dismissServitor: () => void;
  // Exposed so App.tsx audio queue can fire the handshake signal
  sendPlaybackComplete: (requestId: string) => void;
}

// =============================================================================
// WEBSOCKET CONFIG
// =============================================================================

const WEBSOCKET_URL = "ws://127.0.0.1:8080/ws/chat";
const RECONNECT_DELAY = 3000;

// =============================================================================
// HELPER
// =============================================================================

function createMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    createdAt: Date.now(),
  };
}

// =============================================================================
// HOOK
// =============================================================================

export function useChat({
  initialMessages = [],
  onAssistantMessageComplete,
  onServitorResult,
  onVerityAudio,
  onServitorAudio,
}: UseChatOptions = {}): UseChatResult {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [availableModels] = useState<string[]>(["verity-mistral-7b"]);
  const [selectedModel, setSelectedModel] = useState("verity-mistral-7b");
  const [isStreaming, setIsStreaming] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [servitorPending, setServitorPending] = useState(false);
  const [servitorResult, setServitorResult] = useState<ServitorResult | null>(null);

  // Tracks the request_id the backend stamped on the most recently accepted cycle.
  // Any incoming frame whose request_id doesn't match this is from a stale/cancelled cycle.
  const [currentRequestId, setCurrentRequestId] = useState<string | null>(null);
  const currentRequestIdRef = useRef<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const currentAssistantIdRef = useRef<string | null>(null);

  // Stable callback refs
  const onAssistantMessageCompleteRef = useRef(onAssistantMessageComplete);
  const onServitorResultRef = useRef(onServitorResult);
  const onVerityAudioRef = useRef(onVerityAudio);
  const onServitorAudioRef = useRef(onServitorAudio);

  useEffect(() => {
    onAssistantMessageCompleteRef.current = onAssistantMessageComplete;
    onServitorResultRef.current = onServitorResult;
    onVerityAudioRef.current = onVerityAudio;
    onServitorAudioRef.current = onServitorAudio;
  }, [onAssistantMessageComplete, onServitorResult, onVerityAudio, onServitorAudio]);

  // ---------------------------------------------------------------------------
  // sendPlaybackComplete — called by App.tsx audio queue after Verity audio ends
  // ---------------------------------------------------------------------------

  const sendPlaybackComplete = useCallback((requestId: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn("[Ash] sendPlaybackComplete: WebSocket not open, signal dropped");
      return;
    }
    // Only send if this requestId still matches the active cycle.
    // Guards against a delayed onended firing for a stale audio object.
    if (requestId !== currentRequestIdRef.current) {
      console.log(
        `[Ash] sendPlaybackComplete: stale requestId ${requestId} ignored (active: ${currentRequestIdRef.current})`
      );
      return;
    }
    console.log(`[Ash] Sending playback_complete for ${requestId}`);
    wsRef.current.send(
      JSON.stringify({ type: "playback_complete", request_id: requestId })
    );
  }, []);

  // ---------------------------------------------------------------------------
  // Message Handling
  // ---------------------------------------------------------------------------

  const handleMessage = useCallback(
    (data: {
      type: string;
      request_id?: string;
      content?: string;
      audio_data?: string;
      audio_format?: string;
      status?: "OPTIMAL" | "REVIEW" | "CRITICAL";
      confidence?: number;
      mortality_estimate?: number;
      risk_category?: string;
      deficiency?: string;
      amendment?: string;
      recommended_action?: string;
      source?: string;
      message?: string;
    }) => {
      const incomingId = data.request_id ?? null;

      // Ghost-frame guard: drop any frame from a cycle that's no longer active.
      // Exemptions: request_accepted sets the new active ID, errors always surface.
      if (
        incomingId !== null &&
        incomingId !== currentRequestIdRef.current &&
        data.type !== "request_accepted" &&
        data.type !== "error"
      ) {
        console.log(
          `[Ash] Ghost frame dropped — type: ${data.type}, id: ${incomingId} (active: ${currentRequestIdRef.current})`
        );
        return;
      }

      switch (data.type) {

        // Backend confirms it received the message and stamps the cycle ID
        case "request_accepted":
          if (incomingId) {
            currentRequestIdRef.current = incomingId;
            setCurrentRequestId(incomingId);
            console.log(`[Ash] New cycle accepted: ${incomingId}`);
          }
          break;

        case "verity_text":
          setIsStreaming(false);
          if (currentAssistantIdRef.current) {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === currentAssistantIdRef.current
                  ? { ...msg, content: data.content ?? "" }
                  : msg
              )
            );
            if (onAssistantMessageCompleteRef.current) {
              onAssistantMessageCompleteRef.current({
                id: currentAssistantIdRef.current,
                role: "assistant",
                content: data.content ?? "",
                createdAt: Date.now(),
              });
            }
          }
          break;

        case "verity_audio":
          // Pass requestId to the queue so it knows which ID to ack when done
          if (data.audio_data && onVerityAudioRef.current && incomingId) {
            onVerityAudioRef.current(data.audio_data, incomingId);
          }
          break;

        case "servitor_pending":
          setServitorPending(true);
          break;

        case "servitor_result": {
          setServitorPending(false);
          const result: ServitorResult = {
            status: data.status ?? "REVIEW",
            confidence: data.confidence ?? null,
            mortality_estimate: data.mortality_estimate ?? null,
            risk_category: data.risk_category ?? null,
            deficiency: data.deficiency ?? null,
            amendment: data.amendment ?? null,
            recommended_action: data.recommended_action ?? null,
            audio_data: data.audio_data,
            audio_format: data.audio_format,
          };
          setServitorResult(result);
          if (onServitorResultRef.current) {
            onServitorResultRef.current(result);
          }
          if (data.audio_data && onServitorAudioRef.current && incomingId) {
            onServitorAudioRef.current(data.audio_data, incomingId);
          }
          break;
        }

        case "servitor_optimal":
          setServitorPending(false);
          console.log("[Ash] Servitor: OPTIMAL — confidence:", data.confidence);
          break;

        case "error":
          console.error(`[Ash] Backend error from ${data.source}:`, data.message);
          setErrorMessage(`${data.source ?? "unknown"}: ${data.message ?? "Unknown error"}`);
          setIsStreaming(false);
          setServitorPending(false);
          break;

        default:
          console.log("[Ash] Unknown message type:", data.type);
      }
    },
    []
  );

  // ---------------------------------------------------------------------------
  // WebSocket Connection
  // ---------------------------------------------------------------------------

  useEffect(() => {
    let ws: WebSocket | null = null;

    const connect = () => {
      if (ws?.readyState === WebSocket.OPEN) return;

      console.log("[Ash] Connecting to WebSocket...");
      ws = new WebSocket(WEBSOCKET_URL);

      ws.onopen = () => {
        console.log("[Ash] WebSocket connected");
        setIsConnected(true);
        setErrorMessage(null);
      };

      ws.onclose = () => {
        console.log("[Ash] WebSocket disconnected");
        setIsConnected(false);
        reconnectTimeoutRef.current = window.setTimeout(() => {
          console.log("[Ash] Attempting reconnect...");
          connect();
        }, RECONNECT_DELAY);
      };

      ws.onerror = (error) => {
        console.error("[Ash] WebSocket error:", error);
        setErrorMessage("Connection to Ash backend failed");
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const data: unknown = JSON.parse(event.data as string);
          handleMessage(data as Parameters<typeof handleMessage>[0]);
        } catch (err) {
          console.error("[Ash] Failed to parse message:", err);
        }
      };

      wsRef.current = ws;
    };

    connect();

    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      ws?.close();
    };
  }, [handleMessage]);

  // ---------------------------------------------------------------------------
  // Send Message
  // ---------------------------------------------------------------------------

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmedText = text.trim();
      if (!trimmedText || isStreaming) return;

      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        setErrorMessage("Not connected to Ash backend");
        return;
      }

      setErrorMessage(null);
      setIsStreaming(true);
      setServitorResult(null);
      setServitorPending(false);

      // Clear the stale request ID immediately — the backend will stamp a new one
      // in its request_accepted frame before any audio frames arrive.
      currentRequestIdRef.current = null;
      setCurrentRequestId(null);

      const userMessage = createMessage("user", trimmedText);
      const assistantMessageId = crypto.randomUUID();
      currentAssistantIdRef.current = assistantMessageId;

      setMessages((prev) => [
        ...prev,
        userMessage,
        {
          id: assistantMessageId,
          role: "assistant",
          content: "",
          createdAt: Date.now(),
        },
      ]);

      wsRef.current.send(JSON.stringify({ message: trimmedText }));
    },
    [isStreaming]
  );

  // ---------------------------------------------------------------------------
  // Dismiss Servitor
  // ---------------------------------------------------------------------------

  const dismissServitor = useCallback(() => {
    setServitorResult(null);
    setServitorPending(false);
  }, []);

  return {
    messages,
    availableModels,
    selectedModel,
    isStreaming,
    errorMessage,
    isConnected,
    servitorPending,
    servitorResult,
    currentRequestId,
    setSelectedModel,
    sendMessage,
    setMessages,
    dismissServitor,
    sendPlaybackComplete,
  };
}