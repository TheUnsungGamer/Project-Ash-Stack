import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ChatMessage } from "../types/chat";

export interface ServitorAuditResult {
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
  onServitorAuditResult?: (result: ServitorAuditResult) => void;
  onVerityAudioReady?: (audioBase64: string, requestId: string) => void;
  onServitorAudioReady?: (audioBase64: string, requestId: string) => void;
}

interface UseChatResult {
  messages: ChatMessage[];
  availableModels: string[];
  selectedModel: string;
  isStreaming: boolean;
  errorMessage: string | null;
  isConnected: boolean;
  servitorAuditPending: boolean;
  servitorAuditResult: ServitorAuditResult | null;
  currentRequestId: string | null;
  setSelectedModel: (model: string) => void;
  sendMessage: (text: string) => Promise<void>;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  dismissServitorPanel: () => void;
  sendVerityPlaybackComplete: (requestId: string) => void;
}

type IncomingWebSocketFrame = {
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
};

const ASH_WEBSOCKET_URL = "ws://127.0.0.1:8080/ws/chat";
const WEBSOCKET_RECONNECT_DELAY_MS = 3_000;

// These frame types either set the active request ID or must always surface to the user.
const FRAME_TYPES_EXEMPT_FROM_STALE_CYCLE_GUARD = new Set([
  "request_accepted",
  "verity_text",
  "verity_audio",
  "error",
]);

function buildChatMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    createdAt: Date.now(),
  };
}

export function useChat({
  initialMessages = [],
  onAssistantMessageComplete,
  onServitorAuditResult,
  onVerityAudioReady,
  onServitorAudioReady,
}: UseChatOptions = {}): UseChatResult {
  const [messages, setMessages]                         = useState<ChatMessage[]>(initialMessages);
  const [availableModels]                               = useState<string[]>(["verity-mistral-7b"]);
  const [selectedModel, setSelectedModel]               = useState("verity-mistral-7b");
  const [isStreaming, setIsStreaming]                   = useState(false);
  const [errorMessage, setErrorMessage]                 = useState<string | null>(null);
  const [isConnected, setIsConnected]                   = useState(false);
  const [servitorAuditPending, setServitorAuditPending] = useState(false);
  const [servitorAuditResult, setServitorAuditResult]   = useState<ServitorAuditResult | null>(null);
  const [currentRequestId, setCurrentRequestId]         = useState<string | null>(null);

  // Ref-backed so stale closures in WebSocket handlers always see the latest value.
  const currentRequestIdRef      = useRef<string | null>(null);
  const currentAssistantIdRef    = useRef<string | null>(null);
  const wsRef                    = useRef<WebSocket | null>(null);
  const reconnectTimerRef        = useRef<number | null>(null);

  // Stable callback refs — prevents WebSocket handler from closing over stale callbacks.
  const onAssistantMessageCompleteRef = useRef(onAssistantMessageComplete);
  const onServitorAuditResultRef      = useRef(onServitorAuditResult);
  const onVerityAudioReadyRef         = useRef(onVerityAudioReady);
  const onServitorAudioReadyRef       = useRef(onServitorAudioReady);

  useEffect(() => {
    onAssistantMessageCompleteRef.current = onAssistantMessageComplete;
    onServitorAuditResultRef.current      = onServitorAuditResult;
    onVerityAudioReadyRef.current         = onVerityAudioReady;
    onServitorAudioReadyRef.current       = onServitorAudioReady;
  }, [onAssistantMessageComplete, onServitorAuditResult, onVerityAudioReady, onServitorAudioReady]);

  const sendVerityPlaybackComplete = useCallback((requestId: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn("[Ash] sendVerityPlaybackComplete: WebSocket not open, signal dropped");
      return;
    }
    // Guard against a delayed onended firing for a previous cycle's audio element.
    if (requestId !== currentRequestIdRef.current) {
      console.log(`[Ash] Stale playback_complete dropped — id: ${requestId} (active: ${currentRequestIdRef.current})`);
      return;
    }
    wsRef.current.send(JSON.stringify({ type: "playback_complete", request_id: requestId }));
  }, []);

  const handleIncomingWebSocketFrame = useCallback((frame: IncomingWebSocketFrame) => {
    const incomingRequestId = frame.request_id ?? null;

    // Drop frames from cancelled/stale cycles, with exemptions for frames that
    // race request_accepted or must always surface.
    if (
      incomingRequestId !== null &&
      incomingRequestId !== currentRequestIdRef.current &&
      !FRAME_TYPES_EXEMPT_FROM_STALE_CYCLE_GUARD.has(frame.type)
    ) {
      console.log(`[Ash] Stale frame dropped — type: ${frame.type}, id: ${incomingRequestId}`);
      return;
    }

    switch (frame.type) {
      case "request_accepted":
        if (incomingRequestId) {
          currentRequestIdRef.current = incomingRequestId;
          setCurrentRequestId(incomingRequestId);
        }
        break;

      case "verity_text":
        setIsStreaming(false);
        if (currentAssistantIdRef.current) {
          const completedMessage: ChatMessage = {
            id: currentAssistantIdRef.current,
            role: "assistant",
            content: frame.content ?? "",
            createdAt: Date.now(),
          };
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === currentAssistantIdRef.current
                ? { ...msg, content: frame.content ?? "" }
                : msg
            )
          );
          onAssistantMessageCompleteRef.current?.(completedMessage);
        }
        break;

      case "verity_audio":
        if (frame.audio_data && incomingRequestId) {
          onVerityAudioReadyRef.current?.(frame.audio_data, incomingRequestId);
        }
        break;

      case "servitor_pending":
        setServitorAuditPending(true);
        break;

      case "servitor_result": {
        setServitorAuditPending(false);
        const result: ServitorAuditResult = {
          status:              frame.status ?? "REVIEW",
          confidence:          frame.confidence ?? null,
          mortality_estimate:  frame.mortality_estimate ?? null,
          risk_category:       frame.risk_category ?? null,
          deficiency:          frame.deficiency ?? null,
          amendment:           frame.amendment ?? null,
          recommended_action:  frame.recommended_action ?? null,
          audio_data:          frame.audio_data,
          audio_format:        frame.audio_format,
        };
        setServitorAuditResult(result);
        onServitorAuditResultRef.current?.(result);
        if (frame.audio_data && incomingRequestId) {
          onServitorAudioReadyRef.current?.(frame.audio_data, incomingRequestId);
        }
        break;
      }

      case "servitor_optimal":
        setServitorAuditPending(false);
        break;

      case "error":
        setErrorMessage(`${frame.source ?? "unknown"}: ${frame.message ?? "Unknown error"}`);
        setIsStreaming(false);
        setServitorAuditPending(false);
        break;

      default:
        console.log("[Ash] Unknown frame type:", frame.type);
    }
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;

    const connectToAshBackend = () => {
      if (ws?.readyState === WebSocket.OPEN) return;

      ws = new WebSocket(ASH_WEBSOCKET_URL);

      ws.onopen = () => {
        setIsConnected(true);
        setErrorMessage(null);
      };

      ws.onclose = () => {
        setIsConnected(false);
        reconnectTimerRef.current = window.setTimeout(connectToAshBackend, WEBSOCKET_RECONNECT_DELAY_MS);
      };

      ws.onerror = () => {
        setErrorMessage("Connection to Ash backend failed");
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          handleIncomingWebSocketFrame(JSON.parse(event.data as string) as IncomingWebSocketFrame);
        } catch (err) {
          console.error("[Ash] Failed to parse WebSocket frame:", err);
        }
      };

      wsRef.current = ws;
    };

    connectToAshBackend();

    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      ws?.close();
    };
  }, [handleIncomingWebSocketFrame]);

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
      setServitorAuditResult(null);
      setServitorAuditPending(false);

      currentRequestIdRef.current = null;
      setCurrentRequestId(null);

      const userMessage       = buildChatMessage("user", trimmedText);
      const assistantPlaceholderId = crypto.randomUUID();
      currentAssistantIdRef.current = assistantPlaceholderId;

      setMessages((prev) => [
        ...prev,
        userMessage,
        { id: assistantPlaceholderId, role: "assistant", content: "", createdAt: Date.now() },
      ]);

      wsRef.current.send(JSON.stringify({ message: trimmedText }));
    },
    [isStreaming]
  );

  const dismissServitorPanel = useCallback(() => {
    setServitorAuditResult(null);
    setServitorAuditPending(false);
  }, []);

  return {
    messages,
    availableModels,
    selectedModel,
    isStreaming,
    errorMessage,
    isConnected,
    servitorAuditPending,
    servitorAuditResult,
    currentRequestId,
    setSelectedModel,
    sendMessage,
    setMessages,
    dismissServitorPanel,
    sendVerityPlaybackComplete,
  };
}