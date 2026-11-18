import type { Task } from '../types';
export const dayKey = (date:Date) => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
export const startOfWeek = (date:Date) => new Date(date.getFullYear(),date.getMonth(),date.getDate()-(date.getDay()+6)%7);
export const addDays = (date:Date,days:number) => new Date(date.getFullYear(),date.getMonth(),date.getDate()+days);
export const localInput = (date:Date) => new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);
export const minutesOfDay = (date:Date) => date.getHours()*60+date.getMinutes();
export const timeLabel = (date:Date) => date.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
export const taskColor = (task:Task) => task.status === 'done' ? 'green' : task.priority === 2 ? 'coral' : task.priority === 1 ? 'blue' : 'purple';
/** Group overlapping rendered deadline cards; card height is visual, never a task duration. */
export function layoutDeadlines(tasks:Task[],day:Date,hourHeight=56) {
  const cards=tasks.filter(task=>task.due_at && dayKey(new Date(task.due_at))===dayKey(day))
    .sort((a,b)=>Date.parse(a.due_at!)-Date.parse(b.due_at!) || a.id-b.id)
    .map(task=>({task,top:minutesOfDay(new Date(task.due_at!))*hourHeight/60,lane:0,lanes:1}));
  let group:typeof cards=[];
  let ends:number[]=[];
  const finish=()=>{for(const card of group)card.lanes=ends.length;group=[];ends=[];};
  for(const card of cards) {
    if (ends.length && ends.every(end=>end<=card.top)) finish();
    let lane=ends.findIndex(end=>end<=card.top);
    if(lane<0)lane=ends.length;
    card.lane=lane;ends[lane]=card.top+54;group.push(card);
  }
  finish();return cards;
}
