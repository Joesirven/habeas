import { useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'

import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { fetchAdminApi, getFulfillmentArtifact, getRequest } from '@/lib/api'
import { cn } from '@/lib/utils'

type RenderedEmailTemplate = {
  slug: string
  subject: string
  body: string
}

/** Stored templates may carry literal backslash-n sequences — normalize to real newlines. */
function normalizeNewlines(value: string): string {
  return value.replace(/\\n/g, '\n')
}

function renderAccessDeliveryEmail(context: {
  requestor_name: string
  shareable_url: string
}): Promise<RenderedEmailTemplate> {
  return fetchAdminApi<RenderedEmailTemplate>('/requests/email-templates/render', {
    method: 'POST',
    body: JSON.stringify({ slug: 'access_delivery', context }),
  })
}

function deliveryStatusVariant(status: string): 'ok' | 'fail' | 'wait' {
  if (status === 'delivered') return 'ok'
  if (status === 'failed' || status === 'recalled') return 'fail'
  return 'wait'
}

/**
 * `undefined` while loading; `true` iff the request is an ACCESS request
 * (request_type === 'access' or fulfillment artifact kind === 'access').
 *
 * Query keys match RequestDetailOverlay so results are shared from cache.
 */
export function useIsAccessRequest(
  requestId: string,
  seedRequestType?: string | null,
): boolean | undefined {
  const enabled = Boolean(requestId)

  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId],
    queryFn: () => getRequest(requestId),
    enabled,
    staleTime: 30_000,
  })

  const artifactQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', requestId],
    queryFn: () => getFulfillmentArtifact(requestId),
    enabled,
    retry: false,
    staleTime: 30_000,
  })

  if (seedRequestType === 'access') return true
  if (requestQuery.data?.request_type === 'access') return true
  if (artifactQuery.data?.kind === 'access') return true

  const requestSettled = requestQuery.isSuccess || requestQuery.isError
  const artifactSettled = artifactQuery.isSuccess || artifactQuery.isError
  if (requestSettled && artifactSettled) return false
  // A known non-access seed only needs the artifact to rule out an access pack.
  if (seedRequestType && artifactSettled) return false
  return undefined
}

/**
 * Rendered access-delivery email (subject + body with signed URL) in a
 * copyable read-only textarea. Self-gating: renders null when the request is
 * determined not to be an access request (and while that is still unknown).
 */
export function AccessDeliveryEmailCard({
  requestId,
  className,
}: {
  requestId: string
  className?: string
}): ReactElement | null {
  const isAccess = useIsAccessRequest(requestId)

  // Same keys as useIsAccessRequest / RequestDetailOverlay — cache hits, no extra network.
  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId],
    queryFn: () => getRequest(requestId),
    enabled: Boolean(requestId),
    staleTime: 30_000,
  })

  const artifactQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', requestId],
    queryFn: () => getFulfillmentArtifact(requestId),
    enabled: Boolean(requestId),
    retry: false,
    staleTime: 30_000,
  })

  const shareableUrl = artifactQuery.data?.shareable_url ?? null
  // The backend re-signs shareable_url on every artifact poll (~15s in host
  // views), so key the render on the stable gs:// URI to freeze the email text
  // once rendered — otherwise it churns while the user is copying.
  const artifactUri = artifactQuery.data?.fulfillment_artifact_uri ?? null
  const requestorName = requestQuery.data?.display_label?.trim() || 'there'

  const templateQuery = useQuery({
    queryKey: [
      'admin-api',
      'requests',
      'email-templates',
      'render',
      'access_delivery',
      requestId,
      requestorName,
      artifactUri,
    ],
    queryFn: () =>
      renderAccessDeliveryEmail({
        requestor_name: requestorName,
        shareable_url: shareableUrl ?? '',
      }),
    enabled: isAccess === true && Boolean(shareableUrl) && Boolean(artifactUri),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  const [copied, setCopied] = useState(false)
  const copyTimer = useRef<number | null>(null)
  useEffect(
    () => () => {
      if (copyTimer.current != null) window.clearTimeout(copyTimer.current)
    },
    [],
  )

  if (isAccess !== true) return null

  const deliveryStatus = artifactQuery.data?.access_delivery_status ?? null

  const rendered = templateQuery.data
  const emailText = rendered
    ? `Subject: ${normalizeNewlines(rendered.subject)}\n\n${normalizeNewlines(rendered.body)}`
    : ''

  const handleCopy = () => {
    if (!emailText) return
    void navigator.clipboard
      .writeText(emailText)
      .then(() => {
        setCopied(true)
        if (copyTimer.current != null) window.clearTimeout(copyTimer.current)
        copyTimer.current = window.setTimeout(() => setCopied(false), 1600)
      })
      .catch(() => {
        // Clipboard unavailable (permissions / insecure context) — fail soft.
      })
  }

  let body: ReactNode
  if (artifactQuery.isPending) {
    body = <p className="text-ink-soft">Loading fulfillment artifact…</p>
  } else if (artifactQuery.isError || !shareableUrl) {
    body = (
      <p className="text-mute">
        No export artifact yet — run fulfillment to generate the access pack.
      </p>
    )
  } else if (templateQuery.isPending) {
    body = <p className="text-ink-soft">Rendering email template…</p>
  } else if (templateQuery.isError || !rendered) {
    body = (
      <p className="text-mute">
        Couldn't render the access delivery template — copy the shareable URL
        from the handoff panel instead.
      </p>
    )
  } else {
    body = (
      <>
        <p className="text-ink-soft">
          Copy the full email below and paste it into your external mailer —
          the platform does not email requesters.
        </p>
        <textarea
          readOnly
          rows={14}
          value={emailText}
          onFocus={(event) => event.currentTarget.select()}
          aria-label="Access delivery email"
          className="w-full resize-y whitespace-pre-wrap rounded-md border border-line bg-paper/50 px-2.5 py-2 text-xs leading-relaxed text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid"
        />
        <div className="flex items-center gap-2">
          <span className="relative inline-flex">
            <Button size="sm" type="button" onClick={handleCopy}>
              Copy email
            </Button>
            <span
              aria-live="polite"
              className={cn(
                'pointer-events-none absolute -top-7 left-1/2 -translate-x-1/2 rounded-md bg-ink px-2 py-0.5 text-[0.65rem] text-white shadow-sm transition-opacity duration-300',
                copied ? 'opacity-100' : 'opacity-0',
              )}
            >
              Copied
            </span>
          </span>
        </div>
      </>
    )
  }

  return (
    <section
      className={cn(
        'space-y-2 rounded-md border border-line bg-white px-3 py-2.5 text-xs',
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          Access delivery email
        </p>
        {deliveryStatus ? (
          <Badge variant={deliveryStatusVariant(deliveryStatus)}>{deliveryStatus}</Badge>
        ) : null}
      </div>
      {body}
    </section>
  )
}
