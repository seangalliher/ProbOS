/** AD-793 (Wave 196) vitest — "+" button opens NewProjectModal, POST
 * creates the project in the store, submit disabled when name empty. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar } from '../components/sidebar/ThreadSidebar';

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    chatThreads: new Map(),
    projects: new Map(),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  global.fetch = vi.fn((url: any, init: any) => {
    const u = String(url);
    if (u === '/api/projects' && init?.method === 'POST') {
      const body = JSON.parse(init.body);
      return Promise.resolve({
        ok: true,
        json: async () => ({
          id: 'newp1',
          name: body.name,
          description: body.description ?? '',
          pinned_attachment_ids: [],
          archived: false,
          created_at: 1,
          last_active_at: 1,
        }),
      }) as any;
    }
    if (u.startsWith('/api/projects')) {
      return Promise.resolve({ ok: true, json: async () => ({ projects: [] }) }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any;
  });
});

afterEach(() => {
  cleanup();
});

describe('ThreadSidebar new project modal', () => {
  it('opens the modal when "+" clicked and disables submit when name empty', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.click(screen.getByTestId('sidebar-new-project'));
    expect(screen.getByTestId('new-project-modal')).toBeInTheDocument();
    const submit = screen.getByTestId('new-project-submit') as HTMLButtonElement;
    // Empty name → disabled.
    expect(submit.disabled).toBe(true);
    // Type a name → enabled.
    const nameInput = screen.getByTestId('new-project-name');
    fireEvent.change(nameInput, { target: { value: 'My Project' } });
    expect(submit.disabled).toBe(false);
  });

  it('submits and adds the project to the store', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.click(screen.getByTestId('sidebar-new-project'));
    fireEvent.change(screen.getByTestId('new-project-name'), { target: { value: 'My Project' } });
    fireEvent.change(screen.getByTestId('new-project-description'), {
      target: { value: 'A test project' },
    });
    fireEvent.click(screen.getByTestId('new-project-submit'));
    await waitFor(() => {
      expect(useStore.getState().projects.get('newp1')).toBeTruthy();
    });
    expect(useStore.getState().projects.get('newp1')?.name).toBe('My Project');
    // Modal closed.
    expect(screen.queryByTestId('new-project-modal')).not.toBeInTheDocument();
    // Project visible in sidebar.
    expect(screen.getByTestId('project-row-newp1')).toBeInTheDocument();
  });

  it('Cancel button closes modal without creating', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.click(screen.getByTestId('sidebar-new-project'));
    fireEvent.click(screen.getByTestId('new-project-cancel'));
    expect(screen.queryByTestId('new-project-modal')).not.toBeInTheDocument();
    expect(useStore.getState().projects.size).toBe(0);
  });
});
