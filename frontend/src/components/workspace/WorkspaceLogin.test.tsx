/**
 * Tests for the workspace login card (spec 23 §19.2; AC-23.107, AC-23.109; AC-23.143, amended
 * 2026-11-20 (open workspace): with `open` the card asks for the name only).
 * Why: the login is the only door to the workspace; it must refuse blank input, say clearly why a
 * code did not work, and store nothing for an engineer.
 * What: the card with the fake API (codes `demo-specialist`, `demo-engineer`) and stubs.
 * Must not: start a real server.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WorkspaceLogin } from './WorkspaceLogin'
import { renderWithProviders } from '../../test/render'
import { WORKSPACE_TOKEN_KEY } from '../../access/workspaceToken'
import { createFakeApi } from '../../services/fakeApi'

afterEach(() => sessionStorage.clear())

const setup = () => {
  const onLoggedIn = vi.fn()
  renderWithProviders(<WorkspaceLogin onLoggedIn={onLoggedIn} />)
  return { onLoggedIn, user: userEvent.setup() }
}

describe('blank fields (AC-23.107)', () => {
  it('Open workspace is disabled until both fields have text; the name stops at 40 characters', async () => {
    const { user } = setup()
    const button = screen.getByRole('button', { name: 'Open workspace' })
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText('Access code'), 'demo-specialist')
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText('Your name'), '   ')
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText('Your name'), 'x'.repeat(50))
    expect((screen.getByLabelText('Your name') as HTMLInputElement).value).toHaveLength(40)
    expect(button).toBeEnabled()
    expect(screen.getByLabelText('Access code')).toHaveAttribute('type', 'password')
    expect(screen.getByText('Shown in the log next to what you open.')).toBeInTheDocument()
  })
})

describe('outcomes (AC-23.108, AC-23.109)', () => {
  it('a specialist login is stored and handed to the page', async () => {
    const { user, onLoggedIn } = setup()
    await user.type(screen.getByLabelText('Access code'), 'demo-specialist')
    await user.type(screen.getByLabelText('Your name'), 'Maria')
    await user.click(screen.getByRole('button', { name: 'Open workspace' }))
    expect(onLoggedIn).toHaveBeenCalledWith(expect.objectContaining({ role: 'specialist', name: 'Maria' }))
    expect(sessionStorage.getItem(WORKSPACE_TOKEN_KEY)).not.toContain('demo-specialist')
  })

  it('an engineer login stores nothing and shows the engineer sentence', async () => {
    const { user, onLoggedIn } = setup()
    await user.type(screen.getByLabelText('Access code'), 'demo-engineer')
    await user.type(screen.getByLabelText('Your name'), 'Ed')
    await user.click(screen.getByRole('button', { name: 'Open workspace' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This code is for engineers. Their screens are not available yet.')
    expect(onLoggedIn).not.toHaveBeenCalled()
    expect(sessionStorage.getItem(WORKSPACE_TOKEN_KEY)).toBeNull()
  })

  it('a wrong code shows the sentence, clears and focuses the code, keeps the name', async () => {
    const { user } = setup()
    await user.type(screen.getByLabelText('Access code'), 'wrong')
    await user.type(screen.getByLabelText('Your name'), 'Maria')
    await user.click(screen.getByRole('button', { name: 'Open workspace' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The access code is not valid.')
    expect(screen.getByLabelText('Access code')).toHaveValue('')
    expect(screen.getByLabelText('Access code')).toHaveFocus()
    expect(screen.getByLabelText('Your name')).toHaveValue('Maria')
  })
})

describe('open workspace (AC-23.143, amended 2026-11-20)', () => {
  const OPEN_LINE = 'Open demo workspace: anyone with the link can read sessions. Deleting is switched off.'

  it('asks for the name only, says the workspace is open, and logs in as specialist', async () => {
    const onLoggedIn = vi.fn()
    const api = createFakeApi({ delayMs: 0, persist: false, workspaceOpen: true })
    const login = vi.spyOn(api, 'workspaceLogin')
    renderWithProviders(<WorkspaceLogin open onLoggedIn={onLoggedIn} />, { api })
    const user = userEvent.setup()
    expect(screen.queryByLabelText('Access code')).toBeNull()
    expect(screen.getByText(OPEN_LINE)).toBeInTheDocument()
    const button = screen.getByRole('button', { name: 'Open workspace' })
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText('Your name'), 'Maria')
    expect(button).toBeEnabled()
    await user.click(button)
    expect(login).toHaveBeenCalledWith('', 'Maria')
    expect(onLoggedIn).toHaveBeenCalledWith(expect.objectContaining({ role: 'specialist', name: 'Maria' }))
    expect(sessionStorage.getItem(WORKSPACE_TOKEN_KEY)).toContain('specialist')
  })

  it('closed (the default) keeps the code field and has no open line', () => {
    setup()
    expect(screen.getByLabelText('Access code')).toBeInTheDocument()
    expect(screen.queryByText(OPEN_LINE)).toBeNull()
  })
})
