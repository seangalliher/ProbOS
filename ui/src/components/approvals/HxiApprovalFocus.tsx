const FOCUS_RING_CSS = `
[data-hxi-focus]:focus{outline:none}
[data-hxi-focus]:focus-visible{outline:1px solid #f0b060;outline-offset:-1px}
`;

export function HxiApprovalFocus(): React.JSX.Element {
  return <style>{FOCUS_RING_CSS}</style>;
}
