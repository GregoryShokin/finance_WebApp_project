'use client';

import { useEffect, useState } from 'react';
import { Card } from '@/components/ui/card';

/**
 * Псевдо-прогресс при построении preview.
 *
 * Реального прогресса с бэка нет — build_preview синхронный, ответ приходит
 * только когда всё готово. Этот компонент показывает анимированный бар по
 * нелинейной кривой, чтобы пользователь видел: процесс идёт, не завис.
 *
 * Кривая подобрана под наблюдаемое время на средней выписке (~60с на 600 строк):
 *   0–30%: за первые ~5с (parsing PDF / загрузка таблиц)
 *   30–70%: ~25с (нормализация строк)
 *   70–90%: ~20с (transfer matcher + refund matcher)
 *   90–98%: «висит» до ответа сервера, чтобы не упереться в 100% слишком рано
 *
 * Когда ответ приходит — родитель размонтирует компонент и покажет реальный
 * результат. Если запрос идёт дольше ожидания — бар застревает на 98%, что
 * лучше, чем «полный 100%, но всё ещё ждём».
 */

const STAGES: Array<{ untilPct: number; label: string }> = [
  { untilPct: 30, label: 'Извлекаем строки из выписки…' },
  { untilPct: 60, label: 'Нормализуем описания и суммы…' },
  { untilPct: 75, label: 'Применяем правила категоризации…' },
  { untilPct: 90, label: 'Ищем парные переводы между сессиями…' },
  { untilPct: 98, label: 'Ищем парные возвраты внутри выписки…' },
];

export function PreviewProgressCard({ rowCount }: { rowCount: number | null }) {
  const [pct, setPct] = useState(0);
  const [startedAt] = useState(() => Date.now());
  const [stuck, setStuck] = useState(false);

  // После 90с бар признаётся «застрявшим» — обычно это означает, что фронт
  // потерял запрос (HMR, network abort, браузер сбросил коннект). Без этой
  // ветки пользователь сидит часами и думает что pipeline тяжёлый, тогда как
  // на бэке вообще ничего не происходит.
  const STUCK_AFTER_MS = 90_000;

  useEffect(() => {
    // Пересчитываем процент каждые 200 мс по нелинейной кривой:
    // при малом elapsed растём быстро, при большом — экспоненциально замедляемся
    // и асимптотически приближаемся к 98%. Базовая длительность подстроена под
    // размер выписки: ~60с на 600 строк, ~10с на 50 строк.
    const expectedMs = Math.min(120_000, Math.max(8_000, (rowCount ?? 200) * 100));
    const tick = () => {
      const elapsed = Date.now() - startedAt;
      const k = 3 / expectedMs;
      const progress = (1 - Math.exp(-k * elapsed)) * 98;
      setPct(progress);
      if (elapsed > STUCK_AFTER_MS) setStuck(true);
    };
    tick();
    const id = setInterval(tick, 200);
    return () => clearInterval(id);
  }, [rowCount, startedAt]);

  const currentStage =
    STAGES.find((s) => pct < s.untilPct) ?? STAGES[STAGES.length - 1];

  return (
    <Card className="rounded-3xl bg-white p-6 shadow-soft">
      <div className="flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-2xl bg-indigo-50">
          <span className="text-xl">⚙️</span>
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold text-slate-900">Строим preview</h3>
          <p className="mt-0.5 truncate text-sm text-slate-500" title={currentStage.label}>
            {currentStage.label}
          </p>
        </div>
        <span className="shrink-0 text-sm font-semibold tabular-nums text-slate-700">
          {Math.round(pct)}%
        </span>
      </div>

      <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-indigo-400 transition-[width] duration-200 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>

      {stuck ? (
        <div className="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <span className="text-base leading-none">⚠️</span>
          <div className="flex-1">
            <p className="font-medium">Что-то пошло не так — запрос завис.</p>
            <p className="mt-0.5 text-amber-800">
              Скорее всего фронт потерял соединение (например, после hot-reload).
              Обнови страницу: на бэке preview либо уже готов, либо запустится
              заново.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-2 rounded-md bg-amber-200 px-3 py-1 text-xs font-medium text-amber-900 hover:bg-amber-300"
            >
              Обновить страницу
            </button>
          </div>
        </div>
      ) : (
        <p className="mt-3 text-xs text-slate-400">
          Это быстрее в небольших выписках. На 500+ строк может занять до минуты —
          идёт нормализация, поиск переводов и парных возвратов.
        </p>
      )}
    </Card>
  );
}
