import type { ReactNode } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { IconX } from '@tabler/icons-react'

export function Modal({
  title,
  children,
  onClose,
}: {
  title: string
  children: ReactNode
  onClose: () => void
}) {
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content className="modal" aria-describedby={undefined}>
          <div className="cardHead">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close className="iconButton" aria-label="Close">
              <IconX size={18} />
            </Dialog.Close>
          </div>
          <div className="cardBody">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
