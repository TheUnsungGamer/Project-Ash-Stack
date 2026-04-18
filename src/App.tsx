import { useState, useRef, useEffect } from "react";
import "./styles/global.css";
import { initialLogs } from "./constants/initialLogs";
import { starterMessages } from "./constants/starterMessages";
import { useAudioController } from "./hooks/useAudioController";
import { useAudioQueue } from "./hooks/useAudioQueue";
import { useChat } from "./hooks/useChat";
import { AppShell } from "./components/layout/AppShell";
import { AppHeader } from "./components/layout/AppHeader";
import { MainPanel } from "./components/layout/MainPanel";
import { StatusStrip } from "./components/layout/StatusStrip";
import { Sidebar } from "./components/controls/Sidebar";
import { ChatSection } from "./components/chat/ChatSection";
import ServitorPanel from "./components/ServitorPanel";

export default function App() {
  const [draftMessage, setDraftMessage] = useState("");
  const [systemLogs, setSystemLogs]     = useState<string[]>(initialLogs);

  // sendVerityPlaybackComplete is set after useChat initialises — forward-declared
  // so useAudioQueue can call it without a stale closure.
  const sendVerityPlaybackCompleteRef = useRef<((id: string) => void) | null>(null);

  function appendToSystemLog(logLine: string) {
    setSystemLogs((prev) => [...prev.slice(-19), logLine]);
  }

  const { enqueueAudio, cancelAllQueuedAudio } = useAudioQueue({
    onVerityPlaybackComplete: (requestId) => {
      sendVerityPlaybackCompleteRef.current?.(requestId);
    },
    onLogMessage: appendToSystemLog,
  });

  const audioController = useAudioController();

  const {
    messages,
    availableModels,
    selectedModel,
    isStreaming,
    errorMessage,
    setSelectedModel,
    sendMessage,
    servitorAuditResult,
    servitorAuditPending,
    dismissServitorPanel,
    sendVerityPlaybackComplete,
  } = useChat({
    initialMessages: starterMessages,
    onAssistantMessageComplete: () => {
      appendToSystemLog("[LLM] Response complete");
    },
    onVerityAudioReady: (audioBase64, requestId) => {
      enqueueAudio(audioBase64, "Verity", requestId);
    },
    onServitorAudioReady: (audioBase64, requestId) => {
      enqueueAudio(audioBase64, "Servitor", requestId);
    },
  });

  useEffect(() => {
    sendVerityPlaybackCompleteRef.current = sendVerityPlaybackComplete;
  }, [sendVerityPlaybackComplete]);

  async function handleSubmitUserMessage() {
    const trimmedMessage = draftMessage.trim();
    if (!trimmedMessage) return;

    cancelAllQueuedAudio();
    appendToSystemLog(`[USR] ${trimmedMessage.slice(0, 48)}`);
    await sendMessage(trimmedMessage);
    setDraftMessage("");
  }

  async function handleCopyMessageToClipboard(messageContent: string) {
    try {
      await navigator.clipboard.writeText(messageContent);
      appendToSystemLog("[UI ] Message copied to clipboard");
    } catch {
      appendToSystemLog("[ERR] Clipboard write failed");
    }
  }

  async function handleSpeakMessageAloud(messageContent: string, messageId: string) {
    await audioController.speak(messageContent, messageId);
  }

  return (
    <AppShell>
      <AppHeader
        title="Project Ash"
        subtitle="Tactical Cogitator Interface"
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
          logs={systemLogs}
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
          onSubmit={handleSubmitUserMessage}
          onCopyMessage={(message) => void handleCopyMessageToClipboard(message.content)}
          onSpeakMessage={(message) => void handleSpeakMessageAloud(message.content, message.id)}
        />

        <ServitorPanel
          result={servitorAuditResult}
          isVisible={servitorAuditResult !== null || servitorAuditPending}
          isPending={servitorAuditPending}
          onDismiss={dismissServitorPanel}
        />
      </MainPanel>
    </AppShell>
  );
}