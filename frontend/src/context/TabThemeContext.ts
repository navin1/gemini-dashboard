import { createContext, useContext } from 'react'

export interface TabTheme {
  headerBg: string      // Tailwind bg class for widget header, e.g. 'bg-orange-50'
  headerBorder: string  // Tailwind border class for widget header bottom, e.g. 'border-orange-100'
  airflowEnv?: string   // Airflow environment name for this tab, e.g. 'UAT'
  tabPrefix: string     // Prefix for Airflow in-app tab labels, e.g. 'UAT', 'PRD', 'DEV', 'My'
  onOpenDagTab: (dagId: string, env: string) => void
}

export const DEFAULT_TAB_THEME: TabTheme = {
  headerBg: 'bg-white',
  headerBorder: 'border-gray-100',
  tabPrefix: 'My',
  onOpenDagTab: () => {},
}

export const TabThemeContext = createContext<TabTheme>(DEFAULT_TAB_THEME)

export function useTabTheme(): TabTheme {
  return useContext(TabThemeContext)
}
