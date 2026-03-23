"use client";

import { ReactNode } from 'react';
import { Sidebar } from './sidebar';
import { Header } from './header';
import { useAuth } from '@/hooks/use-auth';
import { ErrorState, LoadingState } from '@/components/states/page-state';

export function AppLayoutShell({ children }: { children: ReactNode }) {
  const { user, isLoading, token, error, mounted } = useAuth();

  if (!mounted) {
    return (
      <div className="flex min-h-screen bg-background">
        <aside className="hidden w-80 shrink-0 border-r border-white/60 bg-white/70 p-6 lg:block" />
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="sticky top-0 z-10 h-20 border-b border-white/60 bg-white/60 backdrop-blur" />
          <main className="flex-1 px-4 py-6 lg:px-8 lg:py-8" />
        </div>
      </div>
    );
  }

  if (token && isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="w-full max-w-xl">
          <LoadingState title="Проверяем сессию..." description="Загружаем данные профиля и готовим рабочее пространство." />
        </div>
      </div>
    );
  }

  if (token && error) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="w-full max-w-xl">
          <ErrorState title="Сессия недействительна" description="Перезайди в аккаунт, чтобы продолжить работу с данными." />
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header user={user} />
        <main className="flex-1 px-4 py-6 lg:px-8 lg:py-8">
          <div className="mx-auto w-full max-w-7xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
