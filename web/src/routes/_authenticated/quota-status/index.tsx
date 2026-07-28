import { createFileRoute } from '@tanstack/react-router'

import { QuotaStatusPage } from '@/features/quota-status'

export const Route = createFileRoute('/_authenticated/quota-status/')({
  component: QuotaStatusPage,
})
