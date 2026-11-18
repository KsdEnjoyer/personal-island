import type { Task } from '../types';

export function reviewTime(task: Task): number {
  return Date.parse(task.reminder_at || task.due_at || '');
}

/** Repeated reviews depend on unfinished work, not one-shot delivery flags. */
export function reminderReview(tasks: Task[], now: Date): Task[] {
  const at = now.getTime();
  const horizon = at + 30 * 60_000;
  return tasks.filter(task => task.status === 'open' && reviewTime(task) <= horizon)
    .sort((a, b) => {
      const left = reviewTime(a), right = reviewTime(b);
      const leftMissed = left <= at, rightMissed = right <= at;
      if (leftMissed !== rightMissed) return leftMissed ? -1 : 1;
      return (leftMissed ? right - left : left - right) || a.id - b.id;
    });
}
