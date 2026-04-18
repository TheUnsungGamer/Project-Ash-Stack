import { useCallback, useEffect, useRef, useState } from "react";
import type { AudioController, AudioState, VoiceMode } from "../types/audio";

const ASH_TTS_SERVER_URL = "http://127.0.0.1:8000/tts";

const INITIAL_AUDIO_STATE: AudioState = {
  status: "idle",
  activeText: null,
  activeMessageId: null,
  isVoiceEnabled: true,
  voiceMode: "tech_priest",
  errorMessage: null,
};

function findPreferredEnglishBrowserVoice(): SpeechSynthesisVoice | null {
  if (!("speechSynthesis" in window)) return null;
  const voices = window.speechSynthesis.getVoices();
  if (voices.length === 0) return null;
  return (
    voices.find((v) => v.lang?.toLowerCase().includes("en-us")) ??
    voices.find((v) => v.lang?.toLowerCase().startsWith("en")) ??
    voices[0] ??
    null
  );
}

export function useAudioController(): AudioController {
  const [audioState, setAudioState] = useState<AudioState>(INITIAL_AUDIO_STATE);

  const speechUtteranceRef   = useRef<SpeechSynthesisUtterance | null>(null);
  const htmlAudioElementRef  = useRef<HTMLAudioElement | null>(null);
  const activeObjectUrlRef   = useRef<string | null>(null);
  const browserVoicesLoadedRef = useRef(false);

  const revokeActiveObjectUrl = useCallback(() => {
    if (activeObjectUrlRef.current) {
      URL.revokeObjectURL(activeObjectUrlRef.current);
      activeObjectUrlRef.current = null;
    }
  }, []);

  const stopAndClearHtmlAudioElement = useCallback(() => {
    if (htmlAudioElementRef.current) {
      htmlAudioElementRef.current.pause();
      htmlAudioElementRef.current.src = "";
      htmlAudioElementRef.current = null;
    }
    revokeActiveObjectUrl();
  }, [revokeActiveObjectUrl]);

  const stopBrowserSpeechSynthesis = useCallback(() => {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    speechUtteranceRef.current = null;
  }, []);

  const interrupt = useCallback(() => {
    stopBrowserSpeechSynthesis();
    stopAndClearHtmlAudioElement();
    setAudioState((prev) => ({
      ...prev,
      status: "interrupted",
      activeText: null,
      activeMessageId: null,
      errorMessage: null,
    }));
  }, [stopAndClearHtmlAudioElement, stopBrowserSpeechSynthesis]);

  const stop = useCallback(() => {
    stopBrowserSpeechSynthesis();
    stopAndClearHtmlAudioElement();
    setAudioState((prev) => ({
      ...prev,
      status: "stopped",
      activeText: null,
      activeMessageId: null,
      errorMessage: null,
    }));
  }, [stopAndClearHtmlAudioElement, stopBrowserSpeechSynthesis]);

  const pause = useCallback(() => {
    try {
      if (audioState.voiceMode === "normal") {
        if ("speechSynthesis" in window && window.speechSynthesis.speaking) {
          window.speechSynthesis.pause();
        }
      } else {
        htmlAudioElementRef.current?.pause();
      }
      setAudioState((prev) => ({ ...prev, status: "paused" }));
    } catch (error) {
      setAudioState((prev) => ({
        ...prev,
        status: "error",
        errorMessage: error instanceof Error ? error.message : "Failed to pause audio.",
      }));
    }
  }, [audioState.voiceMode]);

  const resume = useCallback(() => {
    try {
      if (audioState.voiceMode === "normal") {
        if ("speechSynthesis" in window) window.speechSynthesis.resume();
      } else {
        void htmlAudioElementRef.current?.play();
      }
      setAudioState((prev) => ({ ...prev, status: "playing", errorMessage: null }));
    } catch (error) {
      setAudioState((prev) => ({
        ...prev,
        status: "error",
        errorMessage: error instanceof Error ? error.message : "Failed to resume audio.",
      }));
    }
  }, [audioState.voiceMode]);

  const speakWithBrowserSpeechSynthesis = useCallback(
    async (text: string, messageId?: string) => {
      if (!("speechSynthesis" in window)) {
        throw new Error("Browser speech synthesis not supported.");
      }
      stopBrowserSpeechSynthesis();
      stopAndClearHtmlAudioElement();

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1;
      utterance.lang = "en-US";

      const preferredVoice = findPreferredEnglishBrowserVoice();
      if (preferredVoice) utterance.voice = preferredVoice;

      speechUtteranceRef.current = utterance;

      await new Promise<void>((resolve, reject) => {
        utterance.onstart = () =>
          setAudioState((prev) => ({
            ...prev,
            status: "playing",
            activeText: text,
            activeMessageId: messageId ?? null,
            errorMessage: null,
          }));

        utterance.onend = () => {
          speechUtteranceRef.current = null;
          setAudioState((prev) => ({
            ...prev,
            status: "idle",
            activeText: null,
            activeMessageId: null,
            errorMessage: null,
          }));
          resolve();
        };

        utterance.onerror = (event) => {
          speechUtteranceRef.current = null;
          setAudioState((prev) => ({
            ...prev,
            status: "error",
            activeText: null,
            activeMessageId: null,
            errorMessage: event.error || "Browser speech failed.",
          }));
          reject(new Error(event.error || "Browser speech failed."));
        };

        window.speechSynthesis.speak(utterance);
      });
    },
    [stopAndClearHtmlAudioElement, stopBrowserSpeechSynthesis]
  );

  const speakWithAshTtsServer = useCallback(
    async (text: string, messageId?: string) => {
      try {
        stopBrowserSpeechSynthesis();
        stopAndClearHtmlAudioElement();

        setAudioState((prev) => ({
          ...prev,
          status: "playing",
          activeText: text,
          activeMessageId: messageId ?? null,
          errorMessage: null,
        }));

        const response = await fetch(ASH_TTS_SERVER_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });

        // Silent 500 — don't crash the UI, just bail.
        if (!response.ok) return;

        const audioBlob = await response.blob();
        const objectUrl = URL.createObjectURL(audioBlob);
        activeObjectUrlRef.current = objectUrl;

        if (htmlAudioElementRef.current) htmlAudioElementRef.current.pause();

        const audioElement = new Audio(objectUrl);
        htmlAudioElementRef.current = audioElement;

        await new Promise<void>((resolve, reject) => {
          audioElement.onended = () => {
            stopAndClearHtmlAudioElement();
            setAudioState((prev) => ({
              ...prev,
              status: "idle",
              activeText: null,
              activeMessageId: null,
              errorMessage: null,
            }));
            resolve();
          };
          audioElement.onerror = () => {
            stopAndClearHtmlAudioElement();
            reject(new Error("TTS audio playback failed."));
          };
          void audioElement.play().catch(reject);
        });
      } catch {
        // Swallow — TTS failure must not break the chat flow.
      }
    },
    [stopAndClearHtmlAudioElement, stopBrowserSpeechSynthesis]
  );

  const speak = useCallback(
    async (text: string, messageId?: string) => {
      const trimmedText = text.trim();
      if (!audioState.isVoiceEnabled || trimmedText.length === 0) return;

      interrupt();
      setAudioState((prev) => ({
        ...prev,
        status: "playing",
        activeText: trimmedText,
        activeMessageId: messageId ?? null,
        errorMessage: null,
      }));

      try {
        if (audioState.voiceMode === "normal") {
          await speakWithBrowserSpeechSynthesis(trimmedText, messageId);
        } else {
          await speakWithAshTtsServer(trimmedText, messageId);
        }
      } catch (error) {
        setAudioState((prev) => ({
          ...prev,
          status: "error",
          activeText: null,
          activeMessageId: null,
          errorMessage: error instanceof Error ? error.message : "Audio playback failed.",
        }));
      }
    },
    [
      audioState.isVoiceEnabled,
      audioState.voiceMode,
      interrupt,
      speakWithBrowserSpeechSynthesis,
      speakWithAshTtsServer,
    ]
  );

  const toggleVoice = useCallback(() => {
    setAudioState((prev) => {
      const voiceWillBeEnabled = !prev.isVoiceEnabled;
      if (!voiceWillBeEnabled) {
        stopBrowserSpeechSynthesis();
        stopAndClearHtmlAudioElement();
      }
      return {
        ...prev,
        isVoiceEnabled: voiceWillBeEnabled,
        status: voiceWillBeEnabled ? prev.status : "stopped",
        activeText: voiceWillBeEnabled ? prev.activeText : null,
        activeMessageId: voiceWillBeEnabled ? prev.activeMessageId : null,
        errorMessage: null,
      };
    });
  }, [stopAndClearHtmlAudioElement, stopBrowserSpeechSynthesis]);

  const toggleMode = useCallback(() => {
    setAudioState((prev) => {
      const nextMode: VoiceMode = prev.voiceMode === "normal" ? "tech_priest" : "normal";
      stopBrowserSpeechSynthesis();
      stopAndClearHtmlAudioElement();
      return {
        ...prev,
        voiceMode: nextMode,
        status: "stopped",
        activeText: null,
        activeMessageId: null,
        errorMessage: null,
      };
    });
  }, [stopAndClearHtmlAudioElement, stopBrowserSpeechSynthesis]);

  // Warm up the browser's voice list on mount.
  useEffect(() => {
    if (!("speechSynthesis" in window) || browserVoicesLoadedRef.current) return;
    const onVoicesChanged = () => {
      browserVoicesLoadedRef.current = true;
      window.speechSynthesis.getVoices();
    };
    window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener("voiceschanged", onVoicesChanged);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", onVoicesChanged);
  }, []);

  useEffect(() => {
    return () => {
      stopBrowserSpeechSynthesis();
      stopAndClearHtmlAudioElement();
    };
  }, [stopAndClearHtmlAudioElement, stopBrowserSpeechSynthesis]);

  return { audioState, speak, pause, resume, stop, interrupt, toggleVoice, toggleMode };
}