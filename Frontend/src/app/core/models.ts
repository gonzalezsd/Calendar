export interface Session { access_token: string; expires_in: number }
export interface CurrentUser { usuario_id: number; activo: boolean | null; es_administrador: boolean | null }
export interface User {
  usuario_id: number; nombre: string | null; apellido1: string | null; apellido2: string | null;
  activo: boolean | null; es_administrador: boolean | null; nombre_usuario: string | null;
}
export interface Project {
  proyecto_id: number; nombre: string | null; descripcion: string | null;
  duracion: number | null; restantes: number | null; color: string | null; laborable: boolean; activo: boolean;
}
export interface DateType {
  tipo_id: number; nombre: string | null; descripcion: string | null;
  color: string | null; en_borde: boolean | null; activo: boolean;
}
export interface Assignment {
  fecha: string; proyecto_id: number; nombre: string | null; color: string | null; laborable: boolean; es_prevision: boolean;
}
export interface Typing {
  fecha: string; tipo_id: number; nombre: string | null; color: string | null; en_borde: boolean | null;
}
export interface VacationColor { color: string | null; es_prevision: boolean }
export interface VacationContext { anterior: VacationColor[]; posterior: VacationColor[] }
export interface Note { fecha: string; texto: string }
export interface Reminder { recordatorio_id: number; fecha: string; hora: string | null; texto: string; repetir: boolean }
export interface RecurringReminder { recordatorio_id: number; mes: number; dia: number; hora: string | null; texto: string; repetir: boolean }
export interface CalendarData {
  asignaciones: Assignment[]; tipados: Typing[]; notas: Note[]; recordatorios: Reminder[]; contexto_vacaciones: VacationContext;
}
export interface Day {
  number: number; date: string; assignments: Assignment[]; typings: Typing[]; note: string | null; reminders: Reminder[];
}
export interface Month { name: string; days: (Day | null)[] }
export type View = 'calendar' | 'usuarios' | 'proyectos' | 'tipos' | 'recordatorios' | 'importar-exportar';
export type EditableUser = Omit<User, 'usuario_id'> & { password: string };
export type EditableProject = Omit<Project, 'proyecto_id'>;
export type EditableType = Omit<DateType, 'tipo_id'>;
