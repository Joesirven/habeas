import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded border px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-wide',
  {
    variants: {
      variant: {
        default: 'border-line bg-canvas text-ink',
        ok: 'border-emerald-200 bg-emerald-50 text-emerald-800',
        fail: 'border-red-200 bg-red-50 text-red-800',
        run: 'border-sky-200 bg-sky-50 text-sky-900',
        wait: 'border-line bg-white text-ink-soft',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
