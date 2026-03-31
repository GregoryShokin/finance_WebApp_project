import { Card } from '@/components/ui/card';
import { TransactionCard } from '@/components/transactions/transaction-card';
import { TransactionForm } from '@/components/transactions/transaction-form';
import type { Account } from '@/types/account';
import type { Category, CategoryKind } from '@/types/category';
import type { CreateTransactionPayload, Transaction } from '@/types/transaction';
import type { Counterparty } from '@/types/counterparty';
import type { GoalWithProgress } from '@/types/goal';

export function TransactionsList({
  transactions,
  accounts,
  categories,
  counterparties,
  goals = [],
  onEdit,
  onDelete,
  onCancelDelete,
  deletingId,
  pendingDeleteIds,
  editingTransaction,
  isSubmittingEdit,
  onSubmitEdit,
  onCancelEdit,
  onCreateCategoryRequest,
  onCreateAccountRequest,
  onCreateCounterpartyRequest,
  onDeleteCounterpartyRequest,
}: {
  transactions: Transaction[];
  accounts: Account[];
  categories: Category[];
  counterparties?: Counterparty[];
  goals?: GoalWithProgress[];
  onEdit: (transaction: Transaction) => void;
  onDelete?: (transaction: Transaction) => void;
  onCancelDelete?: (transactionId: number) => void;
  deletingId?: number | null;
  pendingDeleteIds?: number[];
  editingTransaction?: Transaction | null;
  isSubmittingEdit?: boolean;
  onSubmitEdit?: (values: CreateTransactionPayload) => void;
  onCancelEdit?: () => void;
  onCreateCategoryRequest?: (payload: { name: string; kind: CategoryKind }) => void;
  onCreateAccountRequest?: (payload: { name: string }) => void;
  onCreateCounterpartyRequest?: (payload: { name: string; opening_balance_kind: 'receivable' | 'payable' }) => void;
  onDeleteCounterpartyRequest?: (counterparty: Counterparty) => void;
}) {
  const pendingSet = new Set(pendingDeleteIds ?? []);

  return (
    <div className="grid gap-4">
      {transactions.map((transaction) => {
        const isEditing = editingTransaction?.id === transaction.id;

        return (
          <div key={transaction.id} className="grid gap-3">
            <TransactionCard
              transaction={transaction}
              accounts={accounts}
              categories={categories}
              onEdit={onEdit}
              onDelete={onDelete}
              onCancelDelete={onCancelDelete}
              isDeletePending={pendingSet.has(transaction.id)}
              isDeleting={deletingId === transaction.id}
              isEditing={isEditing}
            />

            {isEditing && onSubmitEdit && onCancelEdit ? (
              <Card className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft lg:p-6">
                <div className="mb-5 flex flex-col gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h3 className="text-lg font-semibold text-slate-950">Редактирование транзакции</h3>
                    <p className="mt-1 text-sm text-slate-500">
                      Форма открыта прямо под выбранной транзакцией. После сохранения список обновится автоматически.
                    </p>
                  </div>
                </div>

                <TransactionForm
                  initialData={editingTransaction}
                  accounts={accounts}
                  categories={categories}
                  counterparties={counterparties ?? []}
                  goals={goals}
                  isSubmitting={isSubmittingEdit}
                  onCancel={onCancelEdit}
                  onSubmit={onSubmitEdit}
                  onCreateAccountRequest={onCreateAccountRequest}
                  onCreateCategoryRequest={onCreateCategoryRequest}
                  onCreateCounterpartyRequest={onCreateCounterpartyRequest}
                  onDeleteCounterpartyRequest={onDeleteCounterpartyRequest}
                />
              </Card>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
