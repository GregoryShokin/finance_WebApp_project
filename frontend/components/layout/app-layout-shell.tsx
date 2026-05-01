"use client";

import { ReactNode, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from './sidebar';
import { Header } from './header';
import { useAuth } from '@/hooks/use-auth';
import { ErrorState, LoadingState } from '@/components/states/page-state';

export function AppLayoutShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { user, isLoading, token, error, mounted } = useAuth();
  // Mobile sidebar drawer state. lg+ ignores it (sidebar always sticky there).
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Redirect to login when token expires or becomes invalid
  useEffect(() => {
    if (mounted && !token) {
      router.replace('/login');
    }
  }, [mounted, token, router]);

  if (!mounted) {
    return (
      <div className="flex min-h-screen bg-bg">
        <aside className="hidden w-[232px] shrink-0 border-r border-line bg-bg-surface2 p-3.5 lg:block" />
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="sticky top-0 z-10 h-[72px] border-b border-line bg-bg/95 backdrop-blur" />
          <main className="flex-1 px-4 py-6 lg:px-7 lg:py-7" />
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
    <div className="flex min-h-screen bg-bg">
      <Sidebar
        isMobileOpen={mobileMenuOpen}
        onMobileClose={() => setMobileMenuOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          user={user}
          onMobileMenuToggle={() => setMobileMenuOpen((v) => !v)}
        />
        <main className="flex-1 px-4 py-6 lg:px-7 lg:py-7 2xl:px-12">
          {/* Контейнер растёт со ступенями: до xl — комфортная читаемая ширина
              (1280px), на 2xl полностью занимает экран минус боковой padding.
              На FullHD (1920px) это даёт ~1840px контентной зоны вместо
              старых 1280px. */}
          <div className="mx-auto w-full max-w-7xl 2xl:max-w-none">{children}</div>
        </main>
      </div>
    </div>
  );
}
