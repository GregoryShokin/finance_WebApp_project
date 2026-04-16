import type { LucideIcon } from 'lucide-react';
import {
  BarChart2,
  CalendarDays,
  FileUp,
  FolderTree,
  HeartPulse,
  Landmark,
  LayoutDashboard,
  ListTree,
  PiggyBank,
  ReceiptText,
  Sparkles,
  Target,
  Wallet,
} from 'lucide-react';

export type NavLeaf = {
  href: string;
  label: string;
  icon: LucideIcon;
};

export type NavGroup = {
  label: string;
  icon: LucideIcon;
  children: NavLeaf[];
};

export type NavItem = NavLeaf | NavGroup;

export function isNavGroup(item: NavItem): item is NavGroup {
  return 'children' in item;
}

export const navItems: NavItem[] = [
  {
    label: 'Аналитика',
    icon: BarChart2,
    children: [
      { href: '/dashboard', label: 'Дашборд', icon: LayoutDashboard },
      { href: '/dashboard-new', label: 'Дашборд New', icon: Sparkles },
      { href: '/health', label: 'Финансовое здоровье', icon: HeartPulse },
    ],
  },
  { href: '/transactions', label: 'Транзакции', icon: ReceiptText },
  {
    label: 'Планирование',
    icon: PiggyBank,
    children: [
      { href: '/planning', label: 'План', icon: CalendarDays },
      { href: '/goals', label: 'Цели', icon: Target },
    ],
  },
  { href: '/import', label: 'Импорт', icon: FileUp },
  { href: '/categories', label: 'Категории', icon: ListTree },
  { href: '/rules', label: 'Правила', icon: FolderTree },
  { href: '/accounts', label: 'Активы', icon: Wallet },
  { href: '/bank-connections', label: 'Банковские подключения', icon: Landmark },
];
