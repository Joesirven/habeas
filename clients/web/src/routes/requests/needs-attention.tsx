import { MatchingReviewPage } from '@/routes/approvals/matching-review'
import { RequireRole, OpsPageChrome } from '@/lib/auth'

/** Canonical Needs attention entry — matching.review queue until U7 journey lands. */
export function NeedsAttentionPage() {
  return (
    <RequireRole allow={['super_admin', 'admin', 'data_owner']}>
      <OpsPageChrome
        eyebrow="REQUESTS · NEEDS ATTENTION"
        title="Needs attention"
        support="Pending matching.review gates. Journey stages and richer queue filters land in U7."
      >
        <MatchingReviewPage embedded />
      </OpsPageChrome>
    </RequireRole>
  )
}
