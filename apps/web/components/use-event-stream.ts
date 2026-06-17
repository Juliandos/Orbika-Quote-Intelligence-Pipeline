"use client";

import { useEffect, useRef } from "react";
import { apiBase } from "./api";

type Handlers = {
  onDashboard?: () => void;
  onTasks?: () => void;
  onQuoteNew?: (payload: any) => void;
  onLog?: (payload: any) => void;
};

function playBeep() {
  try {
    const context = new window.AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = 880;
    gain.gain.value = 0.04;
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.18);
  } catch {
    // Browser blocked audio or context not available.
  }
}

export function useEventStream(handlers: Handlers) {
  const handlersRef = useRef(handlers);

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
      handlersRef.current.onTasks?.();
      handlersRef.current.onLog?.(JSON.parse((event as MessageEvent).data));
    });
    source.addEventListener("task.completed", (event) => {
      handlersRef.current.onDashboard?.();
      handlersRef.current.onTasks?.();
      handlersRef.current.onLog?.(JSON.parse((event as MessageEvent).data));
    });
    source.addEventListener("task.failed", (event) => {
      handlersRef.current.onDashboard?.();
      handlersRef.current.onTasks?.();
      handlersRef.current.onLog?.(JSON.parse((event as MessageEvent).data));
    });
    source.addEventListener("task.log", (event) =>
      handlersRef.current.onLog?.(JSON.parse((event as MessageEvent).data)),
    );
    source.addEventListener("quote.new", (event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      playBeep();
      handlersRef.current.onDashboard?.();
      handlersRef.current.onQuoteNew?.(payload);
    });

    return () => source.close();
  }, []);
}
