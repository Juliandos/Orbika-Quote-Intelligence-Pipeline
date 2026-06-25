"use client";

import { useEffect, useRef } from "react";
import { apiBase } from "./api";

type Handlers = {
  onDashboard?: () => void;
  onTasks?: () => void;
  onQuoteNew?: (payload: any) => void;
  onLog?: (payload: any) => void;
  onTaskStarted?: (payload: any) => void;
  onTaskCompleted?: (payload: any) => void;
  onTaskFailed?: (payload: any) => void;
};

function playBeep(kind: "success" | "error" | "info" = "info") {
  try {
    const context = new window.AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const secondOscillator = context.createOscillator();
    const secondGain = context.createGain();

    oscillator.type = "sine";
    secondOscillator.type = "sine";

    if (kind === "success") {
      oscillator.frequency.value = 880;
      secondOscillator.frequency.value = 1120;
    } else if (kind === "error") {
      oscillator.frequency.value = 320;
      secondOscillator.frequency.value = 240;
    } else {
      oscillator.frequency.value = 640;
      secondOscillator.frequency.value = 820;
    }

    gain.gain.value = 0.04;
    secondGain.gain.value = 0.035;

    oscillator.connect(gain);
    gain.connect(context.destination);
    secondOscillator.connect(secondGain);
    secondGain.connect(context.destination);

    oscillator.start();
    oscillator.stop(context.currentTime + 0.12);
    secondOscillator.start(context.currentTime + 0.13);
    secondOscillator.stop(context.currentTime + 0.28);
  } catch {
    // Browser blocked audio or context not available.
  }
}

export function useEventStream(handlers: Handlers) {
  const handlersRef = useRef(handlers);
  const ignoreTaskNoticesUntilRef = useRef(Date.now() + 2500);

  useEffect(() => {
    handlersRef.current = handlers;
  }, [handlers]);

  useEffect(() => {
    const source = new EventSource(`${apiBase()}/api/events`);

    source.addEventListener("dashboard.updated", () => handlersRef.current.onDashboard?.());
    source.addEventListener("pipeline.state", () => {
      handlersRef.current.onDashboard?.();
      handlersRef.current.onTasks?.();
    });
    source.addEventListener("task.started", (event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      handlersRef.current.onTasks?.();
      handlersRef.current.onLog?.(payload);
    });
    source.addEventListener("task.completed", (event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      handlersRef.current.onDashboard?.();
      handlersRef.current.onTasks?.();
      handlersRef.current.onLog?.(payload);
    });
    source.addEventListener("task.failed", (event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      handlersRef.current.onDashboard?.();
      handlersRef.current.onTasks?.();
      handlersRef.current.onLog?.(payload);
    });
    source.addEventListener("task.log", (event) =>
      handlersRef.current.onLog?.(JSON.parse((event as MessageEvent).data)),
    );
    source.addEventListener("quote.new", (event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      playBeep("success");
      handlersRef.current.onDashboard?.();
      handlersRef.current.onQuoteNew?.(payload);
    });

    return () => source.close();
  }, []);
}
