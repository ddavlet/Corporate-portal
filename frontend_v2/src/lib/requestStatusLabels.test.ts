import { describe, expect, it } from 'vitest'
import {
  MOBILE_STATUS_OPTIONS,
  mobileStatusOptionLabel,
  requestStatusColor,
  requestStatusLabel,
  requestStatusStep,
} from './requestStatusLabels'

describe('requestStatusLabel', () => {
  it.each([
    ['DRAFT', 'Черновик'],
    ['APPROVED', 'Согласована'],
    ['PAYED', 'Оплачена'],
    ['REJECTED', 'Отклонена'],
  ])('names %s the same in the feed and in the card', (status, label) => {
    expect(requestStatusLabel(status, { context: 'feed' })).toBe(label)
    expect(requestStatusLabel(status, { context: 'card', totalSteps: 3 })).toBe(label)
  })

  it.each(['1', '2', '3', '4', '5'])('shows step %s as «На согласовании · шаг N» in the feed', (status) => {
    expect(requestStatusLabel(status, { context: 'feed' })).toBe(`На согласовании · шаг ${status}`)
    expect(requestStatusLabel(status)).toBe(`На согласовании · шаг ${status}`)
  })

  it.each(['1', '2', '3', '4', '5'])('shows step %s as «Шаг N из M» in the card', (status) => {
    expect(requestStatusLabel(status, { context: 'card', totalSteps: 5 })).toBe(`Шаг ${status} из 5`)
  })

  it('falls back to the feed wording in the card without a sensible step count', () => {
    expect(requestStatusLabel('2', { context: 'card' })).toBe('На согласовании · шаг 2')
    expect(requestStatusLabel('3', { context: 'card', totalSteps: 2 })).toBe('На согласовании · шаг 3')
    expect(requestStatusLabel('2', { context: 'feed', totalSteps: 4 })).toBe('На согласовании · шаг 2')
  })

  it('accepts lower case and spaces, keeps an unknown status as it came', () => {
    expect(requestStatusLabel(' payed ')).toBe('Оплачена')
    expect(requestStatusLabel('ARCHIVED')).toBe('ARCHIVED')
    expect(requestStatusLabel('6')).toBe('6')
    expect(requestStatusLabel('')).toBe('—')
    expect(requestStatusLabel(null)).toBe('—')
  })
})

describe('requestStatusStep', () => {
  it('reads the step of an approval status only', () => {
    expect(requestStatusStep('4')).toBe(4)
    expect(requestStatusStep('DRAFT')).toBeNull()
    expect(requestStatusStep('0')).toBeNull()
    expect(requestStatusStep('12')).toBeNull()
  })
})

describe('requestStatusColor', () => {
  it('uses antd preset colours', () => {
    expect(requestStatusColor('REJECTED')).toBe('error')
    expect(requestStatusColor('APPROVED')).toBe('success')
    expect(requestStatusColor('3')).toBe('processing')
    expect(requestStatusColor('PAYED')).toBe('default')
    expect(requestStatusColor('DRAFT')).toBe('default')
    expect(requestStatusColor('???')).toBe('default')
  })
})

describe('MOBILE_STATUS_OPTIONS', () => {
  it('offers every status of the desktop filter once', () => {
    expect(MOBILE_STATUS_OPTIONS.map((o) => o.value)).toEqual([
      'DRAFT',
      '1',
      '2',
      '3',
      '4',
      '5',
      'APPROVED',
      'PAYED',
      'REJECTED',
    ])
    expect(mobileStatusOptionLabel('2')).toBe('Шаг 2')
    expect(mobileStatusOptionLabel('PAYED')).toBe('Оплачена')
    expect(mobileStatusOptionLabel('X')).toBe('X')
  })
})
