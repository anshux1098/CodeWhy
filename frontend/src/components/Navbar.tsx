import React from 'react';
import { Logo } from './Logo';
import type { Repository } from '../types';
import type { AppTab } from './Sidebar';
import {
  GitBranch,
  Layers,
} from 'lucide-react';

interface NavbarProps {
  onSelectTab: (tab: AppTab) => void;
  selectedRepo: Repository | null;
  onOpenRepoSelector: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  onSelectTab,
  selectedRepo,
  onOpenRepoSelector,
}) => {
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
        
        {/* Left: Brand */}
        <div className="flex items-center gap-3">
          <div onClick={() => onSelectTab('home')} className="cursor-pointer">
            <Logo size="md" />
          </div>
        </div>

        {/* Right: Target Repository, Engine Health & Actions */}
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          
          {/* Active Repo Badge */}
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
          
          {/* Quick Switch Repo Button */}
          <button
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
