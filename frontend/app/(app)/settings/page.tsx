'use client';

import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, Copy, ExternalLink, KeyRound, Link2, MessageCircle, ShieldCheck, Unlink } from 'lucide-react';
import { toast } from 'sonner';

import { PageShell } from '@/components/layout/page-shell';
import { Button } from '@/components/ui/button';
import {
  createTelegramLinkCode,
  disconnectTelegram,
  getTelegramStatus,
} from '@/lib/api/telegram';

const TELEGRAM_BOT_NAME = process.env.NEXT_PUBLIC_TELEGRAM_BOT_NAME ?? 'financeapp_import_bot';

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-white px-4 py-3">
      <span className="text-sm text-slate-500">{label}</span>
      <span className="text-sm font-medium text-slate-900">{value}</span>
    </div>
  );
}

export default function SettingsPage() {
  const queryClient = useQueryClient();

  const statusQuery = useQuery({
    queryKey: ['telegram', 'status'],
    queryFn: getTelegramStatus,
  });

  const linkCodeMutation = useMutation({
    mutationFn: createTelegramLinkCode,
    onSuccess: async (data) => {
      toast.success(`Код привязки готов: ${data.code}`);
      await queryClient.invalidateQueries({ queryKey: ['telegram', 'status'] });
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Не удалось создать код привязки');
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: disconnectTelegram,
    onSuccess: async () => {
      toast.success('Telegram отвязан');
      await queryClient.invalidateQueries({ queryKey: ['telegram', 'status'] });
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Не удалось отвязать Telegram');
    },
  });

  const status = statusQuery.data;
  const pendingCode = status?.pending_code ?? null;
  const pendingCodeExpiresAt = status?.pending_code_expires_at ?? null;

  const expiresLabel = useMemo(() => {
    if (!pendingCodeExpiresAt) return 'Код ещё не создан';
    const date = new Date(pendingCodeExpiresAt);
    if (Number.isNaN(date.getTime())) return 'Код действует ограниченное время';
    return `Действует до ${date.toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })}`;
  }, [pendingCodeExpiresAt]);

  async function handleCopyCode() {
    if (!pendingCode) return;
    try {
      await navigator.clipboard.writeText(pendingCode);
      toast.success('Код скопирован');
    } catch {
      toast.error('Не удалось скопировать код');
    }
  }

  return (
    <PageShell
      title="Настройки"
      description="Управляй подключениями и включай удобные способы загрузки выписок."
    >
      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <section className="rounded-3xl border border-white/60 bg-white/80 p-5 shadow-soft backdrop-blur lg:p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                Интеграции
              </p>
              <div className="flex items-center gap-3">
                <div className="flex size-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
                  <Bot className="size-6" />
                </div>
                <div>
                  <h3 className="text-xl font-semibold text-slate-950">Telegram</h3>
                  <p className="mt-1 text-sm text-slate-500">
                    Подключи Telegram по одноразовому коду, чтобы отправлять выписки прямо боту.
                  </p>
                </div>
              </div>
            </div>

            <div
              className={[
                'rounded-full px-3 py-1 text-xs font-medium',
                status?.connected ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500',
              ].join(' ')}
            >
              {status?.connected ? 'Подключён' : 'Не подключён'}
            </div>
          </div>

          <div className="mt-6 space-y-3">
            <InfoRow label="Бот" value={`@${TELEGRAM_BOT_NAME}`} />
            <InfoRow
              label="Статус"
              value={
                statusQuery.isLoading
                  ? 'Проверяем...'
                  : status?.connected
                    ? 'Аккаунт привязан'
                    : 'Ждёт подключения'
              }
            />
            <InfoRow
              label="Username"
              value={status?.telegram_username ? `@${status.telegram_username}` : 'Ещё не указан'}
            />
            <InfoRow
              label="Telegram ID"
              value={status?.telegram_id ? String(status.telegram_id) : 'Ещё не привязан'}
            />
          </div>

          <div className="mt-6 rounded-2xl border border-slate-100 bg-slate-50 p-4">
            {status?.connected ? (
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <ShieldCheck className="mt-0.5 size-5 text-emerald-600" />
                  <div>
                    <p className="text-sm font-medium text-slate-900">Telegram уже подключён</p>
                    <p className="mt-1 text-sm text-slate-500">
                      Теперь можно открыть бота, отправить PDF, XLSX, XLS или CSV, и затем проверить выписку в приложении.
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap gap-3">
                  <a
                    href={`https://t.me/${TELEGRAM_BOT_NAME}`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-sm font-medium text-white transition hover:opacity-90"
                  >
                    <MessageCircle className="size-4" />
                    Открыть бота
                    <ExternalLink className="size-4" />
                  </a>
                  <Button
                    variant="secondary"
                    onClick={() => disconnectMutation.mutate()}
                    disabled={disconnectMutation.isPending}
                  >
                    <Unlink className="size-4" />
                    Отвязать Telegram
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <KeyRound className="mt-0.5 size-5 text-sky-600" />
                  <div>
                    <p className="text-sm font-medium text-slate-900">Подключение по одноразовому коду</p>
                    <p className="mt-1 text-sm text-slate-500">
                      Получи код привязки, отправь его боту и после подтверждения Telegram подключится к текущему профилю.
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap gap-3">
                  <Button
                    onClick={() => linkCodeMutation.mutate()}
                    disabled={linkCodeMutation.isPending}
                  >
                    <KeyRound className="size-4" />
                    {pendingCode ? 'Обновить код' : 'Получить код привязки'}
                  </Button>

                  <a
                    href={`https://t.me/${TELEGRAM_BOT_NAME}`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
                  >
                    <Link2 className="size-4" />
                    Открыть бота
                    <ExternalLink className="size-4" />
                  </a>
                </div>

                {pendingCode ? (
                  <div className="rounded-2xl border border-sky-100 bg-white p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                          Код привязки
                        </p>
                        <p className="mt-2 font-mono text-3xl font-semibold tracking-[0.22em] text-slate-950">
                          {pendingCode}
                        </p>
                        <p className="mt-2 text-xs text-slate-500">{expiresLabel}</p>
                      </div>
                      <Button variant="secondary" onClick={handleCopyCode}>
                        <Copy className="size-4" />
                        Скопировать
                      </Button>
                    </div>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </section>

        <aside className="rounded-3xl border border-white/60 bg-white/80 p-5 shadow-soft backdrop-blur lg:p-6">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
            Как это работает
          </p>
          <h3 className="text-xl font-semibold text-slate-950">Импорт через Telegram</h3>
          <div className="mt-5 space-y-4 text-sm text-slate-600">
            <div className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3">
              <p className="font-medium text-slate-900">1. Получи код</p>
              <p className="mt-1">
                Нажми «Получить код привязки» и дождись появления одноразового кода на этой странице.
              </p>
            </div>
            <div className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3">
              <p className="font-medium text-slate-900">2. Отправь код боту</p>
              <p className="mt-1">
                Можно отправить код обычным сообщением или командой вида <span className="font-mono">/start КОД</span>.
              </p>
            </div>
            <div className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3">
              <p className="font-medium text-slate-900">3. Загрузи выписку</p>
              <p className="mt-1">
                После привязки бот принимает PDF, CSV, XLSX и XLS, а выписка уходит в систему импорта.
              </p>
            </div>
          </div>
        </aside>
      </div>
    </PageShell>
  );
}