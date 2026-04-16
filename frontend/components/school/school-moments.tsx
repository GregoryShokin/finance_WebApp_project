'use client';

import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Info, Lightbulb } from 'lucide-react';
import { getSchoolMoments, type SchoolMoment } from '@/lib/api/school';

const SEVERITY_STYLES: Record<string, string> = {
  alert: 'border-l-4 border-l-red-500 bg-red-50',
  warning: 'border-l-4 border-l-yellow-500 bg-yellow-50',
  info: 'border-l-4 border-l-blue-500 bg-blue-50',
};

const SEVERITY_ICON: Record<string, typeof AlertTriangle> = {
  alert: AlertTriangle,
  warning: Lightbulb,
  info: Info,
};

const SEVERITY_ICON_COLOR: Record<string, string> = {
  alert: 'text-red-500',
  warning: 'text-yellow-600',
  info: 'text-blue-500',
};

function MomentCard({ moment, compact }: { moment: SchoolMoment; compact?: boolean }) {
  const Icon = SEVERITY_ICON[moment.severity] ?? Info;
  const iconColor = SEVERITY_ICON_COLOR[moment.severity] ?? 'text-blue-500';
  const style = SEVERITY_STYLES[moment.severity] ?? SEVERITY_STYLES.info;

  return (
    <div className={`rounded-lg p-3 ${style}`}>
      <div className="flex items-start gap-2">
        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${iconColor}`} />
        <div className="min-w-0">
          <div className="text-sm font-medium text-slate-800">{moment.title}</div>
          {!compact ? (
            <p className="mt-0.5 text-xs text-slate-600">{moment.message}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

interface SchoolMomentsProps {
  maxItems?: number;
  compact?: boolean;
}

export function SchoolMoments({ maxItems = 5, compact = false }: SchoolMomentsProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['school', 'moments'],
    queryFn: getSchoolMoments,
  });

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: Math.min(maxItems, 2) }).map((_, i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg border border-slate-200 bg-slate-50" />
        ))}
      </div>
    );
  }

  const moments = data?.moments?.slice(0, maxItems) ?? [];
  if (moments.length === 0) return null;

  return (
    <div className="space-y-2">
      {!compact ? (
        <h4 className="text-sm font-semibold text-slate-700">Подсказки</h4>
      ) : null}
      {moments.map((m) => (
        <MomentCard key={m.id} moment={m} compact={compact} />
      ))}
    </div>
  );
}
