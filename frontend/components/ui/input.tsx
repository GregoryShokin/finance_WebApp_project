import { forwardRef, InputHTMLAttributes } from 'react';
import { cn } from '@/lib/utils/cn';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        'flex h-11 w-full rounded-xl border bg-white px-3 py-2 text-sm outline-none transition placeholder:text-slate-400 focus:border-slate-400',
        className,
      )}
      {...props}
    />
  );
});
