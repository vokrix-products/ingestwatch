import { serve } from 'https://deno.land/std@0.177.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const SUPABASE_URL = Deno.env.get('SUPABASE_URL') ?? ''
const SERVICE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
const CLIENT_ID = Deno.env.get('GITHUB_CLIENT_ID') ?? ''
const CLIENT_SECRET = Deno.env.get('GITHUB_CLIENT_SECRET') ?? ''
const APP_URL = Deno.env.get('APP_URL') ?? 'https://ingestwatch.vokrix.co'
const REDIRECT_URI = `${SUPABASE_URL}/functions/v1/github-auth`

function html(msg: string): Response {
  return new Response(`<!doctype html><html><body style="font-family:system-ui;padding:2rem">${msg}</body></html>`, {
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  })
}

async function handleInstall(url: URL): Promise<Response> {
  const jwt = url.searchParams.get('token')
  if (!jwt) return html('Missing auth token. Open this from the dashboard.')
  const sb = createClient(SUPABASE_URL, SERVICE_KEY)
  const { data, error } = await sb.auth.getUser(jwt)
  if (error || !data?.user) return html('Invalid session. Sign in and try again.')
  const state = crypto.randomUUID()
  const { error: se } = await sb
    .from('oauth_states')
    .insert({ state, user_id: data.user.id })
  if (se) return html('Could not start GitHub connection. Try again.')
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    state,
  })
  return Response.redirect(`https://github.com/login/oauth/authorize?${params}`, 302)
}

async function handleCallback(code: string, state: string): Promise<Response> {
  const sb = createClient(SUPABASE_URL, SERVICE_KEY)
  const { data: st, error: ste } = await sb
    .from('oauth_states')
    .select('user_id')
    .eq('state', state)
    .maybeSingle()
  if (ste || !st) return html('Invalid or expired state. Start over from the dashboard.')
  await sb.from('oauth_states').delete().eq('state', state)

  const tokResp = await fetch('https://github.com/login/oauth/access_token', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET,
      code,
      redirect_uri: REDIRECT_URI,
    }),
  })
  const tok = await tokResp.json()
  const accessToken = tok.access_token
  if (!accessToken) {
    return html(`GitHub did not return a token (${tok.error ?? 'unknown error'}). Try again.`)
  }

  const ghResp = await fetch('https://api.github.com/user', {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: 'application/vnd.github+json',
    },
  })
  const gh = await ghResp.json()
  if (!gh.login) return html('Could not load your GitHub profile. Try again.')

  await sb.from('github_connections').upsert(
    {
      user_id: st.user_id,
      github_username: gh.login,
      access_token: accessToken,
      avatar_url: gh.avatar_url ?? null,
      updated_at: new Date().toISOString(),
    },
    { onConflict: 'user_id' }
  )
  return Response.redirect(`${APP_URL}/sources?connected=1`, 302)
}

serve(async (req) => {
  const url = new URL(req.url)
  const code = url.searchParams.get('code')
  const state = url.searchParams.get('state')
  if (code && state) return handleCallback(code, state)
  return handleInstall(url)
})
