import * as DialogPrimitive from '@radix-ui/react-dialog'
import * as React from 'react'

import { cn } from '@/lib/utils'

export const Dialog = DialogPrimitive.Root

export const DialogTrigger = DialogPrimitive.Trigger

export const DialogPortal = DialogPrimitive.Portal

export const DialogClose = DialogPrimitive.Close

export const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      'fixed inset-0 z-50 bg-ink/40 backdrop-blur-[2px]',
      className,
    )}
    {...props}
  />
))
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName

export const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        'fixed left-1/2 top-1/2 z-50 flex w-full max-w-lg -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-xl border border-[var(--glass-border)] bg-paper-raised p-6 shadow-lg',
        className,
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close
        className="absolute right-4 top-4 flex h-6 w-6 items-center justify-center rounded-sm text-sm text-mute opacity-70 ring-offset-paper transition-opacity hover:text-ink hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-habeas-mid focus:ring-offset-2 disabled:pointer-events-none"
        aria-label="Close"
      >
        ×
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPortal>
))
DialogContent.displayName = DialogPrimitive.Content.displayName

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('flex flex-col space-y-1.5 text-left', className)} {...props} />
  )
}

export function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)}
      {...props}
    />
  )
}

export const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn('font-display text-lg font-medium leading-none tracking-tight text-ink', className)}
    {...props}
  />
))
DialogTitle.displayName = DialogPrimitive.Title.displayName

export const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn('text-xs text-ink-soft', className)}
    {...props}
  />
))
DialogDescription.displayName = DialogPrimitive.Description.displayName

export type ConfirmActionDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  confirming?: boolean
  /** Destructive styling for decline / irreversible bulk actions. */
  tone?: 'default' | 'destructive'
  /** Extra body content (e.g. DROP response_status picker). */
  children?: React.ReactNode
  /** When false, confirm stays disabled (e.g. required selection missing). */
  confirmDisabled?: boolean
  onConfirm: () => void
}

/** Modal confirm for fulfill / decline / bulk actions. */
export function ConfirmActionDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  confirming = false,
  tone = 'default',
  children,
  confirmDisabled = false,
  onConfirm,
}: ConfirmActionDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // Keep the dialog up while a mutation is in flight so "Working…" is visible.
        if (!next && confirming) return
        onOpenChange(next)
      }}
    >
      <DialogContent className="max-w-md" onOpenAutoFocus={(event) => event.preventDefault()}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {children}
        {confirming ? (
          <p className="text-xs text-ink-soft" role="status" aria-live="polite">
            Working — do not close this tab…
          </p>
        ) : null}
        <DialogFooter>
          <button
            type="button"
            className="inline-flex h-8 items-center justify-center rounded-md border border-line bg-paper px-3 text-xs font-medium text-ink hover:bg-panel disabled:opacity-50"
            disabled={confirming}
            onClick={() => onOpenChange(false)}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className={
              tone === 'destructive'
                ? 'inline-flex h-8 items-center justify-center rounded-md bg-red-700 px-3 text-xs font-medium text-white hover:bg-red-800 disabled:opacity-50'
                : 'inline-flex h-8 items-center justify-center rounded-md bg-habeas-navy px-3 text-xs font-medium text-white hover:bg-habeas-navy/90 disabled:opacity-50'
            }
            disabled={confirming || confirmDisabled}
            onClick={onConfirm}
          >
            {confirming ? 'Working…' : confirmLabel}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
