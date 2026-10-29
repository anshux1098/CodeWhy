import React from 'react';
import { ArrowRight } from 'lucide-react';

interface HeroProps {
  onNavigateToWorkspace?: (initialQuestion?: string) => void;
}

export const Hero: React.FC<HeroProps> = ({ onNavigateToWorkspace }) => (
  <section className="cw-hero">
    <div className="cw-backdrop" aria-hidden="true">
      <svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice">
        <defs>
          <radialGradient id="cw-glow-1" cx="50%" cy="40%" r="45%">
            <stop offset="0%" stopColor="#757F6C" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#080907" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="cw-glow-2" cx="70%" cy="70%" r="40%">
            <stop offset="0%" stopColor="#B9915E" stopOpacity="0.12" />
            <stop offset="100%" stopColor="#080907" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="cw-wave" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#757F6C" stopOpacity="0.06" />
            <stop offset="45%" stopColor="#B9915E" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#757F6C" stopOpacity="0.06" />
          </linearGradient>
        </defs>

        <rect width="1600" height="900" fill="url(#cw-glow-1)" />
        <rect width="1600" height="900" fill="url(#cw-glow-2)" />

        {/* dotted field */}
        <g opacity="0.18">
          {Array.from({ length: 90 }).map((_, i) => {
            const x = (i * 97) % 1600;
            const y = (i * 53 + 17) % 900;
            return <circle key={i} cx={x} cy={y} r="0.9" fill="#8C806F" />;
          })}
        </g>

        {/* orbital arc */}
        <g className="cw-arc">
          <ellipse
            cx="800"
            cy="560"
            rx="640"
            ry="500"
            fill="none"
            stroke="#757F6C"
            strokeOpacity="0.2"
            strokeWidth="1"
          />
          <circle cx="800" cy="60" r="3" fill="#F5F3ED" opacity="0.85" />
          <circle cx="246" cy="310" r="2.4" fill="#B9915E" opacity="0.9" />
          <circle cx="1354" cy="310" r="2.4" fill="#B9915E" opacity="0.9" />
          <circle cx="1000" cy="121" r="1.5" fill="#AFD2FA" opacity="0.6" />
        </g>

        {/* horizon glow */}
        <ellipse cx="800" cy="820" rx="760" ry="180" fill="#B9915E" opacity="0.05" />

        {/* flowing contour waves */}
        <g className="cw-waves">
          {[
            'M 0 720 C 260 690 520 760 800 730 S 1300 690 1600 730',
            'M 0 760 C 280 730 540 800 820 770 S 1320 730 1600 770',
            'M 0 800 C 300 770 560 840 840 810 S 1340 770 1600 810',
            'M 0 840 C 320 810 580 880 860 850 S 1360 810 1600 850',
            'M 0 680 C 240 650 500 720 780 690 S 1280 650 1600 690',
            'M 0 640 C 220 610 480 680 760 650 S 1260 610 1600 650',
          ].map((d, i) => (
            <path
              key={i}
              d={d}
              fill="none"
              stroke="url(#cw-wave)"
              strokeWidth={i === 2 ? 1.5 : 1}
              opacity={0.55 + (i % 3) * 0.12}
            />
          ))}
        </g>
      </svg>
    </div>

    <div className="cw-hero-content">
      <div className="cw-eyebrow">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <circle cx="3" cy="6" r="1.6" fill="#B9915E" />
          <circle cx="9" cy="6" r="1.6" fill="#757F6C" />
          <path d="M4.6 6h2.8" stroke="#8C806F" strokeWidth="1" />
        </svg>
        <span>Code Archeology &amp; Temporal Decision Provenance</span>
      </div>

      <div className="cw-hero-mark flex items-center justify-center">Cw.</div>

      <h1 className="cw-hero-title">
        Code<span className="cw-why">Why</span>
      </h1>

      <p className="cw-tagline">
        Every line has a history. Find the reasoning, not just the code.
      </p>

      <button
        type="button"
        onClick={() => onNavigateToWorkspace?.()}
        className="cw-cta"
      >
        <span>Start investigation</span>
        <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  </section>
);
