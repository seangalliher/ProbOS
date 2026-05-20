import React from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { ChatInput } from '../components/wardroom/ChatInput';

describe('ChatInput mention autocomplete', () => {
  it('inserts selected agent mention', () => {
    render(<ChatInput />);
    const input = screen.getByLabelText('Chat input') as HTMLInputElement;

    fireEvent.change(input, { target: { value: 'Hello @' } });
    expect(screen.getByText('@OutlookAgent (draft email)')).toBeInTheDocument();

    fireEvent.click(screen.getByText('@OutlookAgent (draft email)'));
    expect(input.value).toContain('@OutlookAgent');
  });
});
