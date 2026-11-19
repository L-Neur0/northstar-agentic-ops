/**
 * Tests for the cluster picker (spec 23 §3.9; AC-23.36, AC-23.37).
 * Why: shows the company's configured clusters from
 * `GET /api/taxonomy`; the dialog stays open and locked while the choice is saved.
 * Rules: the parent owns the save and closes the picker only on success.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ClusterPicker } from './ClusterPicker'
import { renderWithProviders } from '../../test/render'
import { createFakeApi } from '../../services/fakeApi'
import { ApiError } from '../../services/api'

const picker = (over: Partial<Parameters<typeof ClusterPicker>[0]> = {}, api = createFakeApi({ delayMs: 0, persist: false })) => {
  const onSelect = vi.fn()
  const onClose = vi.fn()
  renderWithProviders(
    <ClusterPicker currentCode="FIN" saving={false} error={null} onSelect={onSelect} onClose={onClose} {...over} />,
    { api },
  )
  return { onSelect, onClose }
}

describe('ClusterPicker (AC-23.36)', () => {
  it('lists the clusters with name, code and description and marks the current one', async () => {
    picker()
    const fin = await screen.findByRole('button', { name: /Finance \(FIN\)/ })
    expect(fin).toHaveAttribute('aria-pressed', 'true')
    expect(fin).toHaveTextContent('Planning, recording and reporting money')
    expect(screen.getByRole('button', { name: /IT & Security \(IT\)/ })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('dialog', { name: 'Pick a cluster' })).toBeInTheDocument()
  })

  it('hands the code to onSelect', async () => {
    const { onSelect } = picker()
    await userEvent.click(await screen.findByRole('button', { name: /Procurement \(PRO\)/ }))
    expect(onSelect).toHaveBeenCalledWith('PRO')
  })

  it('shows an error with Retry when the taxonomy does not load', async () => {
    const api = createFakeApi({ delayMs: 0, persist: false })
    api.getTaxonomy = vi.fn().mockRejectedValueOnce(new ApiError(0, 'network', '')).mockResolvedValue({ clusters: [] })
    picker({}, api)
    expect(await screen.findByText(/could not load the clusters/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(api.getTaxonomy).toHaveBeenCalledTimes(2)
  })
})

describe('saving (AC-23.37)', () => {
  it('locks every button and ignores Escape while saving', async () => {
    const { onClose } = picker({ saving: true })
    const fin = await screen.findByRole('button', { name: /Finance \(FIN\)/ })
    expect(fin).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    await userEvent.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('shows the unknown-cluster message inside the dialog', async () => {
    picker({ error: 'That cluster is no longer available. Please pick another.' })
    expect(await screen.findByText('That cluster is no longer available. Please pick another.')).toBeInTheDocument()
  })

  it('closes with Escape when not saving', async () => {
    const { onClose } = picker()
    await screen.findByRole('button', { name: /Finance \(FIN\)/ })
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})
