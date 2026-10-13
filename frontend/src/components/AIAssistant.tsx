import { useEffect, useRef, useState } from 'react';
import { chatWithAssistant } from '../api/client';
import type { AssistantMessage } from '../types';

const QUICK_ACTIONS = ["What's urgent today?", 'Plan my day', 'Show my pending tasks', 'What should I focus on?', 'Explain my priorities'];

export default function AIAssistant({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (open) endRef.current?.scrollIntoView({ block: 'end' }); }, [open, messages, thinking]);
  if (!open) return null;
  const send = async (question = input) => {
    const content = question.trim();
    if (!content || thinking) return;
    const nextHistory = [...messages, { role: 'user' as const, content }];
    setMessages(nextHistory); setInput(''); setThinking(true);
    try { const response = await chatWithAssistant(content, messages); setMessages([...nextHistory, { role: 'assistant', content: response.message }]); }
    catch { setMessages([...nextHistory, { role: 'assistant', content: "Sorry, I couldn't process that request right now. Please try again." }]); }
    finally { setThinking(false); }
  };
  return <div className="assistant-overlay" role="presentation"><section className="assistant-panel" role="dialog" aria-modal="true" aria-label="AI Assistant"><header className="assistant-panel-header"><div><strong>AI Assistant</strong><span>Workday Signal</span></div><button onClick={onClose} aria-label="Close AI Assistant">×</button></header><div className="assistant-conversation"><div className="assistant-welcome"><span>AI</span><p>How can I help with your workday?</p></div>{messages.length === 0 && <div className="assistant-quick-actions">{QUICK_ACTIONS.map((action) => <button key={action} onClick={() => send(action)}>{action}</button>)}</div>}{messages.map((message, index) => <div className={`assistant-message ${message.role}`} key={`${message.role}-${index}`}><span>{message.role === 'assistant' ? 'AI' : 'You'}</span><p>{message.content}</p></div>)}{thinking && <div className="assistant-thinking"><span>AI</span><p><i /> Thinking...</p></div>}<div ref={endRef} /></div><form className="assistant-input" onSubmit={(event) => { event.preventDefault(); send(); }}><input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask about your workday..." aria-label="Ask the AI Assistant" disabled={thinking} /><button type="submit" disabled={!input.trim() || thinking} aria-label="Send message">→</button></form></section></div>;
}
