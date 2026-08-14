import { useEffect, useMemo, useState } from 'react'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { NotificationsBell } from '@/components/notifications-bell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { RefreshCw, TriangleAlert, Radio } from 'lucide-react'
import { statuses, severityToBadgeVariant } from '@/features/tasks/data/data'
import { connectGitHub, useGithubConnection } from '@/lib/github'
import {
  useSources,
  useRunMonitor,
  type SourceRow,
} from './data/sources'

function statusBadge(status: string) {
  const def = statuses.find((s) => s.value === status)
  const variant = def ? severityToBadgeVariant[def.severity] : 'secondary'
  return <Badge variant={variant}>{def?.label ?? status}</Badge>
}

function formatTime(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export function Sources() {
  const { data: sources, isLoading, error } = useSources()
  const runMonitor = useRunMonitor()
  const { conn } = useGithubConnection()
  const [notice, setNotice] = useState(false)
  const [justConnected, setJustConnected] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('connected') === '1') {
      window.history.replaceState({}, '', window.location.pathname)
      setJustConnected(true)
      void runMonitor.mutateAsync()
    }
  }, [runMonitor])

  const counts = useMemo(() => {
    const rows = sources ?? []
    const critical = rows.filter((r) =>
      r.status.endsWith(':critical')
    ).length
    const attention = rows.filter(
      (r) =>
        r.status.endsWith(':warning') || r.status.endsWith(':critical')
    ).length
    return { total: rows.length, attention, critical }
  }, [sources])

  const [paywallOpen, setPaywallOpen] = useState(false)

  useEffect(() => {
    const open = () => setPaywallOpen(true)
    window.addEventListener('open-paywall', open)
    return () => window.removeEventListener('open-paywall', open)
  }, [])

  async function handleRun() {
    try {
      await runMonitor.mutateAsync()
      setNotice(true)
    } catch {}
  }

  return (
    <>
      <Header fixed>
        <Search className='me-auto' />
        <ThemeSwitch />
        <NotificationsBell />
        <ProfileDropdown />
      </Header>

      <Main className='flex flex-1 flex-col gap-4 sm:gap-6'>
        {justConnected && conn && (
          <div className='flex items-center justify-between rounded-lg border border-success bg-success/10 px-4 py-3 text-sm text-success'>
            <span>
              GitHub connected as @{conn.github_username}. Click “Run monitor
              now” to discover your scheduled workflows.
            </span>
            <button
              onClick={() => setJustConnected(false)}
              className='ml-4 text-xs font-medium underline underline-offset-2'
            >
              Dismiss
            </button>
          </div>
        )}

        {!conn && (
          <div className='flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-4 py-3'>
            <p className='text-sm text-muted-foreground'>
              Connect GitHub to start monitoring your scheduled ingestion
              workflows.
            </p>
            <Button
              onClick={connectGitHub}
              data-testid='connect-github-button'
              size='sm'
            >
              Connect GitHub App
            </Button>
          </div>
        )}

        <div className='flex flex-wrap items-end justify-between gap-2'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>
              Monitored Sources
            </h2>
            <p className='text-muted-foreground'>
              Scheduled ingestion jobs under watch
            </p>
          </div>
          <div className='flex items-center gap-2'>
            {conn && (
              <Button
                variant='outline'
                size='sm'
                onClick={connectGitHub}
                data-testid='reconnect-github-button'
              >
                Re-connect / switch account
              </Button>
            )}
            <Button
              onClick={handleRun}
              disabled={runMonitor.isPending}
              data-testid='run-monitor-button'
            >
              <RefreshCw
                className={
                  runMonitor.isPending ? 'h-4 w-4 animate-spin' : 'h-4 w-4'
                }
              />
              {runMonitor.isPending ? 'Queuing...' : 'Run monitor now'}
            </Button>
          </div>
        </div>

        {notice && (
          <div className='flex items-center justify-between rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm text-muted-foreground'>
            <span>
              Monitor run queued — results appear here within a minute.
              Sources are discovered from your connected GitHub account.
            </span>
            <button
              onClick={() => setNotice(false)}
              className='ml-4 text-xs font-medium underline underline-offset-2'
            >
              Dismiss
            </button>
          </div>
        )}

        <div className='grid gap-4 sm:grid-cols-3'>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
              <CardTitle className='text-sm font-medium'>
                Total Sources
              </CardTitle>
              <Radio className='h-4 w-4 text-muted-foreground' />
            </CardHeader>
            <CardContent>
              <div className='text-2xl font-bold tracking-tight'>
                {isLoading ? (
                  <Skeleton className='h-8 w-12' />
                ) : (
                  counts.total
                )}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
              <CardTitle className='text-sm font-medium'>
                Needs Attention
              </CardTitle>
              <TriangleAlert className='h-4 w-4 text-muted-foreground' />
            </CardHeader>
            <CardContent>
              <div className='text-2xl font-bold tracking-tight text-destructive'>
                {isLoading ? (
                  <Skeleton className='h-8 w-12' />
                ) : (
                  counts.attention
                )}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
              <CardTitle className='text-sm font-medium'>Critical</CardTitle>
              <TriangleAlert className='h-4 w-4 text-muted-foreground' />
            </CardHeader>
            <CardContent>
              <div className='text-2xl font-bold tracking-tight text-destructive'>
                {isLoading ? (
                  <Skeleton className='h-8 w-12' />
                ) : (
                  counts.critical
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Sources</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading && <Skeleton className='h-24 w-full' />}
            {error && (
              <p className='text-sm text-destructive'>
                Failed to load: {error.message}
              </p>
            )}
            {!isLoading && !error && sources && sources.length === 0 && (
              <div className='flex flex-col items-center justify-center gap-2 py-10 text-center'>
                <Radio className='h-8 w-8 text-muted-foreground/40' />
                <p className='text-sm font-medium'>
                  No monitored sources yet
                </p>
                <p className='max-w-md text-sm text-muted-foreground'>
                  Sources are auto-discovered from your GitHub Actions
                  workflows on each monitor run (read-only). Connect GitHub
                  above, then click “Run monitor now”.
                </p>
              </div>
            )}
            {!isLoading &&
              !error &&
              sources &&
              sources.length > 0 && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Source</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last Run</TableHead>
                      <TableHead className='text-right'>Fetched</TableHead>
                      <TableHead className='text-right'>Scored</TableHead>
                      <TableHead className='text-right'>Qualified</TableHead>
                      <TableHead>Alert</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sources.map((s: SourceRow) => (
                      <TableRow key={s.id}>
                        <TableCell>
                          <div className='font-medium'>{s.title}</div>
                          <div className='text-xs text-muted-foreground'>
                            {[s.repoOwner, s.workflowId]
                              .filter(Boolean)
                              .join(' / ') ||
                              (s.sourceName ?? '')}
                            {s.schedule ? ` · ${s.schedule}` : ''}
                          </div>
                        </TableCell>
                        <TableCell>{statusBadge(s.status)}</TableCell>
                        <TableCell>{formatTime(s.lastRunAt)}</TableCell>
                        <TableCell className='text-right'>
                          {s.fetched ?? '—'}
                        </TableCell>
                        <TableCell className='text-right'>
                          {s.scored ?? '—'}
                        </TableCell>
                        <TableCell className='text-right'>
                          {s.qualified ?? '—'}
                        </TableCell>
                        <TableCell>
                          {s.alertReason ? (
                            <span className='text-xs text-muted-foreground'>
                              {s.alertReason}
                            </span>
                          ) : s.runUrl ? (
                            <a
                              href={s.runUrl}
                              target='_blank'
                              rel='noreferrer'
                              className='text-xs text-primary hover:underline'
                            >
                              View run
                            </a>
                          ) : (
                            <span className='text-xs text-muted-foreground'>
                              —
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
          </CardContent>
        </Card>
        <Dialog open={paywallOpen} onOpenChange={setPaywallOpen}>
          <DialogContent className='gap-2 sm:max-w-sm'>
            <DialogHeader className='text-start'>
              <DialogTitle>
                {import.meta.env.VITE_PAYWALL_TITLE ??
                  'You have used your 3 free Sources'}
              </DialogTitle>
              <DialogDescription>
                Upgrade to get unlimited monitoring, instant run updates, and
                full access to IngestWatch.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter className='gap-2'>
              <DialogClose asChild>
                <Button variant='outline'>Not now</Button>
              </DialogClose>
              <Button
                onClick={() => {
                  window.location.href =
                    import.meta.env.VITE_STRIPE_CHECKOUT_URL ??
                    'https://checkout.stripe.com/c/pay/cs_live_a1wy2GPxBsc8qE54nOWGSPbXb9IpKBtBRYByKz'
                }}
              >
                Upgrade — $49/month
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </Main>
    </>
  )
}
