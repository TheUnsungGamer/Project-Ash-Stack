import { useRef } from "react";

interface AudioQueueEntry {
  audioBase64: string;
  sourceName: "Verity" | "Servitor";
  requestId: string;
}

interface UseAudioQueueOptions {
  onVerityPlaybackComplete: (requestId: string) => void;
  onLogMessage: (logLine: string) => void;
}

// If onended never fires (browser quirk / silent hang), force-release
// the Servitor gate after this many milliseconds.
const VERITY_PLAYBACK_FORCE_RELEASE_TIMEOUT_MS = 45_000;

// Brief silence between Verity finishing and Servitor speaking —
// lets the operator absorb Verity's words before the audit interrupt.
const SERVITOR_INTRO_PAUSE_MS = 1_800;

export function useAudioQueue({ onVerityPlaybackComplete, onLogMessage }: UseAudioQueueOptions): {
  enqueueAudio: (audioBase64: string, sourceName: "Verity" | "Servitor", requestId: string) => void;
  cancelAllQueuedAudio: () => void;
} {
  const queueRef             = useRef<AudioQueueEntry[]>([]);
  const isPlayingRef         = useRef(false);
  const activeAudioRef       = useRef<HTMLAudioElement | null>(null);
  const forceReleaseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function clearForceReleaseTimer() {
    if (forceReleaseTimerRef.current !== null) {
      clearTimeout(forceReleaseTimerRef.current);
      forceReleaseTimerRef.current = null;
    }
  }

  function playNextEntryInQueue() {
    clearForceReleaseTimer();

    if (queueRef.current.length === 0) {
      isPlayingRef.current   = false;
      activeAudioRef.current = null;
      return;
    }

    const nextEntry = queueRef.current[0]!;

    if (nextEntry.sourceName === "Servitor") {
      setTimeout(() => {
        if (queueRef.current.length === 0) return;
        playAudioEntry(queueRef.current.shift()!);
      }, SERVITOR_INTRO_PAUSE_MS);
      return;
    }

    playAudioEntry(queueRef.current.shift()!);
  }

  function playAudioEntry(entry: AudioQueueEntry) {
    isPlayingRef.current = true;
    const { audioBase64, sourceName, requestId } = entry;

    const audioElement = new Audio(`data:audio/wav;base64,${audioBase64}`);
    activeAudioRef.current = audioElement;

    const onPlaybackFinished = () => {
      clearForceReleaseTimer();
      activeAudioRef.current = null;

      if (sourceName === "Verity") {
        onLogMessage(`[AUD] Verity playback complete — releasing Servitor gate (${requestId.slice(0, 8)}…)`);
        onVerityPlaybackComplete(requestId);
      }

      playNextEntryInQueue();
    };

    audioElement.onended = onPlaybackFinished;

    audioElement.onerror = () => {
      onLogMessage(`[ERR] ${sourceName} audio decode failed — force-releasing gate`);
      clearForceReleaseTimer();
      activeAudioRef.current = null;
      if (sourceName === "Verity") onVerityPlaybackComplete(requestId);
      playNextEntryInQueue();
    };

    audioElement.play().catch(() => {
      onLogMessage(`[ERR] ${sourceName} play() rejected — force-releasing gate`);
      clearForceReleaseTimer();
      activeAudioRef.current = null;
      if (sourceName === "Verity") onVerityPlaybackComplete(requestId);
      playNextEntryInQueue();
    });

    if (sourceName === "Verity") {
      forceReleaseTimerRef.current = setTimeout(() => {
        onLogMessage(`[WARN] Verity audio onended timeout — force-releasing Servitor gate`);
        activeAudioRef.current?.pause();
        activeAudioRef.current = null;
        onVerityPlaybackComplete(requestId);
        playNextEntryInQueue();
      }, VERITY_PLAYBACK_FORCE_RELEASE_TIMEOUT_MS);
    }
  }

  function enqueueAudio(audioBase64: string, sourceName: "Verity" | "Servitor", requestId: string) {
    onLogMessage(`[AUD] Queued ${sourceName} audio (${requestId.slice(0, 8)}…)`);
    queueRef.current.push({ audioBase64, sourceName, requestId });
    if (!isPlayingRef.current) {
      playNextEntryInQueue();
    }
  }

  function cancelAllQueuedAudio() {
    if (activeAudioRef.current) {
      activeAudioRef.current.pause();
      activeAudioRef.current = null;
    }
    clearForceReleaseTimer();
    queueRef.current   = [];
    isPlayingRef.current = false;
  }

  return { enqueueAudio, cancelAllQueuedAudio };
}