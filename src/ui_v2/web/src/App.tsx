import { useEffect } from 'react'
import { Switch, Route } from 'wouter'
import { Layout } from '@/components/Layout'
import { StudyPage } from '@/pages/StudyPage'
import { AgentPage } from '@/pages/AgentPage'
import { KBPage } from '@/pages/KBPage'
import { useAppStore } from '@/store/useAppStore'

function App() {
  const darkMode = useAppStore((s) => s.darkMode)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode)
  }, [darkMode])

  return (
    <Layout>
      <Switch>
        <Route path="/" component={StudyPage} />
        <Route path="/agent" component={AgentPage} />
        <Route path="/kb" component={KBPage} />
        <Route>
          <div className="flex flex-1 items-center justify-center text-gray-400">Page not found</div>
        </Route>
      </Switch>
    </Layout>
  )
}

export default App
