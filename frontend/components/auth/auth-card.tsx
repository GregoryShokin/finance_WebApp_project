import { ReactNode } from 'react';
import { Card } from '@/components/ui/card';

export function AuthCard({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <Card className="w-full max-w-md p-8">
      <div className="mb-6 space-y-2">
        <h1 className="text-2xl font-semibold">{title}</h1>
        <p className="text-sm text-slate-500">{description}</p>
      </div>
      {children}
    </Card>
  );
}
