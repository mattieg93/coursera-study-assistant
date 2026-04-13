// src/ui_v2/web/src/store/useAppStore.ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AppState {
  // Model selections (persisted so sidebar survives refresh)
  agentModel: string
  visionModel: string
  setAgentModel: (m: string) => void
  setVisionModel: (m: string) => void

  // Active Google Doc
  selectedDocId: string
  setSelectedDocId: (id: string) => void

  // Study page modes
  tbNotesMode: boolean
  setTbNotesMode: (v: boolean) => void

  pendingNotes: string | null
  setPendingNotes: (n: string | null) => void

  // Agent
  isAgentRunning: boolean
  setIsAgentRunning: (v: boolean) => void

  // Dark mode
  darkMode: boolean
  toggleDarkMode: () => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      agentModel: '',
      visionModel: 'Auto-detect',
      setAgentModel: (m) => set({ agentModel: m }),
      setVisionModel: (m) => set({ visionModel: m }),

      selectedDocId: '',
      setSelectedDocId: (id) => set({ selectedDocId: id }),

      tbNotesMode: false,
      setTbNotesMode: (v) => set({ tbNotesMode: v }),

      pendingNotes: null,
      setPendingNotes: (n) => set({ pendingNotes: n }),

      isAgentRunning: false,
      setIsAgentRunning: (v) => set({ isAgentRunning: v }),

      darkMode: false,
      toggleDarkMode: () => set((s) => ({ darkMode: !s.darkMode })),
    }),
    {
      name: 'csa-app-store',
      // Only persist non-runtime state
      partialize: (s) => ({
        agentModel: s.agentModel,
        visionModel: s.visionModel,
        selectedDocId: s.selectedDocId,
        darkMode: s.darkMode,
      }),
    },
  ),
)
