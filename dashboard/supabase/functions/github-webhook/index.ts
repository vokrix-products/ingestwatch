import { serve } from 'https://deno.land/std@0.177.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const PROJECT_URL = Deno.env.get('SUPABASE_URL') ?? ''
const SERVICE_KEY = Deno.env.get('SERVICE_ROLE_KEY') ?? ''
const WEBHOOK_SECRET = Deno.env.get('GITHUB_WEBHOOK_SECRET') ?? ''

async function verify(req: Request, raw: string): Promise<boolean> {
  if (!WEBHOOK_SECRET) return false
  const sig = req.headers.get('x-hub-signature-256') ?? ''
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(WEBHOOK_SECRET), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(raw))
  const hex = [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, '0')).join('')
  return `sha256=${hex}` === sig
}

serve(async (req) => {
  if (req.method !== 'POST') return new Response('ok', { status: 200 })
  if (req.headers.get('x-github-event') !== 'workflow_run') return new Response('ignored', { status: 200 })
  const raw = await req.text()
  if (!(await verify(req, raw))) return new Response('bad signature', { status: 401 })
  let payload: any
  try { payload = JSON.parse(raw) } catch { return new Response('bad json', { status: 400 }) }
  const owner = payload?.repository?.owner?.login
  if (!owner) return new Response('no owner', { status: 200 })
  const sb = createClient(PROJECT_URL, SERVICE_KEY)
  const { data, error } = await sb.rpc('enqueue_monitor_run', { p_repo_owner: owner })
  if (error) return new Response(error.message, { status: 500 })
  return new Response(`queued ${data ?? 0}`, { status: 200 })
})
