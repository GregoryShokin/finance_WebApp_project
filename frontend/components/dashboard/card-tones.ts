import type { DisciplineZone, DtiZone, FiScoreZone, FiZone, HealthCardTone, LeverageZone, SavingsRateZone } from '@/types/financial-health';

export function savingsTone(zone: SavingsRateZone): HealthCardTone {
  if (zone === 'good') return 'good';
  if (zone === 'normal') return 'warning';
  return 'danger';
}

export function dtiTone(zone: DtiZone): HealthCardTone {
  if (zone === 'normal') return 'good';
  if (zone === 'acceptable') return 'warning';
  return 'danger';
}

export function leverageTone(zone: LeverageZone): HealthCardTone {
  if (zone === 'normal') return 'good';
  if (zone === 'moderate') return 'warning';
  return 'danger';
}

export function disciplineTone(zone: DisciplineZone): HealthCardTone {
  if (zone === 'excellent' || zone === 'good') return 'good';
  if (zone === 'medium') return 'warning';
  return 'danger';
}

export function fiTone(zone: FiZone): HealthCardTone {
  if (zone === 'free' || zone === 'on_way') return 'good';
  if (zone === 'partial') return 'warning';
  return 'danger';
}

export function fiScoreTone(zone: FiScoreZone): HealthCardTone {
  if (zone === 'freedom' || zone === 'on_way') return 'good';
  if (zone === 'growth') return 'warning';
  return 'danger';
}