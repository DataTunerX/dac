declare module "mermaid" {
  interface MermaidConfig {
    startOnLoad?: boolean
    securityLevel?: string
    theme?: string
    themeVariables?: Record<string, string>
  }

  interface MermaidAPI {
    initialize(config: MermaidConfig): void
    render(id: string, text: string): Promise<{ svg: string; bindFunctions?: (element: Element) => void }>
  }

  const mermaid: MermaidAPI
  export default mermaid
}
