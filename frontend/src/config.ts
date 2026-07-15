declare global {
  interface Window {
    AgentIAConfig?: AppOptions
  }
}

export type AppOptions = {
  apiUrl: string
  siteId: string
  clientId?: string
  title?: string
  demoMailFlow?: boolean
}

export function getAppConfig(): Required<AppOptions> {
  return {
    apiUrl: window.AgentIAConfig?.apiUrl ?? 'http://localhost:8000',
    siteId: window.AgentIAConfig?.siteId ?? '',
    clientId: window.AgentIAConfig?.clientId ?? '',
    title: window.AgentIAConfig?.title ?? 'Assistant de gestion',
    demoMailFlow: window.AgentIAConfig?.demoMailFlow ?? false
  }
}
