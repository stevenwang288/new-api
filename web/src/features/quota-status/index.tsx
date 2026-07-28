import { useQuery } from '@tanstack/react-query'
import { Activity, CheckCircle2, CircleAlert, WalletCards } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { SectionPageLayout } from '@/components/layout'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatQuota } from '@/lib/format'
import { ROLE } from '@/lib/roles'
import { useAuthStore } from '@/stores/auth-store'

import { getDispatcherStatus } from '../channels/api'

function formatRemaining(recoveryAt: number | null | undefined, now: number) {
  const seconds = Math.max(0, Math.ceil((recoveryAt ?? 0) - now))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  if (hours > 0) return `${hours}h ${minutes}m ${remainder}s`
  if (minutes > 0) return `${minutes}m ${remainder}s`
  return `${remainder}s`
}

function laneName(value: string) {
  return value.split('/').pop() ?? value
}

export function QuotaStatusPage() {
  const { t } = useTranslation()
  const user = useAuthStore((state) => state.auth.user)
  const isAdmin = (user?.role ?? 0) >= ROLE.ADMIN
  const [now, setNow] = useState(() => Date.now() / 1000)
  const dispatcherQuery = useQuery({
    queryKey: ['dispatcher_status'],
    queryFn: getDispatcherStatus,
    enabled: isAdmin,
    refetchInterval: 5000,
  })

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => window.clearInterval(timer)
  }, [])

  if (!user) return <Skeleton className='m-6 h-64' />

  const quota = Number(user.quota ?? 0)
  const exhausted = quota <= 0
  const lanes = dispatcherQuery.data?.lanes ?? []
  const ready = lanes.filter((lane) => (lane.state ?? (lane.paused > 0 ? 'COOLDOWN' : 'READY')) === 'READY').length

  return (
    <SectionPageLayout>
      <SectionPageLayout.Title>{t('Quota and Routing Status')}</SectionPageLayout.Title>
      <SectionPageLayout.Content>
        <div className='grid gap-4 p-6'>
          <div className='grid gap-3 md:grid-cols-3'>
            <Card className='p-4'>
              <div className='text-muted-foreground flex items-center gap-2 text-sm'><WalletCards className='h-4 w-4' aria-hidden='true' />{t('Remaining quota')}</div>
              <div className='mt-2 font-mono text-2xl font-bold tabular-nums'>{formatQuota(quota)}</div>
            </Card>
            <Card className='p-4'>
              <div className='text-muted-foreground text-sm'>{t('Total consumed quota')}</div>
              <div className='mt-2 font-mono text-2xl font-bold tabular-nums'>{formatQuota(user.used_quota ?? 0)}</div>
            </Card>
            <Card className={exhausted ? 'border-destructive/50 p-4' : 'border-emerald-500/40 p-4'}>
              <div className='text-muted-foreground flex items-center gap-2 text-sm'><Activity className='h-4 w-4' aria-hidden='true' />{t('Routing participation')}</div>
              <div className='mt-2 flex items-center gap-2 font-medium'>
                {exhausted ? <CircleAlert className='h-4 w-4 text-destructive' aria-hidden='true' /> : <CheckCircle2 className='h-4 w-4 text-emerald-600' aria-hidden='true' />}
                {exhausted ? t('Paused until quota is restored') : t('Available')}
              </div>
            </Card>
          </div>

          {isAdmin && dispatcherQuery.isLoading && <Skeleton className='h-40' />}
          {isAdmin && dispatcherQuery.isError && <Card className='border-destructive/40 p-6 text-destructive'>{t('Dispatcher status unavailable')}</Card>}
          {isAdmin && dispatcherQuery.data && (
            <section aria-labelledby='dispatcher-lanes-title' className='grid gap-3'>
              <div className='flex items-center gap-2'>
                <h2 id='dispatcher-lanes-title' className='text-lg font-semibold'>{t('961 Dispatcher Lanes')}</h2>
                <Badge variant='outline'>{ready}/{lanes.length} {t('lanes ready')}</Badge>
                <Badge variant='outline'>{dispatcherQuery.data.status}</Badge>
              </div>
              <div className='grid gap-3 md:grid-cols-2 xl:grid-cols-3'>
                {lanes.map((lane) => {
                  const state = lane.state ?? (lane.paused > 0 ? 'COOLDOWN' : 'READY')
                  const cooling = state !== 'READY' && (lane.recovery_at ?? 0) > now
                  return (
                    <Card key={lane.lane} className='p-4'>
                      <div className='flex items-center justify-between gap-3'>
                        <span className='truncate font-medium'>{laneName(lane.lane)}</span>
                        <Badge variant={state === 'READY' ? 'default' : 'destructive'}>{state}</Badge>
                      </div>
                      <div className='text-muted-foreground mt-3 space-y-1 text-sm'>
                        <div>{t('Requests')}: {lane.requests} · {t('Success')}: {lane.success} · {t('Errors')}: {lane.errors}</div>
                        {cooling && <div>{t('Recovery in')}: {formatRemaining(lane.recovery_at, now)}</div>}
                        {lane.recovery_at && <div>{t('Recovery at')}: {new Date(lane.recovery_at * 1000).toLocaleString()}</div>}
                        {lane.pause_reason && <div>{t('Reason')}: {lane.pause_reason}</div>}
                      </div>
                    </Card>
                  )
                })}
              </div>
            </section>
          )}
        </div>
      </SectionPageLayout.Content>
    </SectionPageLayout>
  )
}
