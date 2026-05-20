import React from 'react';

export const WelcomePanel: React.FC = () => {
  return (
    <div className="welcome-panel">
      <h2>Welcome to Yeo, Captain's personal assistant</h2>
      <div className="example-prompts">
        <h4>Try asking:</h4>
        <ul>
          <li>What's on my calendar?</li>
          <li>Summarize my inbox</li>
          <li>Review the latest PR</li>
        </ul>
      </div>
      <div className="captain-card-editor">
        <label>
          Name: <input type="text" placeholder="Captain's name" />
        </label>
        <label>
          Preferred contact: <input type="text" placeholder="Email or chat handle" />
        </label>
        <label>
          Working hours: <input type="text" placeholder="e.g. 9am-5pm" />
        </label>
      </div>
    </div>
  );
};
