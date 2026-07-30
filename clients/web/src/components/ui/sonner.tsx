import type { CSSProperties } from 'react'
import { Toaster as Sonner, type ToasterProps } from 'sonner'

/** shadcn/ui Sonner toaster — mount once in AppShell. */
export function Toaster({ ...props }: ToasterProps) {
  return (
    <Sonner
      theme="light"
      className="toaster group"
      position="top-right"
      closeButton
      visibleToasts={3}
      toastOptions={{
        classNames: {
          toast:
            'group toast group-[.toaster]:bg-white group-[.toaster]:text-ink group-[.toaster]:border-line group-[.toaster]:shadow-md',
          description: 'group-[.toast]:text-mute',
          actionButton:
            'group-[.toast]:bg-habeas-navy group-[.toast]:text-white',
          cancelButton: 'group-[.toast]:bg-panel group-[.toast]:text-ink-soft',
          success: 'group-[.toaster]:border-emerald-200',
          error: 'group-[.toaster]:border-red-200',
          warning: 'group-[.toaster]:border-amber-200',
          info: 'group-[.toaster]:border-habeas-light/40',
        },
      }}
      style={
        {
          '--normal-bg': '#ffffff',
          '--normal-text': '#0f172a',
          '--normal-border': '#e2e8f0',
          '--success-bg': '#ffffff',
          '--success-border': '#a7f3d0',
          '--error-bg': '#ffffff',
          '--error-border': '#fecaca',
          '--warning-bg': '#ffffff',
          '--warning-border': '#fde68a',
        } as CSSProperties
      }
      {...props}
    />
  )
}
