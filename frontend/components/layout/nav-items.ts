import { FileUp, FolderTree, Landmark, LayoutDashboard, ListTree, PiggyBank, ReceiptText, Wallet } from 'lucide-react';

export const navItems = [
  { href: '/dashboard', label: 'Дашборд', icon: LayoutDashboard },
  { href: '/transactions', label: 'Транзакции', icon: ReceiptText },
  { href: '/planning', label: 'Планирование', icon: PiggyBank },
  { href: '/import', label: 'Импорт', icon: FileUp },
  { href: '/categories', label: 'Категории', icon: ListTree },
  { href: '/rules', label: 'Правила', icon: FolderTree },
  { href: '/accounts', label: 'Счета', icon: Wallet },
  { href: '/bank-connections', label: 'Банковские подключения', icon: Landmark },
];
