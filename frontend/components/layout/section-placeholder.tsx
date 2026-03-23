import { Wrench } from 'lucide-react';
import { Card } from '@/components/ui/card';

export function SectionPlaceholder({ title, description }: { title: string; description: string }) {
  return (
    <Card className="p-6 lg:p-7">
      <div className="flex items-start gap-4">
        <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
          <Wrench className="size-5" />
        </div>
        <div>
          <p className="text-lg font-semibold text-slate-950">{title}</p>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{description}</p>
        </div>
      </div>
    </Card>
  );
}
