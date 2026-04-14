import { useState, useRef, useEffect } from "react";
import "./styles/global.css";
import { initialLogs } from "./constants/initialLogs";
import ServitorPanel from './components/ServitorPanel.tsx';
import { useAudioController } from "./hooks/useAudioController";
import { useChat } from "./hooks/useChat";
import { starterMessages } from "./constants/starterMessages";
import { AppShell } from "./components/layout/AppShell";
import { MainPanel } from "./components/layout/MainPanel";
import { AppHeader } from "./components/layout/AppHeader";
import { ChatSection } from "./components/chat/ChatSection";
import { StatusStrip } from "./components/layout/StatusStrip";
import { Sidebar } from "./components/controls/Sidebar";

// How long to wait after audio starts before force-releasing the handshake.
// Covers: onended never fires, audio decode failure, browser autoplay block.
// Set conservatively high — Verity responses can be long.
const PLAYBACK_COMPLETE_TIMEOUT_MS = 45_000;

export default function App() {
  const [draftMessage, setDraftMessage] = useState("");
  const [logs, setLogs] = useState<string[]>(initialLogs);

  const audioController = useAudioController();

  // Audio queue entries now carry the requestId so we know which cycle to ack
  interface QueueEntry {
    audioData: string;
    source: string;
    requestId: string;
  }

  const audioQueueRef   = useRef<QueueEntry[]>([]);
  const isPlayingRef    = useRef(false);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);

  // Ref to the force-release timer for the currently playing audio item
  const forceReleaseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // We need sendPlaybackComplete before useChat is called — forward-declared via ref
  // so playNextInQueue can call it without a stale closure.
  const sendPlaybackCompleteRef = useRef<((id: string) => void) | null>(null);

  function pushLog(logLine: string) {
    setLogs((prev) => [...prev.slice(-19), logLine]);
  }

  function clearForceReleaseTimer() {
    if (forceReleaseTimerRef.current !== null) {
      clearTimeout(forceReleaseTimerRef.current);
      forceReleaseTimerRef.current = null;
    }
  }

  // Pause before Servitor speaks — lets Verity's words land before the interrupt
  const SERVITOR_INTRO_PAUSE_MS = 1800;

  function playNextInQueue() {
    clearForceReleaseTimer();

    if (audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      currentAudioRef.current = null;
      return;
    }

    const entry = audioQueueRef.current[0]!;

    // If the next item is Servitor audio, hold briefly before playing.
    // This gives the operator a beat of silence after Verity finishes — the
    // "Prime Directive override" line hits harder after a pause.
    if (entry.source === "Servitor") {
      setTimeout(() => {
        if (audioQueueRef.current.length === 0) return; // cancelled in the gap
        playItem(audioQueueRef.current.shift()!);
      }, SERVITOR_INTRO_PAUSE_MS);
      return;
    }

    playItem(audioQueueRef.current.shift()!);
  }

  function playItem(entry: QueueEntry) {
    isPlayingRef.current = true;
    const { audioData, source, requestId } = entry;

    const audio = new Audio(`data:audio/wav;base64,${audioData}`);
    currentAudioRef.current = audio;

    // -------------------------------------------------------------------------
    // STATE-LOCKED HANDSHAKE: send playback_complete when Verity audio ends.
    // Only Verity audio gates the Servitor — Servitor audio is purely informational.
    // -------------------------------------------------------------------------
    const onFinished = () => {
      clearForceReleaseTimer();
      currentAudioRef.current = null;

      if (source === "Verity") {
        pushLog(`[AUD] Verity playback complete — releasing Servitor gate (${requestId.slice(0, 8)}…)`);
        sendPlaybackCompleteRef.current?.(requestId);
      }

      playNextInQueue();
    };

    audio.onended = onFinished;

    audio.onerror = () => {
      pushLog(`[ERR] ${source} audio decode failed — force-releasing gate`);
      clearForceReleaseTimer();
      currentAudioRef.current = null;

      if (source === "Verity") {
        // Audio failed to load — backend must not hang
        sendPlaybackCompleteRef.current?.(requestId);
      }

      playNextInQueue();
    };

    audio.play().catch(() => {
      // Browser blocked autoplay or some other play() rejection
      pushLog(`[ERR] ${source} play() rejected — force-releasing gate`);
      clearForceReleaseTimer();
      currentAudioRef.current = null;

      if (source === "Verity") {
        sendPlaybackCompleteRef.current?.(requestId);
      }

      playNextInQueue();
    });

    // -------------------------------------------------------------------------
    // FORCE-RELEASE FALLBACK TIMER
    // If onended never fires (e.g. browser quirk, silent hang), release after
    // PLAYBACK_COMPLETE_TIMEOUT_MS regardless.
    // -------------------------------------------------------------------------
    if (source === "Verity") {
      forceReleaseTimerRef.current = setTimeout(() => {
        pushLog(`[WARN] Verity audio onended timeout — force-releasing Servitor gate`);
        currentAudioRef.current?.pause();
        currentAudioRef.current = null;
        sendPlaybackCompleteRef.current?.(requestId);
        playNextInQueue();
      }, PLAYBACK_COMPLETE_TIMEOUT_MS);
    }
  }

  function queueAudio(audioData: string, source: string, requestId: string) {
    pushLog(`[AUD] Queued ${source} audio (${requestId.slice(0, 8)}…)`);
    audioQueueRef.current.push({ audioData, source, requestId });
    if (!isPlayingRef.current) {
      playNextInQueue();
    }
  }

  const {
    messages,
    availableModels,
    selectedModel,
    isStreaming,
    errorMessage,
    setSelectedModel,
    sendMessage,
    servitorResult,
    servitorPending,
    dismissServitor,
    sendPlaybackComplete,
  } = useChat({
    initialMessages: starterMessages,
    onAssistantMessageComplete: (message) => {
      pushLog("[LLM] Response complete");
      // audioController.speak() removed — verity_audio WebSocket frame is the
      // single source of truth for playback. Calling speak() here caused Verity
      // to hit the TTS server independently, duplicating audio every response.
    },
    // requestId is now passed through so the queue can ack the right cycle
    onVerityAudio: (audioData, requestId) => {
      queueAudio(audioData, "Verity", requestId);
    },
    onServitorAudio: (audioData, requestId) => {
      queueAudio(audioData, "Servitor", requestId);
    },
  });

  // Wire the stable ref so playNextInQueue can always reach the latest function.
  // Must live in useEffect — React forbids mutating refs during render.
  useEffect(() => {
    sendPlaybackCompleteRef.current = sendPlaybackComplete;
  }, [sendPlaybackComplete]);

  async function handleCopyMessage(messageContent: string) {
    try {
      await navigator.clipboard.writeText(messageContent);
      pushLog("[UI ] Message copied to clipboard");
    } catch {
      pushLog("[ERR] Clipboard write failed");
    }
  }

  async function handleSpeakMessage(messageContent: string, messageId: string) {
    await audioController.speak(messageContent, messageId);
  }

  async function handleSubmit() {
    const trimmedMessage = draftMessage.trim();
    if (!trimmedMessage) return;

    // Cancel any in-flight audio immediately when the user sends a new message.
    // The backend will cancel its own task; we mirror that on the frontend.
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    clearForceReleaseTimer();
    audioQueueRef.current = [];
    isPlayingRef.current = false;

    pushLog(`[USR] ${trimmedMessage.slice(0, 48)}`);
    await sendMessage(trimmedMessage);
    setDraftMessage("");
  }

  return (
    <AppShell>
      <AppHeader
        title="Ash UI Rebuild"
        subtitle="Modular chat test shell"
      />

      <StatusStrip
        selectedModel={selectedModel}
        audioStatus={audioController.audioState.status}
        voiceMode={audioController.audioState.voiceMode}
      />

      <MainPanel>
        <Sidebar
          availableModels={availableModels}
          selectedModel={selectedModel}
          isStreaming={isStreaming}
          errorMessage={errorMessage ?? undefined}
          logs={logs}
          audioState={audioController.audioState}
          onSelectModel={setSelectedModel}
          onToggleVoice={audioController.toggleVoice}
          onToggleMode={audioController.toggleMode}
          onPauseAudio={audioController.pause}
          onResumeAudio={audioController.resume}
          onStopAudio={audioController.stop}
          messageCount={messages.length}
        />

        <ChatSection
          messages={messages}
          isStreaming={isStreaming}
          draftMessage={draftMessage}
          onDraftChange={setDraftMessage}
          onSubmit={handleSubmit}
          onCopyMessage={(message) => void handleCopyMessage(message.content)}
          onSpeakMessage={(message) =>
            void handleSpeakMessage(message.content, message.id)
          }
        />

        <ServitorPanel
          result={servitorResult}
          isVisible={servitorResult !== null || servitorPending}
          isPending={servitorPending}
          onDismiss={dismissServitor}
        />
      </MainPanel>
    </AppShell>
  );
}