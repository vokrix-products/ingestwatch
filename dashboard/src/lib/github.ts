import { useEffect, useState } from 'react'
import { supabase, SUPABASE_URL } from '@/lib/supabase'

export interface GithubConnection {
  user_id: string
  github_username: string
  avatar_url: string | null
  installed_at: string
  updated_at: string
}

/** Redirect the user through the GitHub App OAuth flow. */
export async function connectGitHub() {
  const { data } = await supabase.auth.getSession()
  const jwt = data.session?.access_token
  if (!jwt) return
  window.location.href =
    `${SUPABASE_URL}/functions/v1/github-auth/install?token=${encodeURIComponent(jwt)}`
}

/** Poll-safe view of the current user's GitHub connection (no token exposed). */
export function useGithubConnection() {
  const [conn, setConn] = useState<GithubConnection | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    async function load() {
      const { data, error } = await supabase.rpc('get_my_github_connection')
      if (!active) return
      if (error) setError(error.message)
      else setConn((data?.[0] as GithubConnection) ?? null)
    }
    load()
    const interval = setInterval(load, 20000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [])

  return { conn, error }
}
