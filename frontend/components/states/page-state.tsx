import { AlertCircle, Inbox, LoaderCircle } from 'lucide-react';
import { Card } from '@/components/ui/card';

export function LoadingState({ title = 'Загрузка...', description }: { title?: string; description?: string }) {
  return (
    <Card className="flex min-h-72 flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="flex size-14 items-center justify-center rounded-full bg-slate-100">
        <LoaderCircle className="size-6 animate-spin text-slate-700" />
      </div>
      <div>
        <p className="font-semibold text-slate-950">{title}</p>
        {description ? <p className="mt-1 text-sm text-slate-500">{description}</p> : null}
      </div>
    </Card>
  );
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <Card className="flex min-h-72 flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="flex size-14 items-center justify-center rounded-full bg-slate-100">
        <Inbox className="size-6 text-slate-500" />
      </div>
      <div>
        <p className="font-semibold text-slate-950">{title}</p>
        <p className="mt-1 text-sm leading-6 text-slate-500">{description}</p>
      </div>
    </Card>
  );
}

export function ErrorState({ title, description }: { title: string; description: string }) {
  return (
    <Card className="flex min-h-72 flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="flex size-14 items-center justify-center rounded-full bg-rose-50">
        <AlertCircle className="size-6 text-rose-600" />
      </div>
      <div>
        <p className="font-semibold text-slate-950">{title}</p>
        <p className="mt-1 text-sm leading-6 text-slate-500">{description}</p>
      </div>
    </Card>
  );
}
