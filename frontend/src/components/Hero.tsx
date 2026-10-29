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
          <radialGradient id="cw-amb-olive" cx="50%" cy="36%" r="52%">
            <stop offset="0%" stopColor="#757F6C" stopOpacity="0.12" />
            <stop offset="55%" stopColor="#757F6C" stopOpacity="0.04" />
            <stop offset="100%" stopColor="#080907" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="cw-amb-bronze" cx="64%" cy="76%" r="46%">
            <stop offset="0%" stopColor="#B9915E" stopOpacity="0.09" />
            <stop offset="100%" stopColor="#080907" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="cw-amb-sage" cx="34%" cy="80%" r="42%">
            <stop offset="0%" stopColor="#8C806F" stopOpacity="0.07" />
            <stop offset="100%" stopColor="#080907" stopOpacity="0" />
          </radialGradient>

          <linearGradient id="cw-line-sage" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#757F6C" stopOpacity="0.05" />
            <stop offset="42%" stopColor="#8C806F" stopOpacity="0.62" />
            <stop offset="100%" stopColor="#757F6C" stopOpacity="0.05" />
          </linearGradient>
          <linearGradient id="cw-line-bronze" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#8C806F" stopOpacity="0.05" />
            <stop offset="55%" stopColor="#B9915E" stopOpacity="0.68" />
            <stop offset="100%" stopColor="#8C806F" stopOpacity="0.05" />
          </linearGradient>
          <linearGradient id="cw-line-taupe" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#B9915E" stopOpacity="0.05" />
            <stop offset="48%" stopColor="#8C806F" stopOpacity="0.56" />
            <stop offset="100%" stopColor="#B9915E" stopOpacity="0.05" />
          </linearGradient>

          <radialGradient id="cw-shade-bronze" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#B9915E" stopOpacity="0.07" />
            <stop offset="100%" stopColor="#B9915E" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="cw-shade-olive" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#757F6C" stopOpacity="0.06" />
            <stop offset="100%" stopColor="#757F6C" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* ambient light */}
        <rect width="1600" height="900" fill="url(#cw-amb-olive)" />
        <rect width="1600" height="900" fill="url(#cw-amb-sage)" />
        <rect width="1600" height="900" fill="url(#cw-amb-bronze)" />

        {/* dotted field */}
        <g opacity="0.12">
          {Array.from({ length: 70 }).map((_, i) => {
            const x = (i * 97) % 1600;
            const y = (i * 53 + 17) % 900;
            return <circle key={i} cx={x} cy={y} r="0.8" fill="#8C806F" />;
          })}
        </g>

        {/* orbital arc — thin, low contrast, a few glowing nodes */}
        <g className="cw-arc">
          <ellipse
            cx="800"
            cy="560"
            rx="640"
            ry="500"
            fill="none"
            stroke="#757F6C"
            strokeOpacity="0.13"
            strokeWidth="0.7"
          />
          <circle cx="800" cy="60" r="7" fill="#F5F3ED" opacity="0.05" />
          <circle cx="800" cy="60" r="2.1" fill="#F5F3ED" opacity="0.8" />
          <circle cx="246" cy="310" r="6" fill="#B9915E" opacity="0.07" />
          <circle cx="246" cy="310" r="1.9" fill="#B9915E" opacity="0.8" />
          <circle cx="1354" cy="310" r="6" fill="#B9915E" opacity="0.07" />
          <circle cx="1354" cy="310" r="1.9" fill="#B9915E" opacity="0.8" />
          <circle cx="1000" cy="121" r="1.3" fill="#AFD2FA" opacity="0.5" />
        </g>

        {/* atmospheric shading beneath selected curves */}
        <ellipse cx="1130" cy="862" rx="520" ry="150" fill="url(#cw-shade-bronze)" />
        <ellipse cx="360" cy="872" rx="480" ry="140" fill="url(#cw-shade-olive)" />

        {/* flowing silk / topographic contour lines */}
        <g className="cw-waves">
          {[
            { d: 'M -150 598 C 110 558 340 700 640 664 S 1140 596 1720 638', g: 'sage', w: 0.7, o: 0.55 },
            { d: 'M -140 632 C 170 592 400 700 700 672 S 1200 604 1720 656', g: 'bronze', w: 0.8, o: 0.62 },
            { d: 'M -150 662 C 120 618 360 690 620 668 S 1120 618 1720 665', g: 'taupe', w: 0.7, o: 0.55 },
            { d: 'M -120 694 C 180 642 380 730 660 700 S 1180 642 1720 700', g: 'bronze', w: 0.95, o: 0.76 },
            { d: 'M -140 724 C 160 672 420 760 720 730 S 1220 672 1720 725', g: 'sage', w: 0.7, o: 0.58 },
            { d: 'M -130 748 C 140 698 400 782 690 755 S 1200 700 1720 748', g: 'taupe', w: 0.75, o: 0.6 },
            { d: 'M -120 762 C 200 706 460 796 760 765 S 1240 706 1730 760', g: 'bronze', w: 0.9, o: 0.8 },
            { d: 'M -145 796 C 220 742 500 834 800 807 S 1280 748 1720 800', g: 'sage', w: 0.7, o: 0.58 },
            { d: 'M -140 812 C 180 766 470 852 770 826 S 1260 772 1720 820', g: 'taupe', w: 0.8, o: 0.64 },
            { d: 'M -120 842 C 240 792 540 876 840 849 S 1320 792 1720 842', g: 'bronze', w: 0.75, o: 0.66 },
            { d: 'M -130 872 C 260 828 560 906 860 884 S 1340 830 1720 878', g: 'sage', w: 0.65, o: 0.5 },
            { d: 'M -110 900 C 280 856 580 926 880 902 S 1360 856 1720 900', g: 'taupe', w: 0.7, o: 0.52 },
          ].map((wave, i) => (
            <path
              key={i}
              d={wave.d}
              fill="none"
              stroke={`url(#cw-line-${wave.g})`}
              strokeWidth={wave.w}
              opacity={wave.o}
              strokeLinecap="round"
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
        <ArrowRight className="h-4 w-4 cw-arrow" />
      </button>
    </div>
  </section>
);
