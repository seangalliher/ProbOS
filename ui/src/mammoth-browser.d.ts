// AD-1074b: mammoth ships a pre-bundled browser build (mammoth.browser.js)
// without type declarations. Declare the narrow surface the ArtifactViewer uses
// (docx ArrayBuffer -> HTML). The runtime build is resolved by Vite/Node.
declare module 'mammoth/mammoth.browser' {
  export function convertToHtml(
    input: { arrayBuffer: ArrayBuffer },
  ): Promise<{ value: string; messages: unknown[] }>;
  const mammoth: { convertToHtml: typeof convertToHtml };
  export default mammoth;
}
