import { useState, useRef } from "react";
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

export default function App() {
  const [draftMessage, setDraftMessage] = useState("");
  const [logs, setLogs] = useState<string[]>(initialLogs);

  const audioController = useAudioController();

  // Audio queue system - Verity plays first, Servitor waits
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef(false);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);

  function pushLog(logLine: string) {
    setLogs((prev) => [...prev.slice(-19), logLine]);
  }

  function playNextInQueue() {
    if (audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      currentAudioRef.current = null;
      return;
    }

    isPlayingRef.current = true;
    const audioData = audioQueueRef.current.shift()!;
    const audio = new Audio(`data:audio/wav;base64,${audioData}`);
    currentAudioRef.current = audio;
    
    audio.onended = () => {
      currentAudioRef.current = null;
      playNextInQueue();
    };
    
    audio.onerror = () => {
      currentAudioRef.current = null;
      playNextInQueue();
    };
    
    audio.play().catch(() => {
      playNextInQueue();
    });
  }

  function queueAudio(audioData: string, source: string) {
    pushLog(`[AUD] Queued ${source} audio`);
    audioQueueRef.current.push(audioData);
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
  } = useChat({
    initialMessages: starterMessages,
    onAssistantMessageComplete: async (message) => {
      pushLog("[LLM] Response complete");
      await audioController.speak(message.content, message.id);
    },
    onVerityAudio: (audioData) => {
      queueAudio(audioData, "Verity");
    },
    onServitorAudio: (audioData) => {
      queueAudio(audioData, "Servitor");
    },
  });

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

    if (!trimmedMessage) {
      return;
    }

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
