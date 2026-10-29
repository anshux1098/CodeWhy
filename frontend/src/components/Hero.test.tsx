import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
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
    matches: query.includes('min-width: 1100px'),
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
    makeRepo({ id: 'sqlalchemy-alembic', name: 'alembic', scope: null }),
    makeRepo({
      id: 'urllib3-urllib3',
      name: 'urllib3',
      scope: 'urllib3/urllib3 at branch main',
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
  });

  it('only shows a branch when the scope carries reliable branch text', () => {
    const { container } = render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={() => {}}
      />,
    );

    const stars = screen.getAllByRole('button', { name: /^Repository / });
    expect(stars[0].textContent).toContain('Current');
    expect(stars[0].textContent).not.toContain('branch');
    expect(stars[1].textContent).toContain('branch main');
    expect(container.querySelectorAll('.cw-arc-seg')).toHaveLength(2);
    expect(container.querySelectorAll('.cw-arc-seg.is-selected')).toHaveLength(1);
  });

  it('selects on click and never on hover', () => {
    const onSelectRepo = vi.fn();
    const { container } = render(
      <Hero
        repositories={repositories}
        selectedRepo={repositories[0]}
        onSelectRepo={onSelectRepo}
      />,
    );
    const stars = screen.getAllByRole('button', { name: /^Repository / });

    fireEvent.pointerEnter(stars[1]);
    fireEvent.pointerLeave(stars[1]);
    expect(onSelectRepo).not.toHaveBeenCalled();

    fireEvent.click(stars[1]);
    expect(onSelectRepo).toHaveBeenCalledTimes(1);
    expect(onSelectRepo.mock.calls[0][0].id).toBe('urllib3-urllib3');
    expect(container.querySelectorAll('.cw-arc-seg.is-hovered')).toHaveLength(0);
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

  it('caps visible stars to the orbit slots without dropping repositories', () => {
    const many = Array.from({ length: 8 }, (_, i) =>
      makeRepo({ id: `repo-${i}`, name: `repo-${i}` }),
    );
    render(<Hero repositories={many} selectedRepo={many[0]} onSelectRepo={() => {}} />);
    expect(screen.getAllByRole('button', { name: /^Repository / })).toHaveLength(6);
  });

  it('never marks another star when the selected repository is not visible', () => {
    const many = Array.from({ length: 8 }, (_, i) =>
      makeRepo({ id: `repo-${i}`, name: `repo-${i}` }),
    );
    const { container } = render(
      <Hero repositories={many} selectedRepo={many[7]} onSelectRepo={() => {}} />,
    );
    expect(screen.queryAllByRole('button', { name: /current repository/ })).toHaveLength(0);
    expect(container.querySelectorAll('.cw-repo-star.is-selected')).toHaveLength(0);
    expect(container.querySelectorAll('.cw-arc-seg.is-selected')).toHaveLength(0);
  });
});
