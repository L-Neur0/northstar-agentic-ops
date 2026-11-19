/**
 * Tests for the five process sections of "Your process" (spec 23 §3.8.2–6; AC-23.28–23.31).
 * Why: the card is how the expert sees the form fill up; each field shows its server status with
 * an icon and words (never colour alone), its formatted value, and proposals with their quote.
 * Rules: sections follow the field view phase; counts tally `complete` views only.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProcessCard } from './ProcessCard'
import { defaultSections } from './sectionState'
import { emptyProfile, processViews, view } from '../../test/fixtures/sessions'
import type { FieldView } from '../../types/process-discovery'

function renderCard(views: FieldView[], over: Partial<Parameters<typeof ProcessCard>[0]> = {}) {
  const profile = emptyProfile()
  profile.department = 'Finance control'
  profile.user_function = 'Cost controller'
  profile.region = 'Germany'
  profile.process.name = 'Chasing site managers'
  profile.process.volume = { count: 400, period: '', raw: '' }
  profile.process.sensitive_data = [{ none: true }]
  profile.process.process_owner = { role: '', none_identified: true }
  profile.process.trigger = 'Ledger closes'
  const onToggle = vi.fn()
  render(
    <ProcessCard
      profile={profile}
      fieldViews={views}
      sections={defaultSections()}
      onToggle={onToggle}
      canPickCluster
      onPickCluster={vi.fn()}
      clusterProposal={null}
      {...over}
    />,
  )
  return { onToggle }
}

const field = (label: string) => screen.getByText(label, { selector: '[data-field-label]' }).closest('li') as HTMLElement

describe('ProcessCard (AC-23.28)', () => {
  it('shows five sections with counts, aria-expanded and aria-controls', async () => {
    const { onToggle } = renderCard(processViews({ department: 'complete', user_function: 'complete' }))
    const headers = ['About you', 'The process', 'Boundaries', 'Measures', 'Number of steps'].map((t) =>
      screen.getByRole('button', { name: new RegExp(`^${t}`) }),
    )
    expect(headers[0]).toHaveTextContent('2/3')
    expect(headers[3]).toHaveTextContent('0/6')
    for (const h of headers) {
      expect(h).toHaveAttribute('aria-expanded', 'true')
      expect(document.getElementById(h.getAttribute('aria-controls') ?? '')).not.toBeNull()
    }
    await userEvent.click(headers[1])
    expect(onToggle).toHaveBeenCalledWith('find')
  })
})

describe('field rows (AC-23.29, AC-23.30)', () => {
  it('shows an icon label and words for every status, with the reason for partial and invalid', () => {
    renderCard([
      view('department', 'complete'),
      view('user_function', 'skipped'),
      view('region', 'invalid', { reason: '"Germany" is not one of the regions.' }),
      view('process.volume', 'partial', { reason: 'Volume still needs: period.' }),
      view('process.trigger', 'deferred'),
      view('process.end_result', 'given_up'),
      view('process.value_at_end', 'empty'),
    ])
    expect(within(field('Department')).getByRole('img', { name: 'Complete' })).toBeInTheDocument()
    expect(within(field('Department')).getByText('Finance control')).toBeInTheDocument()
    expect(within(field('Role')).getByText('Skipped')).toBeInTheDocument()
    expect(within(field('Region')).getByRole('img', { name: 'Needs a fix' })).toBeInTheDocument()
    expect(within(field('Region')).getByText('"Germany" is not one of the regions.')).toBeInTheDocument()
    expect(within(field('Volume')).getByRole('img', { name: 'Partly answered' })).toBeInTheDocument()
    expect(within(field('Volume')).getByText('Volume still needs: period.')).toBeInTheDocument()
    expect(within(field('Trigger')).getByText('Asked again later')).toBeInTheDocument()
    expect(within(field('End result')).getByText('Left open')).toBeInTheDocument()
    expect(within(field('Who uses the result')).getByText('Not yet described')).toBeInTheDocument()
    expect(within(field('Who uses the result')).getByRole('img', { name: 'Not answered yet' })).toBeInTheDocument()
  })

  it('shows "None" for a none row and a none_identified owner', () => {
    renderCard([view('process.sensitive_data', 'complete'), view('process.process_owner', 'complete')])
    expect(within(field('Sensitive data or regulation')).getByText('None')).toBeInTheDocument()
    expect(within(field('Process owner')).getByText('None')).toBeInTheDocument()
  })

  it('marks document and specialist values with a source chip', () => {
    renderCard([
      view('department', 'complete', { source: 'document', documentName: 'cost-guide.pdf' }),
      view('user_function', 'complete', { source: 'specialist' }),
    ])
    expect(within(field('Department')).getByText('from cost-guide.pdf')).toBeInTheDocument()
    expect(within(field('Role')).getByText('edited by IT')).toBeInTheDocument()
  })
})

describe('proposals (AC-23.31)', () => {
  it('shows Proposed, the source, the quote and the hint, and does not count it', () => {
    renderCard([
      view('process.name', 'proposed', { source: 'expert', quote: 'I chase the site managers every Friday' }),
      view('process.cluster', 'empty'),
      view('process.trigger', 'proposed', { source: 'document', documentName: 'notes.docx', quote: 'Starts when the ledger closes' }),
    ])
    const name = field('Process name')
    expect(within(name).getByText('Proposed')).toBeInTheDocument()
    expect(within(name).getByText('from your idea')).toBeInTheDocument()
    expect(within(name).getByText('I chase the site managers every Friday').closest('blockquote')).not.toBeNull()
    expect(within(name).getByText('Say yes in the chat to confirm, or give the right answer.')).toBeInTheDocument()
    expect(within(field('Trigger')).getByText('from notes.docx')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^The process/ })).toHaveTextContent('0/2')
  })
})

describe('cluster row', () => {
  it('offers Pick cluster, Change cluster, and shows the suggestion', async () => {
    const onPick = vi.fn()
    renderCard([view('process.cluster', 'empty')], {
      onPickCluster: onPick,
      clusterProposal: { code: 'FIN', name: 'Finance', description: '' },
    })
    expect(screen.getByText('Suggested: Finance (FIN). Answer in the chat, or pick another.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Pick cluster' }))
    expect(onPick).toHaveBeenCalled()
  })

  it('hides the link when the session is not active', () => {
    renderCard([view('process.cluster', 'empty')], { canPickCluster: false })
    expect(screen.queryByRole('button', { name: /cluster/i })).not.toBeInTheDocument()
  })
})
