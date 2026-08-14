import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { supabase, PRODUCT_ID } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth-store'

async function writeAudit(
  action: string,
  entity: string,
  entityId: string,
  userId: string
) {
  try {
    await supabase.from('audit_log').insert({
      product_id: PRODUCT_ID,
      customer_id: userId,
      action,
      entity,
      entity_id: entityId,
    })
  } catch {}
}

export interface SourceRow {
  id: string
  title: string
  status: string
  sourceName: string | null
  repoOwner: string | null
  workflowId: string | null
  lastRunAt: string | null
  nextRunAt: string | null
  schedule: string | null
  runUrl: string | null
  fetched: number | null
  scored: number | null
  qualified: number | null
  alertReason: string | null
  emptyRun: boolean | null
  createdAt: string
}

interface RecordRow {
  id: number | string
  title: string
  status: string
  details: Record<string, unknown> | null
  created_at: string
}

function num(v: unknown): number | null {
  if (typeof v === 'number') return v
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isNaN(n) ? null : n
}

async function fetchSources(): Promise<SourceRow[]> {
  const { data, error } = await supabase
    .from('records')
    .select('id, title, status, details, created_at')
    .eq('product_id', PRODUCT_ID)
    .order('created_at', { ascending: false })

  if (error) throw error

  return (data ?? [])
    .filter(
      (row: RecordRow) =>
        row.details != null &&
        (row.details as Record<string, unknown>).source_name != null
    )
    .map((row: RecordRow) => {
      const d = (row.details ?? {}) as Record<string, unknown>
      return {
        id: String(row.id),
        title: row.title,
        status: row.status,
        sourceName: (d.source_name as string) ?? null,
        repoOwner: (d.repo_owner as string) ?? null,
        workflowId: (d.workflow_id as string) ?? null,
        lastRunAt: (d.last_run_at as string) ?? null,
        nextRunAt: (d.next_run_at as string) ?? null,
        schedule: (d.schedule as string) ?? null,
        runUrl: (d.run_url as string) ?? null,
        fetched: num(d.fetched_count),
        scored: num(d.scored_count),
        qualified: num(d.qualified_count),
        alertReason: (d.alert_reason as string) ?? null,
        emptyRun: typeof d.empty_run === 'boolean' ? d.empty_run : null,
        createdAt: row.created_at,
      }
    })
}

export function useSources() {
  return useQuery({
    queryKey: ['sources', PRODUCT_ID],
    queryFn: fetchSources,
    refetchInterval: 15000,
  })
}

const TRIAL_LIMIT = 3

async function countMonitorRuns(userId: string): Promise<number> {
  const { count, error } = await supabase
    .from('jobs')
    .select('*', { count: 'exact', head: true })
    .eq('product_id', PRODUCT_ID)
    .eq('customer_id', userId)
    .eq('job_type', 'process_sources')
    .in('status', ['pending', 'processing', 'completed'])
  if (error) throw error
  return count ?? 0
}

async function runMonitor(userId: string): Promise<void> {
  const { data } = await supabase.auth.getSession()
  const meta = (data.session?.user?.app_metadata ?? {}) as Record<string, unknown>
  const userProductId = meta.product_id ?? ''
  if (String(userProductId) !== import.meta.env.VITE_PRODUCT_ID) {
    const used = await countMonitorRuns(userId)
    if (used >= TRIAL_LIMIT) throw new Error('TRIAL_LIMIT_REACHED')
  }
  const { error } = await supabase.from('jobs').insert({
    product_id: PRODUCT_ID,
    customer_id: userId,
    job_type: 'process_sources',
    status: 'pending',
  })
  if (error) throw error
}

export function useRunMonitor() {
  const queryClient = useQueryClient()
  const user = useAuthStore((state) => state.auth.user)
  return useMutation({
    mutationFn: async () => {
      if (!user) throw new Error('Not authenticated')
      await runMonitor(user.id)
      if (user?.id)
        void writeAudit('job.created', 'job', 'process_sources', user.id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs', PRODUCT_ID] })
    },
    onError: (err) => {
      if (err instanceof Error && err.message === 'TRIAL_LIMIT_REACHED') {
        window.dispatchEvent(new CustomEvent('open-paywall'))
      }
    },
  })
}
