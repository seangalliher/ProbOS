/** AD-1021 (completion): MonacoSurface — the lazy-loaded @monaco-editor/react
 *  (MIT) engine wrapper. The ONLY module importing monaco-editor, so the heavy
 *  core is confined to the dynamic-import boundary (CodeWorkstation lazy-imports
 *  this file) and the `monaco-vendor` Vite chunk — never the main HXI bundle.
 *  Self-hosted (local-first: NO CDN loader) via loader.config({ monaco }).
 *  Viewer/scratch only: NO LSP, NO IntelliSense, NO file tree, NO extensions.
 */
import { Editor, loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(self as any).MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

export interface MonacoSurfaceProps {
  value: string;
  language: string;
  readOnly: boolean;
  onChange?: (value: string) => void;
}

export default function MonacoSurface({ value, language, readOnly, onChange }: MonacoSurfaceProps): React.ReactElement {
  return (
    <div data-testid="workstation-monaco" style={{ height: '100%', minHeight: 0 }}>
      <Editor
        value={value}
        language={language}
        theme="vs-dark"
        height="100%"
        onChange={(v) => onChange?.(v ?? '')}
        options={{ readOnly, minimap: { enabled: false }, scrollBeyondLastLine: false, fontSize: 12, fontFamily: "'JetBrains Mono', monospace", wordWrap: 'on', automaticLayout: true }}
      />
    </div>
  );
}
