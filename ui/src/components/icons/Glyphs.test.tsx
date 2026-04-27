import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import * as Glyphs from './Glyphs';

const glyphNames = Object.keys(Glyphs).filter(
  k => typeof (Glyphs as any)[k] === 'function'
);

describe.each(glyphNames)('%s', (name) => {
  it('renders an SVG element', () => {
    const Component = (Glyphs as any)[name];
    const { container } = render(<Component />);
    expect(container.querySelector('svg')).toBeTruthy();
  });

  it('applies default stroke properties', () => {
    const Component = (Glyphs as any)[name];
    const { container } = render(<Component />);
    const svg = container.querySelector('svg');
    const STROKE_EXEMPT = new Set(['StatusDone']);
    if (!STROKE_EXEMPT.has(name)) {
      expect(svg?.getAttribute('stroke')).toBe('currentColor');
      expect(svg?.getAttribute('stroke-width')).toBe('1.5');
      expect(svg?.getAttribute('stroke-linecap')).toBe('round');
    }
  });

  it('respects custom size prop', () => {
    const Component = (Glyphs as any)[name];
    const { container } = render(<Component size={24} />);
    const svg = container.querySelector('svg');
    expect(svg?.getAttribute('width')).toBe('24');
    expect(svg?.getAttribute('height')).toBe('24');
  });
});

it('StatusDone uses fill=currentColor', () => {
  const { container } = render(<Glyphs.StatusDone />);
  const circle = container.querySelector('circle');
  expect(circle?.getAttribute('fill')).toBe('currentColor');
});

it('exports the expected number of glyph components', () => {
  const count = Object.keys(Glyphs).filter(
    k => typeof (Glyphs as any)[k] === 'function'
  ).length;
  // 25 glyphs defined in BF-041
  expect(count).toBe(25);
});
