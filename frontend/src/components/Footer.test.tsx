import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Footer } from './Footer';

describe('Footer visual refinement', () => {
  it('renders brand lockup with CodeWhy and tagline', () => {
    const { container } = render(<Footer />);
    expect(screen.getByText('Code')).toBeTruthy();
    expect(screen.getByText('Why')).toBeTruthy();
    expect(screen.getByText(/Decision Intelligence/i)).toBeTruthy();
    expect(
      screen.getByText(/Git decision archeology engine reconstructing historical rationale/i),
    ).toBeTruthy();
    const footer = container.querySelector('footer');
    expect(footer?.className).toContain('bg-[#080907]');
    expect(footer?.className).toContain('border-[#292A23]');
  });

  it('renders all three capability badges with correct labels', () => {
    render(<Footer />);
    expect(screen.getByText('Verbatim Quote Verification')).toBeTruthy();
    expect(screen.getByText('Temporal Decision Lineage')).toBeTruthy();
    expect(screen.getByText('Principled Refusal Gates')).toBeTruthy();
  });

  it('renders copyright and character-verified supporting text', () => {
    render(<Footer />);
    expect(screen.getByText(new RegExp(`© ${new Date().getFullYear()} CodeWhy Engine`))).toBeTruthy();
    expect(screen.getByText('Grounded in Character-Verified Artifacts')).toBeTruthy();
  });

  it('contains no legacy red badge classes or primary accent tokens', () => {
    const { container } = render(<Footer />);
    const html = container.innerHTML;
    expect(html).not.toContain('badge-violet');
    expect(html).not.toContain('text-violet-500');
    expect(html).not.toContain('var(--primary)');
  });
});
