import { useQuery } from '@tanstack/react-query'
import { Activity, CheckCircle2, CircleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { SectionPageLayout } from '@/components/layout'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

import { getDispatcherStatus } from '../channels/api'

function laneName(value: string) {
  return value.split('/').pop() ?? value
}

function formatRemaining(recoveryAt: number | null | undefined, now: number) {
  const seconds = Math.max(0, Math.ceil((recoveryAt ?? 0) - now))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  if (hours > 0) return `${hours}h ${minutes}m ${remainder}s`
  if (minutes > 0) return `${minutes}m ${remainder}s`
  return `${remainder}s`
}

function statusVariant(state: string | undefined) {
  return state === 'READY' ? 'default' : 'destructive'
}

export function DispatcherStatusPage() {
  const { t } = useTranslation()
  const [now, setNow] = useState(() => Date.now() / 1000)
  const query = useQuery({
    queryKey: ['dispatcher_status'],
    queryFn: getDispatcherStatus,
    refetchInterval: 5000,
  })

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => window.clearInterval(timer)
  }, [])

  if (query.isLoading) return <Skeleton className='m-6 h-64' />
  if (query.isError || !query.data) {
    return <Card className='m-6 border-destructive/40 p-6 text-destructive'>{t('Dispatcher status unavailable')}</Card>
  }

  const ready = query.data.lanes.filter((lane) => (lane.state ?? (lane.paused > 0 ? 'COOLDOWN' : 'READY')) === 'READY').length
  return (
    <SectionPageLayout>
      <SectionPageLayout.Title>{t('Dispatcher Status')}</SectionPageLayout.Title>
      <SectionPageLayout.Content>
      <div className='grid gap-4 p-6'>
        <div className='flex items-center gap-2 text-sm'>
          <Activity className='h-4 w-4' aria-hidden='true' />
          <span>{ready}/{query.data.lanes.length} {t('lanes ready')}</span>
          <Badge variant='outline'>{query.data.status}</Badge>
        </div>
        <div className='grid gap-3 md:grid-cols-2 xl:grid-cols-3'>
          {query.data.lanes.map((lane) => {
            const state = lane.state ?? (lane.paused > 0 ? 'COOLDOWN' : 'READY')
            const cooling = state !== 'READY' && (lane.recovery_at ?? 0) > now
            return (
              <Card key={lane.lane} className='p-4'>
                <div className='flex items-center justify-between gap-3'>
                  <div className='flex min-w-0 items-center gap-2'>
                    {state === 'READY' ? <CheckCircle2 className='h-4 w-4 text-emerald-600' aria-hidden='true' /> : <CircleAlert className='h-4 w-4 text-destructive' aria-hidden='true' />}
                    <span className='truncate font-medium'>{laneName(lane.lane)}</span>
                  </div>
                  <Badge variant={statusVariant(state)}>{state}</Badge>
                </div>
                <div className='text-muted-foreground mt-3 space-y-1 text-sm'>
                  <div>{t('Requests')}: {lane.requests} · {t('Success')}: {lane.success} · {t('Errors')}: {lane.errors}</div>
                  {cooling && <div>{t('Recovery in')}: {formatRemaining(lane.recovery_at, now)}</div>}
                  {lane.recovery_at && <div>{t('Recovery at')}: {new Date(lane.recovery_at * 1000).toLocaleString()}</div>}
                  {lane.recovery_source && <div>{t('Recovery source')}: {lane.recovery_source === 'upstream' ? t('Upstream') : t('Estimated')}</div>}
                  {lane.pause_reason && <div>{t('Reason')}: {lane.pause_reason}</div>}
                </div>
              </Card>
            )
          })}
        </div>
      </div>
      </SectionPageLayout.Content>
    </SectionPageLayout>
  )
}
