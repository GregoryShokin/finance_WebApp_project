import type { LucideIcon } from 'lucide-react';
import { CalendarDays, FileUp, FolderTree, Landmark, LayoutDashboard, ListTree, PiggyBank, ReceiptText, Target, Wallet } from 'lucide-react';

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
  { href: '/dashboard',        label: 'Дашборд',                icon: LayoutDashboard },
  { href: '/transactions',     label: 'Транзакции',             icon: ReceiptText },
  {
    label: 'Планирование',
    icon: PiggyBank,
    children: [
      { href: '/planning', label: 'План',  icon: CalendarDays },
      { href: '/goals',    label: 'Цели',  icon: Target },
    ],
  },
  { href: '/import',           label: 'Импорт',                 icon: FileUp },
  { href: '/categories',       label: 'Категории',              icon: ListTree },
  { href: '/rules',            label: 'Правила',                icon: FolderTree },
  { href: '/accounts',         label: 'Счета',                  icon: Wallet },
  { href: '/bank-connections', label: 'Банковские подключения', icon: Landmark },
];
