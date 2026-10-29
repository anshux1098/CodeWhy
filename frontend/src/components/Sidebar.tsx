import React from 'react';
import {
  Compass,
  Terminal,
  Layers,
  GitFork,
  Activity,
  PanelLeftClose,
  PanelLeftOpen,
  FileCode2,
} from 'lucide-react';

export type AppTab = 'home' | 'workspace' | 'decisions' | 'status' | 'graph' | 'file';

interface SidebarProps {
  variant?: 'default' | 'landing';
  currentTab: AppTab;
  onSelectTab: (tab: AppTab) => void;
  isOpen: boolean;
  onToggle: () => void;
}

interface NavItem {
  id: AppTab;
  label: string;
  icon: React.ElementType;
  accent: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'home', label: 'Overview', icon: Compass, accent: 'var(--tab-overview)' },
  { id: 'workspace', label: 'Investigate', icon: Terminal, accent: 'var(--tab-investigate)' },
  { id: 'decisions', label: 'Decisions', icon: Layers, accent: 'var(--tab-decisions)' },
  { id: 'file', label: 'Before You Change', icon: FileCode2, accent: 'var(--tab-file)' },
  { id: 'graph', label: 'Knowledge Graph', icon: GitFork, accent: 'var(--tab-graph)' },
  { id: 'status', label: 'Repo Status', icon: Activity, accent: 'var(--tab-status)' },
];

export const Sidebar: React.FC<SidebarProps> = ({
  variant = 'default',
  currentTab,
  onSelectTab,
  isOpen,
  onToggle,
}) => {
  const landing = variant === 'landing';

  if (!landing) {
    return (
      <>
        {isOpen && (
          <button
            type="button"
            aria-label="Close sidebar"
            className="fixed inset-0 z-30 bg-black/80 lg:hidden"
            onClick={onToggle}
          />
        )}

        <aside
          className={`
            fixed lg:sticky top-16 left-0 z-40 h-[calc(100vh-4rem)] shrink-0
            border-r transition-[width,transform] duration-200 ease-in-out
            ${isOpen ? 'translate-x-0 w-64' : '-translate-x-full lg:translate-x-0 lg:w-[72px]'}
          `}
          style={{
            backgroundColor: 'var(--sidebar)',
            borderColor: 'var(--border)',
          }}
        >
          <div className="flex h-full flex-col py-5">
            <div className={`flex items-center px-4 mb-6 ${isOpen ? 'justify-between' : 'justify-center'}`}>
              {isOpen && (
                <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-[var(--text-subtle)]">
                  Navigation
                </span>
              )}
              <button
                type="button"
                onClick={onToggle}
                className="sidebar-toggle cursor-pointer rounded-lg p-2 transition-colors"
                title={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
                aria-expanded={isOpen}
                aria-label={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
              >
                {isOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
              </button>
            </div>

            <nav aria-label="Main" className="flex flex-col gap-2 px-3">
              {NAV_ITEMS.map(({ id, label, icon: Icon, accent }) => {
                const active = currentTab === id;
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => {
                      onSelectTab(id);
                      if (isOpen && typeof window !== 'undefined' && window.matchMedia('(max-width: 1023px)').matches) {
                        onToggle();
                      }
                    }}
                    title={label}
                    aria-current={active ? 'page' : undefined}
                    data-nav-tab={id}
                    className="sidebar-nav-button cursor-pointer"
                    style={{ justifyContent: isOpen ? 'flex-start' : 'center', padding: isOpen ? '0 12px' : '0' }}
                  >
                    <span className="sidebar-nav-icon">
                      <Icon className="h-4 w-4 shrink-0" />
                    </span>
                    {isOpen && (
                      <span className="truncate text-[13px] font-medium" style={{ color: active ? accent : 'var(--sidebar-text)' }}>
                        {label}
                      </span>
                    )}
                  </button>
                );
              })}
            </nav>

            {isOpen && (
              <div style={{ marginTop: 'auto', padding: '16px 16px 4px', borderTop: '1px solid var(--border)' }}>
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-subtle)]">
                  CodeWhy v1.0
                </p>
              </div>
            )}
          </div>
        </aside>
      </>
    );
  }

  return (
    <>
      {isOpen && (
        <button
          type="button"
          aria-label="Close sidebar"
          className="fixed inset-0 z-30 bg-black/80 lg:hidden"
          onClick={onToggle}
        />
      )}

      <aside
        className={`cw-sidebar-landing fixed lg:sticky left-0 z-40 shrink-0 border-r transition-[width,transform] duration-200 ease-in-out ${isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0 is-collapsed'}`}
      >
        <div className="flex h-full flex-col py-5">
          <div className={`flex items-center px-4 mb-6 ${isOpen ? 'justify-between' : 'justify-center'}`}>
            {isOpen && (
              <span className="cw-nav-label cw-nav-label">NAVIGATION</span>
            )}
            <button
              type="button"
              onClick={onToggle}
              className="sidebar-toggle cursor-pointer rounded-lg p-2 transition-colors"
              title={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
              aria-expanded={isOpen}
              aria-label={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            >
              {isOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
            </button>
          </div>

          <nav aria-label="Main" className="flex flex-col gap-2 px-3">
            {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
              const active = currentTab === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => {
                    onSelectTab(id);
                    if (isOpen && typeof window !== 'undefined' && window.matchMedia('(max-width: 1023px)').matches) {
                      onToggle();
                    }
                  }}
                  title={label}
                  aria-current={active ? 'page' : undefined}
                  data-nav-tab={id}
                  className="cw-nav-btn flex items-center gap-3 w-full min-h-[44px] px-3 cursor-pointer"
                >
                  <span className="cw-nav-icon flex items-center justify-center shrink-0">
                    <Icon className="h-4 w-4" />
                  </span>
                  {isOpen && (
                    <span className="truncate text-[13px] font-medium">{label}</span>
                  )}
                </button>
              );
            })}
          </nav>

          {isOpen && (
            <div style={{ marginTop: 'auto', padding: '16px 16px 4px', borderTop: '1px solid var(--cw-border)' }}>
              <p className="cw-version">CODEWHY V1.0</p>
            </div>
          )}
        </div>
      </aside>
    </>
  );
};
