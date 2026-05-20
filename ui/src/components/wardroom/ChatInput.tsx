import React, { useState } from 'react';

interface AgentIntent {
  agent: string;
  intent: string;
}

const registeredAgents: AgentIntent[] = [
  { agent: 'OutlookAgent', intent: 'draft email' },
  { agent: 'ArchitectAgent', intent: 'review code' },
  // ...populate from backend in real impl
];

export const ChatInput: React.FC = () => {
  const [input, setInput] = useState('');
  const [showMentions, setShowMentions] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setInput(value);
    if (value.endsWith('@')) {
      setShowMentions(true);
      setMentionQuery('');
    } else if (showMentions) {
      const match = value.match(/@(\w*)$/);
      setMentionQuery(match ? match[1] : '');
    }
  };

  const handleMentionClick = (agent: string) => {
    setInput(input.replace(/@\w*$/, `@${agent} `));
    setShowMentions(false);
  };

  const filteredAgents = registeredAgents.filter(a =>
    a.agent.toLowerCase().startsWith(mentionQuery.toLowerCase())
  );

  return (
    <div className="chat-input">
      <input
        value={input}
        onChange={handleInput}
        placeholder="Type a message..."
        aria-label="Chat input"
      />
      {showMentions && (
        <ul className="mention-list">
          {filteredAgents.map(a => (
            <li key={a.agent} onClick={() => handleMentionClick(a.agent)}>
              @{a.agent} ({a.intent})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
