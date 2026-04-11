export type CreditRepaymentInput = {
  id: number;
  name: string;
  balance: number;
  rate: number;
  minPayment: number;
};

type CreditRepaymentState = CreditRepaymentInput & {
  balance: number;
};

export type RepaymentSimulation = {
  months: number;
  totalInterest: number;
  order: string[];
};

export type RepaymentSortFn = (a: CreditRepaymentState, b: CreditRepaymentState) => number;

const EPSILON = 0.01;
const MAX_MONTHS = 480;

function normalizeCredits(credits: CreditRepaymentInput[]) {
  return credits
    .map((credit) => ({
      ...credit,
      balance: Math.max(0, Number(credit.balance) || 0),
      rate: Math.max(0, Number(credit.rate) || 0),
      minPayment: Math.max(0, Number(credit.minPayment) || 0),
    }))
    .filter((credit) => credit.balance > EPSILON);
}

export function simulateRepayment(
  credits: CreditRepaymentInput[],
  extraBudget: number,
  sortFn: RepaymentSortFn,
): RepaymentSimulation {
  const states: CreditRepaymentState[] = normalizeCredits(credits).map((credit) => ({ ...credit }));

  if (states.length === 0) {
    return { months: 0, totalInterest: 0, order: [] };
  }

  const orderedNames = [...states]
    .sort((a, b) => sortFn(a, b) || a.id - b.id)
    .map((credit) => credit.name);

  const basePaymentPool =
    states.reduce((sum, credit) => sum + credit.minPayment, 0) + Math.max(0, Number(extraBudget) || 0);

  let months = 0;
  let totalInterest = 0;

  while (months < MAX_MONTHS && states.some((credit) => credit.balance > EPSILON)) {
    months += 1;

    for (const credit of states) {
      if (credit.balance <= EPSILON) continue;
      const interest = credit.balance * (credit.rate / 100 / 12);
      credit.balance += interest;
      totalInterest += interest;
    }

    let paymentPool = basePaymentPool;

    for (const credit of states) {
      if (credit.balance <= EPSILON) continue;
      const minDue = Math.min(credit.minPayment, credit.balance);
      if (minDue <= 0) continue;
      credit.balance -= minDue;
      paymentPool -= minDue;
      if (credit.balance <= EPSILON) {
        credit.balance = 0;
      }
    }

    const activeCredits = states
      .filter((credit) => credit.balance > EPSILON)
      .sort((a, b) => sortFn(a, b) || a.id - b.id);

    for (const credit of activeCredits) {
      if (paymentPool <= EPSILON) break;
      const extraPayment = Math.min(paymentPool, credit.balance);
      credit.balance -= extraPayment;
      paymentPool -= extraPayment;
      if (credit.balance <= EPSILON) {
        credit.balance = 0;
      }
    }
  }

  return {
    months,
    totalInterest,
    order: orderedNames,
  };
}
