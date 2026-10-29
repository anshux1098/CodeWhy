import React from 'react';
import { Logo } from './Logo';
import type { Repository } from '../types';
import type { AppTab } from './Sidebar';
import { branchFromScope } from '../lib/repoBranch';
import {
  GitBranch,
  Layers,
  ChevronDown,
} from 'lucide-react';

interface NavbarProps {
  variant?: 'default' | 'landing';
  onSelectTab: (tab: AppTab) => void;
  selectedRepo: Repository | null;
  onOpenRepoSelector: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  variant = 'default',
  onSelectTab,
  selectedRepo,
  onOpenRepoSelector,
}) => {
  if (variant === 'landing') {
    const branch = branchFromScope(selectedRepo?.scope);
    return (
      <header className="cw-navbar-landing sticky top-0 z-50 w-full flex items-center justify-between px-6 gap-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => onSelectTab('home')}
            className="flex items-center gap-3 cursor-pointer"
            aria-label="CodeWhy home"
          >
            <div className="cw-brand-mark flex items-center justify-center">Cw.</div>
            <div className="flex flex-col leading-none">
              <span className="cw-wordmark text-lg">
                Code<span className="cw-why">Why</span>
              </span>
              <span className="cw-eyebrow-sub mt-1">Decision Intelligence</span>
            </div>
          </button>
        </div>

        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          <div
            className="cw-repo-pill flex min-w-0 items-center gap-2 px-3 py-1.5"
            title={`Active repository: ${selectedRepo?.name || 'None selected'}`}
          >
            <GitBranch className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--cw-olive)' }} />
            <span className="block max-w-[120px] truncate sm:max-w-[180px] font-semibold">
              {selectedRepo?.name || 'No repo selected'}
            </span>
            {branch && (
              <span className="cw-branch text-[11px]">· {branch}</span>
            )}
            {selectedRepo?.fixture && (
              <span className="text-[9px] font-mono px-1 py-0.5 rounded border border-[var(--cw-border)] text-[var(--cw-text-2)]">
                fixture
              </span>
            )}
            <ChevronDown className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--cw-text-2)' }} aria-hidden="true" />
          </div>

          <button
            type="button"
            onClick={onOpenRepoSelector}
            className="cw-switch-repo flex items-center gap-1.5 px-3 py-1.5 cursor-pointer"
          >
            <Layers className="w-3.5 h-3.5" style={{ color: 'var(--cw-bronze)' }} />
            <span>Switch Repo</span>
          </button>
        </div>
      </header>
    );
  }

  return (
    <header
      className="sticky top-0 z-50 w-full backdrop-blur-md"
      style={{
        borderBottom: '1px solid var(--border)',
        backgroundColor: 'color-mix(in srgb, var(--surface) 92%, transparent)',
        boxShadow: '0 2px 14px rgba(0,0,0,0.04)',
      }}
    >
      <div className="w-full px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div onClick={() => onSelectTab('home')} className="cursor-pointer">
            <Logo size="md" />
          </div>
        </div>

        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          <div
            className="flex min-w-0 items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-mono"
            title={`Active repository: ${selectedRepo?.name || 'None selected'}`}
            style={{
              backgroundColor: 'var(--surface-raised)',
              borderColor: 'var(--border)',
            }}
          >
            <GitBranch className="w-3.5 h-3.5 shrink-0 text-emerald-500" />
            <div className="min-w-0 flex items-center gap-1.5">
              <span
                className="block max-w-[110px] truncate sm:max-w-[190px] font-semibold"
                style={{ color: 'var(--text)' }}
              >
                {selectedRepo?.name || 'No repo selected'}
              </span>
              {selectedRepo?.fixture && (
                <span className="badge-amber text-[9px] font-mono px-1 py-0.2 rounded">
                  fixture
                </span>
              )}
            </div>
          </div>

          <button
            type="button"
            onClick={onOpenRepoSelector}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium cursor-pointer transition-all hover:border-violet-500/50"
            style={{
              backgroundColor: 'var(--surface-raised)',
              borderColor: 'var(--border)',
              color: 'var(--text)',
            }}
          >
            <Layers className="w-3.5 h-3.5 text-[var(--primary)]" />
            <span>Switch Repo</span>
          </button>
        </div>
      </div>
    </header>
  );
};
