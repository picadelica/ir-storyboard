import {
  cloneElement,
  type FocusEvent,
  type HTMLAttributes,
  type MouseEvent,
  type PointerEvent,
  type ReactElement,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

type Placement = "top" | "bottom";

interface HintState {
  title: string;
  body?: string;
  x: number;
  y: number;
  placement: Placement;
}

interface HintTargetProps {
  title: string;
  body?: string;
  children: ReactElement<HTMLAttributes<HTMLElement>>;
  delay?: number;
}

function positionFor(target: HTMLElement): Pick<HintState, "x" | "y" | "placement"> {
  const rect = target.getBoundingClientRect();
  const tooltipWidth = 286;
  const x = Math.min(
    window.innerWidth - tooltipWidth - 12,
    Math.max(12, rect.left + rect.width / 2 - tooltipWidth / 2),
  );
  const placement: Placement = rect.top < 175 ? "bottom" : "top";
  const y = placement === "top" ? rect.top - 10 : rect.bottom + 10;

  return { x, y, placement };
}

export function HintTarget({ title, body, children, delay = 400 }: HintTargetProps) {
  const [hint, setHint] = useState<HintState | null>(null);
  const timer = useRef<number | null>(null);
  const suppressUntil = useRef(0);

  const clearTimer = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const show = (target: HTMLElement) => {
    clearTimer();
    if (Date.now() < suppressUntil.current) return;
    const pos = positionFor(target);
    timer.current = window.setTimeout(() => {
      timer.current = null;
      if (
        Date.now() < suppressUntil.current ||
        document.visibilityState !== "visible" ||
        !document.hasFocus() ||
        !target.isConnected
      ) {
        return;
      }
      setHint({ title, body, ...pos });
    }, delay);
  };

  const hide = () => {
    clearTimer();
    setHint(null);
  };

  useEffect(() => {
    const hideGlobal = () => {
      suppressUntil.current = Date.now() + 700;
      clearTimer();
      setHint(null);
    };
    const hideWhenInvisible = () => {
      if (document.visibilityState !== "visible") hideGlobal();
    };

    window.addEventListener("blur", hideGlobal);
    window.addEventListener("focus", hideGlobal);
    window.addEventListener("pagehide", hideGlobal);
    document.addEventListener("visibilitychange", hideWhenInvisible);

    return () => {
      window.removeEventListener("blur", hideGlobal);
      window.removeEventListener("focus", hideGlobal);
      window.removeEventListener("pagehide", hideGlobal);
      document.removeEventListener("visibilitychange", hideWhenInvisible);
      clearTimer();
    };
  }, []);

  const childProps = children.props;

  const nextProps = {
    ...childProps,
    onMouseEnter: (event: MouseEvent<HTMLElement>) => {
      childProps.onMouseEnter?.(event);
      show(event.currentTarget);
    },
    onMouseLeave: (event: MouseEvent<HTMLElement>) => {
      childProps.onMouseLeave?.(event);
      hide();
    },
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      childProps.onPointerDown?.(event);
      hide();
    },
    onFocus: (event: FocusEvent<HTMLElement>) => {
      childProps.onFocus?.(event);
      hide();
    },
    onBlur: (event: FocusEvent<HTMLElement>) => {
      childProps.onBlur?.(event);
      hide();
    },
    "data-hintable": "true",
  } as HTMLAttributes<HTMLElement> & { "data-hintable": string };

  const next = cloneElement(children, nextProps);
  const bodyLines = hint?.body?.split("\n") ?? [];

  return (
    <>
      {next}
      {hint && createPortal(
        <div
          className={`ir-global-hint ${hint.placement}`}
          role="tooltip"
          style={{ left: hint.x, top: hint.y }}
        >
          <strong>{hint.title}</strong>
          {bodyLines.map((line, index) => (
            <span
              key={index}
              className={line.trim().startsWith("Бывш") ? "ir-global-hint-legacy" : undefined}
            >
              {line}
            </span>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
}
