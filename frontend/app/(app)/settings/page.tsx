'use client';

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Settings } from 'lucide-react';
import { toast } from 'sonner';
import { getUserSettings, updateUserSettings } from '@/lib/api/user-settings';

const MIN_PCT = 5;
const MAX_PCT = 50;
const STEP = 5;

const EXAMPLE_EXPENSES = 100_000; // reference monthly expenses for the explainer

function formatRub(value: number) {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(value);
}

export default function SettingsPage() {
  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery({
    queryKey: ['user-settings'],
    queryFn: getUserSettings,
    staleTime: 1000 * 60 * 5,
  });

  // Slider value in whole percent (5–50)
  const [sliderValue, setSliderValue] = useState(20);

  useEffect(() => {
    if (settings) {
      setSliderValue(Math.round(settings.large_purchase_threshold_pct * 100));
    }
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: () =>
      updateUserSettings({ large_purchase_threshold_pct: sliderValue / 100 }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-settings'] });
      toast.success('Настройки сохранены');
    },
    onError: () => {
      toast.error('Не удалось сохранить настройки');
    },
  });

  const isDirty =
    settings !== undefined &&
    sliderValue !== Math.round(settings.large_purchase_threshold_pct * 100);

  const exampleThreshold = Math.round((sliderValue / 100) * EXAMPLE_EXPENSES);

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      {/* Header */}
      <div className="mb-8 flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-2xl bg-slate-100">
          <Settings className="size-5 text-slate-600" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Настройки</h1>
          <p className="text-sm text-slate-500">Параметры учёта</p>
        </div>
      </div>

      {/* Card */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-base font-semibold text-slate-800">Порог крупной покупки</h2>
        <p className="mt-1 text-sm leading-relaxed text-slate-500">
          Если сумма разовой покупки превышает этот процент от среднемесячных расходов, приложение
          предложит учесть её отдельно — чтобы она не исказила средние показатели.
        </p>

        {isLoading ? (
          <div className="mt-6 h-10 animate-pulse rounded-lg bg-slate-100" />
        ) : (
          <div className="mt-6">
            {/* Value display */}
            <div className="mb-4">
              <span className="text-4xl font-bold text-slate-900">{sliderValue}%</span>
              <span className="ml-2 text-sm text-slate-400">от среднемесячных расходов</span>
            </div>

            {/* Slider */}
            <input
              type="range"
              min={MIN_PCT}
              max={MAX_PCT}
              step={STEP}
              value={sliderValue}
              onChange={(e) => setSliderValue(Number(e.target.value))}
              className="w-full accent-slate-900"
            />

            {/* Tick labels */}
            <div className="mt-1 flex justify-between text-xs text-slate-400">
              {Array.from(
                { length: (MAX_PCT - MIN_PCT) / STEP + 1 },
                (_, i) => MIN_PCT + i * STEP,
              ).map((v) => (
                <span key={v}>{v}%</span>
              ))}
            </div>

            {/* Explanation */}
            <div className="mt-5 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
              <strong>Например:</strong> при среднемесячных расходах {formatRub(EXAMPLE_EXPENSES)}{' '}
              крупной считается покупка от{' '}
              <strong className="text-slate-800">{formatRub(exampleThreshold)}</strong>.
            </div>

            {/* Save button */}
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                disabled={!isDirty || saveMutation.isPending}
                onClick={() => saveMutation.mutate()}
                className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {saveMutation.isPending ? 'Сохраняем...' : 'Сохранить'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
