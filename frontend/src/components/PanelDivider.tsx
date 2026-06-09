import { useEffect, useRef } from "react";
import type { KeyboardEvent, PointerEvent as ReactPointerEvent } from "react";

export type PanelDividerProps = {
  keyboardStep?: number;
  label: string;
  onResize: (delta: number) => void;
  valueMax: number;
  valueMin: number;
  valueNow: number;
};

export function PanelDivider({
  keyboardStep = 24,
  label,
  onResize,
  valueMax,
  valueMin,
  valueNow,
}: PanelDividerProps) {
  const startX = useRef(0);
  const onResizeRef = useRef(onResize);
  const moveHandlerRef = useRef<((event: globalThis.PointerEvent) => void) | null>(
    null,
  );
  const upHandlerRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    onResizeRef.current = onResize;
  }, [onResize]);

  useEffect(() => cleanupPointerListeners, []);

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    startX.current = event.clientX;
    cleanupPointerListeners();

    function handlePointerMove(moveEvent: globalThis.PointerEvent) {
      const delta = moveEvent.clientX - startX.current;
      startX.current = moveEvent.clientX;
      onResizeRef.current(delta);
    }

    function handlePointerUp() {
      cleanupPointerListeners();
    }

    moveHandlerRef.current = handlePointerMove;
    upHandlerRef.current = handlePointerUp;
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const deltas: Record<string, number> = {
      ArrowLeft: -keyboardStep,
      ArrowRight: keyboardStep,
      Home: valueMin - valueNow,
      End: valueMax - valueNow,
    };
    const delta = deltas[event.key];
    if (delta === undefined) {
      return;
    }
    event.preventDefault();
    onResizeRef.current(delta);
  }

  return (
    <div
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemax={valueMax}
      aria-valuemin={valueMin}
      aria-valuenow={valueNow}
      className="panel-divider"
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      role="separator"
      tabIndex={0}
    >
      ||
    </div>
  );

  function cleanupPointerListeners() {
    if (moveHandlerRef.current) {
      window.removeEventListener("pointermove", moveHandlerRef.current);
      moveHandlerRef.current = null;
    }
    if (upHandlerRef.current) {
      window.removeEventListener("pointerup", upHandlerRef.current);
      upHandlerRef.current = null;
    }
  }
}
