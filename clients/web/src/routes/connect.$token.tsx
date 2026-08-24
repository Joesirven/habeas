import { Link } from '@tanstack/react-router'

import { Button } from '@/components/ui/button'

export function ConnectTokenPage() {
  return (
    <div className="fixed inset-0 z-[60] flex flex-col items-center justify-center bg-[#F8FAFC] px-4">
      <div className="w-full max-w-md space-y-4 rounded-lg border border-[#E2E8F0] bg-white p-6 text-center shadow-sm">
        <h1 className="text-lg font-medium text-[#0F172A]">Invite link retired</h1>
        <p className="text-sm text-[#475569]">
          This invite link is retired. Open Connectors from the app after you&apos;re assigned a
          vertical.
        </p>
        <Button asChild className="bg-habeas-navy hover:bg-habeas-navy/90">
          <Link to="/owner/connectors">Open Connectors</Link>
        </Button>
      </div>
    </div>
  )
}
