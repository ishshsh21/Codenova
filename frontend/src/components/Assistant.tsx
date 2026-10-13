import { useEffect, useRef, useState } from 'react';
import { askAssistant } from '../api/client';
import type { AssistantMessage } from '../types';

const STARTERS = ['What should I do first?', 'Why is my top task ranked first?', 'What is overdue?'];

export default function Assistant({ onClose }: { onClose: () => void }) {
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }); }, [messages, thinking]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const send = async (text = input) => {
    const content = text.trim();
    if (!content || thinking) return;
    const history = [...messages, { role: 'user' as const, content }];
    setMessages(history); setInput(''); setThinking(true);
    try {
      const reply = await askAssistant(content, messages);
      setMessages([...history, { role: 'assistant', content: reply.message }]);
    } catch {
      setMessages([...history, { role: 'assistant', content: "Sorry, I couldn't answer that right now. Please try again." }]);
    } finally {
      setThinking(false);
    }
  };

  return (
    <div className="scrim" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Assistant" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head"><strong>Ask Codenova</strong><button className="btn btn-icon" aria-label="Close" onClick={onClose}>×</button></header>
        <div className="chat">
          {!messages.length && (
            <div className="chips">{STARTERS.map((s) => <button key={s} className="chip" onClick={() => send(s)}>{s}</button>)}</div>
          )}
          {messages.map((m, i) => <p key={i} className={`bubble bubble-${m.role}`}>{m.content}</p>)}
          {thinking && <p className="bubble bubble-assistant muted">Thinking…</p>}
          <div ref={endRef} />
        </div>
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about your tasks…" aria-label="Message" disabled={thinking} />
          <button className="btn btn-primary" disabled={!input.trim() || thinking}>Send</button>
        </form>
      </aside>
    </div>
  );
}
