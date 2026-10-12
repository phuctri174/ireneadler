import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { CoreSocket } from "../link/coreSocket";
import "./CommandBar.css";

// Typed input to Irene until there is a microphone. Opens under her face; while
// open the window takes the keyboard and the mouse (it is click-through
// otherwise). Enter sends, Escape closes and gives both back. When a tool needs
// a yes, the bar asks and the next Enter answers it.

const GOODBYE_CLOSE_MS = 2600;

interface Pending {
  id: string;
  prompt: string;
}

interface Props {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  core: CoreSocket;
  /** Dev test hook: text submitted exactly as if typed and Entered. Bump n to send. */
  inject?: { text: string; n: number } | null;
  /** Called on every keystroke that changes the text - she watches him type. */
  onTyping?: () => void;
}

function yesNo(text: string): boolean | null {
  const t = text.trim().toLowerCase();
  if (/^(y|yes|yeah|yep|ok|okay|sure|do it|go ahead)\b/.test(t)) return true;
  if (/^(n|no|nope|cancel|stop|don'?t)\b/.test(t)) return false;
  return null;
}

export function CommandBar({ open, onOpen, onClose, core, inject = null, onTyping }: Props) {
  const input = useRef<HTMLInputElement | null>(null);
  const [text, setText] = useState("");
  const [said, setSaid] = useState<string | null>(null);
  const [reply, setReply] = useState<{ speak: string; display: string } | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [latency, setLatency] = useState<number | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [hint, setHint] = useState<string | null>(null);

  // the window only takes input while the bar is open
  useEffect(() => {
    void invoke("command_bar", { open }).catch((cause: unknown) => {
      console.error("command bar focus failed", cause);
    });
    if (open) window.setTimeout(() => input.current?.focus(), 30);
  }, [open]);

  useEffect(() => {
    let closeTimer = 0;
    const stop = core.onMessage((message) => {
      switch (message.type) {
        case "transcript":
          if (message.role === "user") {
            setSaid(message.text);
            setReply(null);
            setLatency(null);
            setStatus("thinking…");
          }
          break;
        case "reply":
          setReply({ speak: message.speak, display: message.display });
          setStatus(null);
          break;
        case "tool":
          setStatus(message.status === "running" ? `using ${message.name}…` : message.status === "failed" ? `${message.name} failed` : null);
          break;
        case "latency":
          setLatency(message.command_to_audio_ms);
          break;
        case "confirm":
          setPending({ id: message.id, prompt: message.prompt });
          setStatus(null);
          onOpen();
          break;
        case "confirm_done":
          setPending((value) => (value?.id === message.id ? null : value));
          break;
        case "conversation":
          if (message.event === "reset") {
            setSaid(null);
            setReply(null);
            setLatency(null);
          } else {
            window.clearTimeout(closeTimer);
            closeTimer = window.setTimeout(onClose, GOODBYE_CLOSE_MS);
          }
          break;
      }
    });
    return () => {
      stop();
      window.clearTimeout(closeTimer);
    };
  }, [core, onOpen, onClose]);

  const submit = (raw: string = text): void => {
    const value = raw.trim();
    if (!value) return;
    if (pending) {
      const answer = yesNo(value);
      if (answer === null) {
        setHint("type y or n");
        return;
      }
      core.send({ type: "confirm_reply", id: pending.id, ok: answer });
      setPending(null);
      setHint(null);
      setText("");
      return;
    }
    if (!core.send({ type: "command", text: value })) {
      setHint("core is not connected");
      return;
    }
    setHint(null);
    setText("");
  };

  // dev hook: the same submit path as Enter, without any OS-level input
  const submitRef = useRef(submit);
  submitRef.current = submit;
  useEffect(() => {
    if (inject && open) submitRef.current(inject.text);
  }, [inject?.n]); // eslint-disable-line react-hooks/exhaustive-deps

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    // keep Escape/Enter here: the app's Escape would otherwise hide the whole window
    event.stopPropagation();
    if (event.key === "Enter") {
      event.preventDefault();
      submit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      if (pending) core.send({ type: "confirm_reply", id: pending.id, ok: false });
      setPending(null);
      onClose();
    }
  };

  if (!open) return null;
  return (
    <div className={pending ? "cmdbar is-confirm" : "cmdbar"} role="dialog" aria-label="Command bar">
      {said || reply || status ? (
        <div className="cmdbar-log">
          {said ? <div className="cmdbar-you">{said}</div> : null}
          {status ? <div className="cmdbar-status readout">{status}</div> : null}
          {reply?.speak ? <div className="cmdbar-irene">{reply.speak}</div> : null}
          {reply?.display ? <pre className="cmdbar-display">{reply.display}</pre> : null}
        </div>
      ) : null}
      {pending ? (
        <div className="cmdbar-confirm">
          <span className="readout">CONFIRM</span> {pending.prompt}? <b>y / n</b>
        </div>
      ) : null}
      <div className="cmdbar-row">
        <span className="cmdbar-prompt">{pending ? "y/n" : "›"}</span>
        <input
          ref={input}
          className="cmdbar-input"
          value={text}
          placeholder={pending ? "y or n, then Enter" : "Talk to Irene - Enter to send, Esc to close"}
          spellCheck={false}
          onChange={(event) => {
            setText(event.target.value);
            onTyping?.();
          }}
          onKeyDown={onKeyDown}
        />
        {latency !== null ? <span className="cmdbar-latency readout">{latency} ms</span> : null}
      </div>
      {hint ? <div className="cmdbar-hint readout">{hint}</div> : null}
    </div>
  );
}

export default CommandBar;
