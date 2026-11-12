import type { CSSProperties } from 'react'
import { Timeline, Typography, theme, type GlobalToken } from 'antd'
import {
  formatDateTime,
  getDecisionColor,
  translateDecision,
  translateStepType,
  type ApprovalItem,
} from './RequestDetailModal'
import { mobileToneTextColor } from './mobileActionsTheme'
import { isNotificationApprovalStep } from './requestApprovalSteps'

/**
 * Text colour of a decision on the phone: the dot keeps the desktop tag colour (getDecisionColor), the words take a
 * darker shade of the same palette (mobileToneTextColor), so 13–15 px text stays above 4.5:1 on white. A step the queue
 * has not reached yet is grey.
 */
function decisionTextStyle(decision: string | null | undefined, notStarted: boolean, token: GlobalToken): CSSProperties {
  if (notStarted) return { color: token.colorTextSecondary }
  const color = getDecisionColor(decision)
  if (color === 'green') return { color: mobileToneTextColor('success', token) }
  if (color === 'red') return { color: mobileToneTextColor('error', token) }
  if (color === 'orange') return { color: mobileToneTextColor('warning', token) }
  return { color: token.colorTextSecondary }
}

function timelineDotColor(decision: string | null | undefined, notStarted: boolean): string {
  if (notStarted) return 'gray'
  const color = getDecisionColor(decision)
  return !color || color === 'default' ? 'gray' : color
}

/**
 * Approvals of a request as one vertical timeline in step order: step and its kind, the approver, the decision, its
 * date and comment (the rejection reason). A pending step after the active one (`activeApprovalStep`, the smallest
 * pending step) is «Не начат»: the queue has not reached it. Built on the helpers of the desktop card; the desktop
 * groups stay as they are.
 */
export function RequestApprovalsTimelineWidget({
  approvals,
  activeApprovalStep = null,
}: {
  approvals: ApprovalItem[]
  activeApprovalStep?: number | null
}) {
  const { token } = theme.useToken()
  if (!approvals.length) {
    return <Typography.Text style={{ color: token.colorTextSecondary }}>Согласований пока нет</Typography.Text>
  }
  const sorted = [...approvals].sort((a, b) => a.step - b.step || a.id - b.id)
  return (
    <div data-testid="request-approvals-timeline">
      <Timeline
        items={sorted.map((item) => {
          const pending = String(item.decision || '').toLowerCase() === 'pending'
          const notStarted = pending && activeApprovalStep != null && item.step > activeApprovalStep
          // The desktop helper leaves «notification» untranslated; the phone names it.
          const stepKind = isNotificationApprovalStep(item) ? 'уведомление' : translateStepType(item.step_type)
          return {
            key: item.id,
            color: timelineDotColor(item.decision, notStarted),
            children: (
              <div
                style={{ display: 'grid', gap: 2, minWidth: 0 }}
                data-testid={`approval-${item.id}`}
                data-state={notStarted ? 'not-started' : pending ? 'pending' : 'decided'}
              >
                <Typography.Text style={{ fontSize: 13, color: token.colorTextSecondary }}>
                  {`Шаг ${item.step}${stepKind ? ` · ${stepKind}` : ''}`}
                </Typography.Text>
                <Typography.Text style={{ overflowWrap: 'anywhere' }}>
                  {item.approver_username || 'Согласующий не определён'}
                </Typography.Text>
                <Typography.Text
                  strong
                  data-testid={`approval-${item.id}-decision`}
                  style={decisionTextStyle(item.decision, notStarted, token)}
                >
                  {notStarted ? 'Не начат' : translateDecision(item.decision)}
                  {!pending && item.decided_at ? (
                    <span style={{ fontWeight: 400, color: token.colorTextSecondary }}> · {formatDateTime(item.decided_at)}</span>
                  ) : null}
                </Typography.Text>
                {!pending && item.comment?.trim() ? (
                  <Typography.Text style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{item.comment}</Typography.Text>
                ) : null}
              </div>
            ),
          }
        })}
      />
    </div>
  )
}
