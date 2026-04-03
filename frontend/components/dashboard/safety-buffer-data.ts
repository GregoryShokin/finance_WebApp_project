import type { GoalWithProgress } from '@/types/goal';

export type SafetyBufferMetrics = {
  savedAmount: number;
  targetAmount: number;
  avgMonthlyExpenses: number;
  progressPercent: number;
  coverageMonths: number;
  message: string;
};

const SYSTEM_GOAL_KEY = 'safety_buffer';

function buildMessage(progressPercent: number) {
  if (progressPercent < 20) {
    return 'Резерв только формируется: подушка пока почти не защищает от финансовых рисков.';
  }

  if (progressPercent < 60) {
    return 'Подушка формируется, но пока не обеспечивает достаточный запас прочности.';
  }

  if (progressPercent < 100) {
    return 'Подушка близка к рекомендуемому уровню, но резерв ещё не полностью собран.';
  }

  return 'Подушка сформирована: у вас есть рекомендуемый резерв на 5 месяцев расходов.';
}

export function getSafetyBufferMetrics(goals: GoalWithProgress[]): SafetyBufferMetrics | null {
  const safetyGoal = goals.find((goal) => goal.system_key === SYSTEM_GOAL_KEY);
  if (!safetyGoal) {
    return null;
  }

  const savedAmount = Number(safetyGoal.saved ?? 0);
  const targetAmount = Number(safetyGoal.target_amount ?? 0);
  const avgMonthlyExpenses = targetAmount > 0 ? targetAmount / 5 : 0;

  if (targetAmount <= 0 || avgMonthlyExpenses <= 0) {
    return null;
  }

  const progressPercent = (savedAmount / targetAmount) * 100;
  const coverageMonths = savedAmount / avgMonthlyExpenses;

  return {
    savedAmount,
    targetAmount,
    avgMonthlyExpenses,
    progressPercent,
    coverageMonths,
    message: buildMessage(progressPercent),
  };
}