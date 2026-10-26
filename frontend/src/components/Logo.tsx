import React from 'react';

interface LogoProps {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  showText?: boolean;
  showTagline?: boolean;
  className?: string;
}

export const Logo: React.FC<LogoProps> = ({
  size = 'md',
  showText = true,
  showTagline = true,
  className = '',
}) => {
  const sizeMap = {
    sm: { icon: 24, text: 16, sub: 10 },
    md: { icon: 32, text: 20, sub: 11 },
    lg: { icon: 44, text: 28, sub: 13 },
    xl: { icon: 56, text: 36, sub: 14 },
  };

  const { icon, text, sub } = sizeMap[size];
  const gradId = `cw-grad-${size}`;

  return (
    <div className={`flex items-center gap-2.5 select-none ${className}`}>
      {/* CW Icon — matches reference image */}
      <div className="shrink-0 flex items-center justify-center" style={{ width: icon, height: icon }}>
        <svg
          role="img"
          aria-label="CodeWhy logo"
          width={icon}
          height={icon}
          viewBox="0 0 56 56"
          fill="none"
        >
          <defs>
            <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#f65a3b" />
              <stop offset="100%" stopColor="#e33d28" />
            </linearGradient>
            <radialGradient id={`${gradId}-bg`} cx="50%" cy="30%" r="70%">
              <stop offset="0%" stopColor="#17314b" />
              <stop offset="100%" stopColor="#060e20" />
            </radialGradient>
          </defs>

          {/* Dark rounded square background */}
          <rect width="56" height="56" rx="13" fill={`url(#${gradId}-bg)`} />
          <rect width="56" height="56" rx="13" fill="none" stroke={`url(#${gradId})`} strokeWidth="1.5" strokeOpacity="0.6" />

          {/* "C" letter — left side, cyan */}
          <text
            x="10"
            y="38"
            fontFamily="'Inter', sans-serif"
            fontWeight="800"
            fontSize="26"
            fill={`url(#${gradId})`}
          >
            C
          </text>

          {/* "W" letter — right side, slight overlap */}
          <text
            x="26"
            y="38"
            fontFamily="'Inter', sans-serif"
            fontWeight="800"
            fontSize="26"
            fill={`url(#${gradId})`}
          >
            W
          </text>

          {/* Accent dot — bottom right */}
          <circle cx="47" cy="44" r="3" fill="#f59e0b" opacity="0.9" />
        </svg>
      </div>

      {/* Brand wordmark & Tagline */}
      {showText && (
        <div className="flex flex-col justify-center">
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0px', lineHeight: 1 }}>
            <span
              style={{
                fontFamily: "'Inter', sans-serif",
                fontWeight: 800,
                fontSize: text,
                color: 'var(--text)',
                letterSpacing: '-0.02em',
                lineHeight: 1,
              }}
            >
              Code
            </span>
            <span
              style={{
                fontFamily: "'Inter', sans-serif",
                fontWeight: 800,
                fontSize: text,
                background: 'linear-gradient(135deg, #f65a3b 0%, #e33d28 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
                letterSpacing: '-0.02em',
                lineHeight: 1,
              }}
            >
              Why
            </span>
          </div>
          {showTagline && (
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: sub,
                color: 'var(--text-subtle)',
                marginTop: '3px',
                letterSpacing: '0.02em',
                lineHeight: 1,
              }}
            >
              Decision Archeology
            </span>
          )}
        </div>
      )}
    </div>
  );
};
