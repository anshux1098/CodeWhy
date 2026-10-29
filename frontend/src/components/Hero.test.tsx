import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { Hero } from './Hero';
import type { Repository } from '../types';

function makeRepo(overrides: Partial<Repository>): Repository {
  return {
    id: 'repo',
    name: 'repo',
    url: 'https://example.test/repo',
    owner: null,
    full_name: null,
    scope: null,
    counts: { decisions: 0, entities: 0, pull_requests: 0, commits: 0 },
    ...overrides,
  };
}

beforeAll(() => {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal('ResizeObserver', ResizeObserverStub);
  window.matchMedia = ((query: string) => ({
    matches: query.includes('prefers-reduced-motion') || query.includes('min-width: 1100px'),
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

describe('Hero repository stars', () => {
  const repositories = [
    makeRepo({
      id: 'sqlalchemy-alembic',
      name: 'alembic',
      owner: 'sqlalchemy',
      full_name: 'sqlalchemy/alembic',
      scope: null,
      counts: { decisions: 9, entities: 6, pull_requests: 199, commits: 345 },
    }),
    makeRepo({
      id: 'urllib3-urllib3',
      name: 'urllib3',
      owner: 'urllib3',
      full_name: 'urllib3/urllib3',
      scope: 'urllib3/urllib3 at branch main, commits 2009-12-10..2026-10-01',
      counts: { decisions: 34, entities: 24, pull_requests: 299, commits: 735 },
      sources_analyzed: 96,
      last_rebuilt_at: '2026-10-18T21:18:02.432234+00:00',
    }),
  ];

  it('renders one accessible star per repository and marks the selected one', () => {
    render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={() => {}}
      />,
    );

    const stars = screen.getAllByRole('button', { name: /^Repository / });
    expect(stars).toHaveLength(2);
    expect(stars[0].className).toContain('is-selected');
    expect(stars[1].className).not.toContain('is-selected');
    expect(stars[0].getAttribute('aria-label')).toContain('current repository');
    expect(stars[1].getAttribute('aria-label')).toContain('switch repository');
    expect(stars[0].getAttribute('aria-haspopup')).toBe('dialog');
  });

  it('renders every available repository without a fixed cap', () => {
    const many = Array.from({ length: 5 }, (_, i) =>
      makeRepo({ id: `repo-${i}`, name: `repo-${i}` }),
    );
    render(<Hero repositories={many} selectedRepo={many[0]} onSelectRepo={() => {}} />);

    const stars = screen.getAllByRole('button', { name: /^Repository / });
    expect(stars).toHaveLength(5);
    expect(new Set(stars.map((star) => star.getAttribute('aria-label'))).size).toBe(5);
  });

  it('labels the tooltip as current or switch and only shows a reliable branch', () => {
    const { container } = render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={() => {}}
      />,
    );

    const stars = screen.getAllByRole('button', { name: /^Repository / });
    expect(stars[0].textContent).toContain('Current repository');
    expect(stars[0].textContent).not.toContain('branch');
    expect(stars[1].textContent).toContain('Switch repository');
    expect(stars[1].textContent).toContain('branch main');
    expect(container.querySelectorAll('.cw-arc-seg')).toHaveLength(2);
    expect(container.querySelectorAll('.cw-arc-seg.is-selected')).toHaveLength(1);
  });

  it('opens repository details on click without switching on hover', () => {
    const onSelectRepo = vi.fn();
    render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={onSelectRepo}
      />,
    );
    const stars = screen.getAllByRole('button', { name: /^Repository / });

    fireEvent.pointerEnter(stars[1]);
    expect(onSelectRepo).not.toHaveBeenCalled();
    fireEvent.pointerLeave(stars[1]);

    fireEvent.click(stars[1]);
    expect(onSelectRepo).not.toHaveBeenCalled();

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('heading', { name: 'urllib3' })).toBeTruthy();
    expect(dialog.textContent).toContain('urllib3');
    expect(dialog.textContent).toContain('main');
    expect(dialog.textContent).toContain('34');
    expect(dialog.querySelector('a')?.getAttribute('href')).toBe(
      'https://example.test/repo',
    );
    expect(stars[1].getAttribute('aria-expanded')).toBe('true');
  });

  it('switches through the existing handler from the details panel', () => {
    const onSelectRepo = vi.fn();
    render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={onSelectRepo}
      />,
    );
    fireEvent.click(screen.getAllByRole('button', { name: /^Repository / })[1]);

    fireEvent.click(screen.getByRole('button', { name: /Switch to repository/ }));
    expect(onSelectRepo).toHaveBeenCalledTimes(1);
    expect(onSelectRepo.mock.calls[0][0].id).toBe('urllib3-urllib3');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows the current state instead of a switch action for the selected repo', () => {
    render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={() => {}}
      />,
    );
    fireEvent.click(screen.getAllByRole('button', { name: /^Repository / })[0]);

    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toContain('Current repository');
    expect(within(dialog).queryByRole('button', { name: /Switch to repository/ })).toBeNull();
  });

  it('omits metadata the repository does not provide', () => {
    const bare = makeRepo({ id: 'bare', name: 'bare' });
    render(<Hero repositories={[bare]} selectedRepo={bare} onSelectRepo={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /^Repository / }));

    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).not.toContain('Owner');
    expect(dialog.textContent).not.toContain('Branch');
    expect(dialog.textContent).not.toContain('sources analyzed');
    expect(dialog.textContent).not.toContain('Rebuilt');
  });

  it('dismisses on Escape, restores focus, and dismisses on an outside press', () => {
    render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={() => {}}
      />,
    );
    const stars = screen.getAllByRole('button', { name: /^Repository / });

    fireEvent.click(stars[1]);
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(stars[1]);

    fireEvent.click(stars[1]);
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('keeps the panel open while pressing inside it', () => {
    render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={() => {}}
      />,
    );
    fireEvent.click(screen.getAllByRole('button', { name: /^Repository / })[1]);
    const dialog = screen.getByRole('dialog');

    fireEvent.pointerDown(within(dialog).getByRole('heading', { name: 'urllib3' }));
    expect(screen.getByRole('dialog')).toBeTruthy();
  });

  it('moves the persistent selection when repository state changes', () => {
    const { rerender } = render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={() => {}}
      />,
    );
    rerender(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[1]}
        onSelectRepo={() => {}}
      />,
    );

    const stars = screen.getAllByRole('button', { name: /^Repository / });
    expect(stars[0].className).not.toContain('is-selected');
    expect(stars[1].className).toContain('is-selected');
  });

  it('closes the panel when the app selects another repository', () => {
    const { rerender } = render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={() => {}}
      />,
    );
    fireEvent.click(screen.getAllByRole('button', { name: /^Repository / })[1]);
    expect(screen.getByRole('dialog')).toBeTruthy();

    rerender(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[1]}
        onSelectRepo={() => {}}
      />,
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
