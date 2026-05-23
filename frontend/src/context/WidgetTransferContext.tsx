import { createContext, useContext } from 'react'
import type { Widget } from '../types'

export interface TransferTarget { id: string; label: string }

interface WidgetTransferCtx {
  targets: TransferTarget[]
  sendToTab: (widget: Widget, tabId: string) => void
  copyToTab: (widget: Widget, tabId: string) => void
  currentTabId: string
}

const Ctx = createContext<WidgetTransferCtx>({ targets: [], sendToTab: () => {}, copyToTab: () => {}, currentTabId: '' })
export const useWidgetTransfer = () => useContext(Ctx)
export const WidgetTransferProvider = Ctx.Provider
