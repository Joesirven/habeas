import { Link } from '@tanstack/react-router'

import { LegalSettingsSheet } from '@/components/LegalSettingsSheet'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

type UploadMenuProps = {
  size?: 'sm' | 'default'
  variant?: 'default' | 'outline'
}

export function LegalChromeActions() {
  return (
    <div className="flex items-center gap-2">
      <LegalSettingsSheet triggerVariant="header" />
      <UploadMenu />
    </div>
  )
}

export function UploadMenu({ size = 'sm', variant = 'outline' }: UploadMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" size={size} variant={variant} aria-label="Upload">
          +
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link to="/requests/new">Manual request</Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/requests/new">Agent batch</Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
