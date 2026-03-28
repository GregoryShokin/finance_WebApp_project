'use client';

import type { LucideIcon } from 'lucide-react';
import {
  BookOpen,
  Car,
  Clapperboard,
  Gift,
  HeartPulse,
  House,
  PawPrint,
  Plane,
  Shirt,
  ShoppingBag,
  ShoppingBasket,
  Smartphone,
  Sparkles,
  Tag,
  UtensilsCrossed,
} from 'lucide-react';

const categoryIconMap: Record<string, LucideIcon> = {
  'book-open': BookOpen,
  car: Car,
  clapperboard: Clapperboard,
  gift: Gift,
  'heart-pulse': HeartPulse,
  house: House,
  'paw-print': PawPrint,
  plane: Plane,
  shirt: Shirt,
  'shopping-bag': ShoppingBag,
  'shopping-basket': ShoppingBasket,
  smartphone: Smartphone,
  sparkles: Sparkles,
  tag: Tag,
  'utensils-crossed': UtensilsCrossed,
};

export function CategoryIcon({ iconName, className = 'size-5' }: { iconName?: string | null; className?: string }) {
  const Icon = categoryIconMap[iconName ?? ''] ?? Tag;
  return <Icon className={className} />;
}
