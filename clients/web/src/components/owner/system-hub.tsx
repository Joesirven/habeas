import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { OwnerConnectorSystem } from '@/lib/api'
import {
  displayStatusChip,
  isOwnerConnectorsHiddenSystem,
  ownerConnectorDisplayName,
} from '@/lib/owner-connector-ui'
import { isSystemComplete } from '@/lib/owner-wizard-flow'

/**
 * Wizard completion is surfaced at top level when the API grows the field and
 * inside `metadata.wizard_completed_at` otherwise — accept either.
 */
export function ownerConnectorWizardCompleted(connector: OwnerConnectorSystem): boolean {
  if (isSystemComplete(connector)) return true
  const fromMetadata = connector.metadata?.wizard_completed_at
  return typeof fromMetadata === 'string' && fromMetadata.length > 0
}

/**
 * Any-order system picker — the wizard hub. One quiet row per visible system
 * with a status chip (same color semantics as the settings list) and a
 * Set up / Review action. Systems can be completed in any order.
 */
export function SystemHub({
  verticalId,
  connectors,
  onSelect,
}: {
  verticalId: string
  connectors: OwnerConnectorSystem[]
  onSelect: (system: string) => void
}) {
  const visible = connectors.filter(
    (connector) => !isOwnerConnectorsHiddenSystem(connector.system),
  )

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-medium text-ink">Data systems</h4>
        <p className="mt-1 text-xs leading-relaxed text-mute">
          Set up each system in any order. Matching starts as soon as a system is connected.
        </p>
      </div>

      {visible.length === 0 ? (
        <p className="rounded-md border border-dashed border-line bg-canvas px-3 py-3 text-xs text-mute">
          No data systems are configured for this vertical.
        </p>
      ) : (
        <ul className="space-y-2">
          {visible.map((connector) => {
            const configured = ownerConnectorWizardCompleted(connector)
            const chip = displayStatusChip(connector.display_status, {
              gateAllowed: connector.gate_allowed,
            })
            return (
              <li
                key={connector.system}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-white px-3 py-2.5"
              >
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-ink">
                    {ownerConnectorDisplayName(verticalId, connector.system, connector.display_name)}
                  </span>
                  {configured ? (
                    <Badge variant="ok">Configured</Badge>
                  ) : (
                    <Badge variant={chip.variant}>{chip.label}</Badge>
                  )}
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant={configured ? 'outline' : 'default'}
                  onClick={() => onSelect(connector.system)}
                >
                  {configured ? 'Review' : 'Set up'}
                </Button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
