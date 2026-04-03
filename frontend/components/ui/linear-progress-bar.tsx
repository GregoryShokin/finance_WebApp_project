'use client';

import { useEffect, useState } from 'react';

export function LinearProgressBar({
  value,
  tone,
}: {
  value: number;
  tone: string;
}) {
  const capped = Math.max(0, Math.min(value, 100));
  const [width, setWidth] = useState(0);

  useEffect(() => {
    setWidth(capped);
  }, [capped]);

  return (
    <div className="mt-4">
      <div className="h-[6px] w-full overflow-hidden rounded-[3px] bg-[#F1EFE8]">
        <div
          className="h-full rounded-[3px]"
          style={{
            width: `${width}%`,
            backgroundColor: tone,
            transition: 'width 600ms ease',
          }}
        />
      </div>
      <div className="mt-1 flex items-center justify-between text-[10px] text-[#B4B2A9]">
        <span>0%</span>
        <span>100% (свобода)</span>
      </div>
    </div>
  );
}
