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

/**
 * For a card that is about to be scaled by `scale`, returns the horizontal
 * transform-origin keyword that keeps the scaled card inside the viewport.
 *
 * With `center` (the default) the card grows `(scale - 1) * width / 2` in each
 * direction. If there is not enough space on one side, the origin is anchored
 * to the opposite edge so the card only grows inward.
 */
export function resolveExpandHorizontal(card: HTMLElement, scale: number): 'left' | 'center' | 'right' {
  const rect = card.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const margin = 16;

  const halfOverflow = ((scale - 1) * rect.width) / 2;
  const spaceLeft = rect.left - margin;
  const spaceRight = viewportWidth - rect.right - margin;

  if (spaceRight < halfOverflow && spaceLeft >= halfOverflow * 2) {
    return 'right';
  }
  if (spaceLeft < halfOverflow && spaceRight >= halfOverflow * 2) {
    return 'left';
  }
  return 'center';
}
