export function resolveExpandUp(card: HTMLElement, estimatedExpandedHeight: number): boolean {
  const rect = card.getBoundingClientRect();
  const spaceBelow = window.innerHeight - rect.bottom;
  return spaceBelow < estimatedExpandedHeight;
}

export function resolveExpandDirection(card: HTMLElement, maxExpandedWidth = 860): 'left' | 'right' {
  const rect = card.getBoundingClientRect();
  const expandedWidth = Math.min(maxExpandedWidth, window.innerWidth - 32);
  const spaceRight = window.innerWidth - rect.left;
  return spaceRight >= expandedWidth ? 'right' : 'left';
}
