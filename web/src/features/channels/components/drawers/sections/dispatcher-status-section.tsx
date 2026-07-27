import { useQuery } from '@tanstack/react-query'
import { Activity, CheckCircle2, CircleAlert } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

import { getDispatcherStatus } from '../../../api'

function laneName(value: string) {
  return value.split('/').pop() ?? value
}

function cooldownLabel(cooldownUntil: number, now: number, ready: string, cooling: string) {
  const remaining = Math.max(0, cooldownUntil - now)
  return remaining > 0 ? `${cooling} ${Math.ceil(remaining)}s` : ready
}

export function DispatcherStatusSection() {
  const { t } = useTranslation()
  const now = Date.now() / 1000
  const query = useQuery({
    queryKey: ['dispatcher_status'],
    queryFn: getDispatcherStatus,
    refetchInterval: 5000,
  })

  if (query.isLoading) return <Skeleton className='h-28 w-full' />
  if (query.isError || !query.data) {
    return (
      <Card className='border-destructive/40 p-4'>
        <div className='text-destructive flex items-center gap-2 text-sm'>
          <CircleAlert className='h-4 w-4' aria-hidden='true' />
          {t('Dispatcher status unavailable')}
        </div>
      </Card>
    )
  }

  return (
    <Card className='p-4'>
      <div className='mb-3 flex items-center justify-between gap-2'>
        <div className='flex items-center gap-2 text-sm font-semibold'>
          <Activity className='h-4 w-4' aria-hidden='true' />
          {t('961 Dispatcher Status')}
        </div>
        <Badge variant='outline'>{query.data.status}</Badge>
      </div>
      <div className='grid gap-2 sm:grid-cols-2'>
        {query.data.lanes.map((lane) => {
          const paused = lane.paused > 0
          return (
            <div
              key={lane.lane}
              className='bg-muted/30 flex items-center justify-between gap-3 rounded-md px-3 py-2 text-xs'
            >
              <div className='flex min-w-0 items-center gap-2'>
                {paused ? (
                  <CircleAlert className='text-destructive h-3.5 w-3.5 shrink-0' aria-hidden='true' />
                ) : (
                  <CheckCircle2 className='text-emerald-600 h-3.5 w-3.5 shrink-0' aria-hidden='true' />
                )}
                <span className='truncate font-medium'>{laneName(lane.lane)}</span>
              </div>
              <div className='text-muted-foreground flex shrink-0 flex-col items-end gap-0.5'>
                <span>
                  {t('Requests')}: {lane.requests} · {t('Success')}: {lane.success} · {t('Errors')}: {lane.errors}
                </span>
                <span>
                  {paused ? `${t('Paused')} ${lane.paused}s` : t('Available')} ·{' '}
                  {cooldownLabel(lane.cooldown_until, now, t('Ready'), t('Cooling down'))}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
