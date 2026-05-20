import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { WelcomePanel } from '../components/wardroom/WelcomePanel';

describe('WelcomePanel', () => {
  it('renders first-run guidance', () => {
    render(<WelcomePanel />);
    expect(screen.getByText("Welcome to Yeo, Captain's personal assistant")).toBeInTheDocument();
    expect(screen.getByText("What's on my calendar?")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Captain's name")).toBeInTheDocument();
  });
});
