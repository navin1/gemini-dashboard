import { createContext, useContext } from 'react'

interface AirflowDashContextValue {
  onOpenDagTab: (dagId: string, env: string) => void
}

export const AirflowDashContext = createContext<AirflowDashContextValue>({
  onOpenDagTab: () => {},
})

export function useAirflowDash() {
  return useContext(AirflowDashContext)
}
