import { ButtonHTMLAttributes, forwardRef } from 'react';
import { cn } from '@/lib/utils/cn';

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'default' | 'sm' | 'icon';
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = 'primary', size = 'default', type = 'button', ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        'inline-flex items-center justify-center rounded-xl text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50',
        size === 'default' && 'h-10 gap-2 px-4',
        size === 'sm' && 'h-9 gap-2 px-3.5 text-sm',
        size === 'icon' && 'size-9 shrink-0',
        variant === 'primary' && 'bg-primary text-white hover:opacity-90',
        variant === 'secondary' && 'bg-slate-100 text-foreground hover:bg-slate-200',
        variant === 'ghost' && 'bg-transparent text-foreground hover:bg-slate-100',
        variant === 'danger' && 'bg-danger text-white hover:opacity-90',
        className,
      )}
      {...props}
    />
  );
});
