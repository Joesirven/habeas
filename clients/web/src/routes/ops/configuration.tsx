import { OpsPageChrome, RequireRole } from '@/lib/auth'

export function OpsConfigurationPage() {
  return (
    <RequireRole allow={['super_admin']}>
      <OpsPageChrome
        eyebrow="OPS · CONFIGURATION"
        title="Configuration"
        support="Infra-owned until an editable concurrency API exists. Retry knobs live under Health."
      >
        <div className="taste-panel p-5">
          <p className="taste-micro">Shell</p>
          <p className="mt-3 text-sm text-ink-soft">
            Role allowlists and worker URLs are deployed via Cloud Build / Console env — not edited
            here in v1.
          </p>
        </div>
      </OpsPageChrome>
    </RequireRole>
  )
}
