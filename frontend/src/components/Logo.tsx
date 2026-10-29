import React from 'react';

interface LogoProps {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  showText?: boolean;
  showTagline?: boolean;
  className?: string;
  variant?: 'default' | 'landing';
}

export const Logo: React.FC<LogoProps> = ({
  size = 'md',
  showText = true,
  showTagline = true,
  className = '',
  variant = 'default',
}) => {
  const sizeMap = {
    sm: { icon: 28, text: 16, sub: 8, rx: 7 },
    md: { icon: 38, text: 20, sub: 9.5, rx: 10 },
    lg: { icon: 52, text: 28, sub: 11, rx: 14 },
    xl: { icon: 68, text: 36, sub: 13, rx: 18 },
  };
  const { icon, text, sub, rx } = sizeMap[size];

  if (variant === 'landing') {
    return (
      <div className={`flex items-center gap-3 select-none ${className}`}>
        {/* CW Squircle Emblem Mark */}
        <div
          className="relative shrink-0 flex items-center justify-center rounded-lg font-bold transition-transform hover:scale-[1.03]"
          style={{
            width: icon,
            height: icon,
            fontSize: Math.max(10, Math.round(text * 0.65)),
            backgroundImage: 'linear-gradient(180deg, #14150F 0%, #0A0B08 100%)',
            border: '1px solid color-mix(in srgb, #B9915E 52%, #292A23)',
            color: '#F0E9DC',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.4), 0 0 12px rgba(185, 145, 94, 0.15)',
          }}
        >
          Cw.
        </div>

        {/* Typography: Project Name + Tagline */}
        {showText && (
          <div className="flex flex-col justify-center leading-none">
            <div
              className="flex items-baseline tracking-tight font-extrabold"
              style={{
                fontFamily: "'Manrope', sans-serif",
                fontSize: text,
                letterSpacing: '-0.04em',
                lineHeight: 1.1,
              }}
            >
              <span style={{ color: '#F5F3ED' }}>Code</span>
              <span style={{ color: '#B9915E' }}>Why</span>
            </div>
            {showTagline && (
              <span
                style={{
                  fontFamily: "'Manrope', sans-serif",
                  fontSize: sub,
                  fontWeight: 600,
                  color: '#A5A69D',
                  marginTop: '3px',
                  letterSpacing: '0.04em',
                  lineHeight: 1,
                  textTransform: 'uppercase',
                }}
              >
                Decision Intelligence
              </span>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-3 select-none ${className}`}>
      {/* CW Squircle Emblem Mark */}
      <div
        className="relative shrink-0 flex items-center justify-center rounded-xl transition-transform hover:scale-[1.03]"
        style={{
          width: icon,
          height: icon,
          boxShadow: '0 4px 14px rgba(240, 68, 43, 0.22), 0 1px 3px rgba(0,0,0,0.08)',
        }}
      >
        <svg
          role="img"
          aria-label="CodeWhy logo"
          width={icon}
          height={icon}
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <linearGradient id="cw-logo-c" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#ff7957" />
              <stop offset="100%" stopColor="#f0442b" />
            </linearGradient>
            <linearGradient id="cw-logo-w" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#ff6b6b" />
              <stop offset="100%" stopColor="#dc2626" />
            </linearGradient>
          </defs>

          {/* Squircle Background Container */}
          <rect x="1.5" y="1.5" width="45" height="45" rx={rx} fill="#111114" />
          <rect
            x="1.5"
            y="1.5"
            width="45"
            height="45"
            rx={rx}
            stroke="#3b2528"
            strokeWidth="1.2"
            strokeOpacity="1"
          />

          {/* Stylized 'C' */}
          <path
            d="M20 16.5C18.8 15.2 16.9 14.5 15 14.5C10.8 14.5 7.5 18 7.5 24C7.5 30 10.8 33.5 15 33.5C17.2 33.5 19.1 32.5 20.2 31"
            stroke="url(#cw-logo-c)"
            strokeWidth="3.6"
            strokeLinecap="round"
          />

          {/* Stylized 'W' */}
          <path
            d="M23.5 19L27 32L30.5 23L34 32L37.5 19"
            stroke="url(#cw-logo-w)"
            strokeWidth="3.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Floating Insight Dots */}
          <circle cx="30.5" cy="14" r="2.2" fill="#ef4444" />
          <circle cx="37.5" cy="34" r="1.5" fill="#fca5a5" />
        </svg>
      </div>

      {/* Typography: Project Name + Tagline */}
      {showText && (
        <div className="flex flex-col justify-center">
          <div
            className="flex items-baseline tracking-tight font-extrabold"
            style={{
              fontFamily: "'Manrope', sans-serif",
              fontSize: text,
              letterSpacing: '-0.04em',
              lineHeight: 1.1,
            }}
          >
            <span style={{ color: 'var(--text)' }}>Code</span>
            <span
              className="bg-clip-text text-transparent"
              style={{
                backgroundImage: 'linear-gradient(135deg, #FF6B4A 0%, #F0442B 60%, #D8321B 100%)',
              }}
            >
              Why
            </span>
            <span
              className="inline-block w-1.5 h-1.5 rounded-full ml-0.5 mb-0.5"
              style={{ backgroundColor: '#F0442B' }}
            />
          </div>
          {showTagline && (
            <span
              style={{
                fontFamily: "'Manrope', sans-serif",
                fontSize: sub,
                fontWeight: 600,
                color: 'var(--text-subtle)',
                marginTop: '3px',
                letterSpacing: '0.04em',
                lineHeight: 1,
                textTransform: 'uppercase',
              }}
            >
              Decision Intelligence
            </span>
          )}
        </div>
      )}
    </div>
  );
};
