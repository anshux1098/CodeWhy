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
  {
    id: 'home',
    label: 'Overview',
    icon: Compass,
    accent: 'var(--tab-overview)',
  },
  {
    id: 'workspace',
    label: 'Investigate',
    icon: Terminal,
    accent: 'var(--tab-investigate)',
  },
  {
    id: 'decisions',
    label: 'Decisions',
    icon: Layers,
    accent: 'var(--tab-decisions)',
  },
  {
    id: 'file',
    label: 'Before You Change',
    icon: FileCode2,
    accent: 'var(--tab-file)',
  },
  {
    id: 'graph',
    label: 'Knowledge Graph',
    icon: GitFork,
    accent: 'var(--tab-graph)',
  },
  {
    id: 'status',
    label: 'Repo Status',
    icon: Activity,
    accent: 'var(--tab-status)',
  },
];

export const Sidebar: React.FC<SidebarProps> = ({
  currentTab,
  onSelectTab,
  isOpen,
  onToggle,
}) => {
  return (
    <>
      {/* Mobile overlay */}
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
          ${isOpen ? 'translate-x-0 w-60' : '-translate-x-full lg:translate-x-0 lg:w-16'}
        `}
        style={{
          backgroundColor: 'var(--sidebar)',
          borderColor: 'var(--border)',
        }}
      >
        <div className="flex h-full flex-col py-4">
          {/* Header / Toggle */}
          <div className={`flex items-center px-3 mb-5 ${isOpen ? 'justify-between' : 'justify-center'}`}>
            {isOpen && (
              <span style={{ fontSize: '9px', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.15em', color: 'var(--text-subtle)' }}>
                Navigation
              </span>
            )}
            <button
              type="button"
              onClick={onToggle}
              className="p-1.5 rounded-lg transition-colors cursor-pointer"
              style={{ color: 'var(--text-subtle)', backgroundColor: 'transparent' }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--surface-hover)';
                (e.currentTarget as HTMLButtonElement).style.color = 'var(--text)';
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent';
                (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-subtle)';
              }}
              title={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
              aria-expanded={isOpen}
              aria-label={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            >
              {isOpen ? (
                <PanelLeftClose className="w-4 h-4" />
              ) : (
                <PanelLeftOpen className="w-4 h-4" />
              )}
            </button>
          </div>

          {/* Nav Items — card-style with gaps */}
          <nav
            aria-label="Main"
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              padding: '0 10px',
            }}
          >
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
                  className="cursor-pointer transition-all duration-150"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    justifyContent: isOpen ? 'flex-start' : 'center',
                    borderRadius: '10px',
                    padding: isOpen ? '10px 12px' : '11px',
                    border: `1px solid ${active ? `color-mix(in srgb, ${accent} 40%, transparent)` : 'var(--border)'}`,
                    backgroundColor: active ? `color-mix(in srgb, ${accent} 8%, transparent)` : 'transparent',
                    boxShadow: active ? `0 0 14px color-mix(in srgb, ${accent} 12%, transparent), inset 0 0 8px color-mix(in srgb, ${accent} 8%, transparent)` : 'none',
                    position: 'relative',
                    overflow: 'hidden',
                    textAlign: 'left',
                  }}
                  onMouseEnter={e => {
                    if (!active) {
                      const el = e.currentTarget as HTMLButtonElement;
                      el.style.borderColor = `color-mix(in srgb, ${accent} 40%, transparent)`;
                      el.style.backgroundColor = `color-mix(in srgb, ${accent} 8%, transparent)`;
                      el.style.boxShadow = `0 0 10px color-mix(in srgb, ${accent} 12%, transparent)`;
                    }
                  }}
                  onMouseLeave={e => {
                    if (!active) {
                      const el = e.currentTarget as HTMLButtonElement;
                      el.style.borderColor = 'var(--border)';
                      el.style.backgroundColor = 'transparent';
                      el.style.boxShadow = 'none';
                    }
                  }}
                >
                  {/* Active left accent bar */}
                  {active && (
                    <span
                      style={{
                        position: 'absolute',
                        left: 0,
                        top: '18%',
                        bottom: '18%',
                        width: '3px',
                        borderRadius: '0 4px 4px 0',
                        backgroundColor: accent,
                        boxShadow: `0 0 6px ${accent}`,
                      }}
                    />
                  )}

                  <Icon
                    className="w-4 h-4 shrink-0 transition-colors"
                    style={{ color: active ? accent : 'var(--text-subtle)' }}
                  />

                  {isOpen && (
                    <span
                      style={{
                        fontSize: '12px',
                        fontWeight: active ? 600 : 400,
                        color: active ? accent : 'var(--sidebar-text)',
                        fontFamily: 'sans-serif',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        transition: 'color 0.15s',
                      }}
                    >
                      {label}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {/* Footer version */}
          {isOpen && (
            <div
              style={{
                marginTop: 'auto',
                padding: '12px 14px 4px',
                borderTop: '1px solid var(--border)',
              }}
            >
              <p style={{ fontSize: '9px', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.15em', color: 'var(--text-subtle)' }}>
                CodeWhy v1.0
              </p>
            </div>
          )}
        </div>
      </aside>
    </>
  );
};
